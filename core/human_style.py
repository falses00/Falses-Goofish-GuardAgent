import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DEFAULT_BANNED_PHRASES = [
    "作为AI",
    "作为 AI",
    "AI客服",
    "智能客服",
    "机器人",
    "感谢咨询",
    "感谢您的咨询",
    "请问还有什么可以帮您",
    "竭诚为您服务",
    "亲亲",
    "尊敬的客户",
    "本店",
    "本商品",
]


DEFAULT_REPLACEMENTS = {
    "您好": "你好",
    "您": "你",
    "感谢咨询": "",
    "感谢你的咨询": "",
    "感谢您的咨询": "",
    "AI客服": "",
    "智能客服": "",
    "本商品": "这个",
    "本店": "我这边",
    "亲亲": "亲",
}


@dataclass
class HumanStyleProfile:
    """Human seller tone constraints used before and after LLM generation."""

    max_chars: int = 140
    max_lines: int = 2
    banned_phrases: List[str] = field(default_factory=lambda: list(DEFAULT_BANNED_PHRASES))
    replacements: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_REPLACEMENTS))

    @classmethod
    def from_dict(cls, data: Dict) -> "HumanStyleProfile":
        profile = cls()
        profile.max_chars = int(data.get("max_chars", profile.max_chars))
        profile.max_lines = int(data.get("max_lines", profile.max_lines))
        profile.banned_phrases = list(data.get("banned_phrases", profile.banned_phrases))
        profile.replacements = {**profile.replacements, **data.get("replacements", {})}
        return profile


@dataclass
class HumanStyleResult:
    safe: bool
    changed: bool
    original_length: int
    final_length: int
    violations: List[str] = field(default_factory=list)
    unresolved_violations: List[str] = field(default_factory=list)
    guardrails: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


class HumanReplyStyler:
    """Keep generated replies short, casual, and close to a real Xianyu seller tone."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.getenv("HUMAN_REPLY_STYLE_PATH", "data/human_reply_style.json"))
        self._loaded = False
        self.profile = HumanStyleProfile()

    def load(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.profile = HumanStyleProfile.from_dict(payload.get("profile", payload))
        self._loaded = True

    def build_prompt_context(self) -> str:
        self.load()
        banned = "、".join(self.profile.banned_phrases)
        return (
            "\n▲【真人卖家回复风格】:\n"
            "你是在闲鱼上卖自己东西的个人卖家，不是客服机器人。\n"
            f"默认 1-2 句，尽量不超过 {self.profile.max_chars} 字；先直接回答买家的问题，再补一句必要说明。\n"
            "语气要自然、口语、克制，可以像真人一样说“我这边”“这个”“可以的”，不要写营销文案。\n"
            f"不要出现这些客服腔或机器腔表达: {banned}。\n"
            "不要用项目符号、长段落、过度道歉、过度承诺，也不要显得像在背规则。"
        )

    def apply(self, reply: str) -> Tuple[str, HumanStyleResult]:
        self.load()
        original = (reply or "").strip()
        original_violations = self._violations(original)
        styled = self._normalize(original)
        unresolved = self._violations(styled)
        changed = styled != original
        guardrails = ["human_reply_style"]
        if original_violations or changed:
            guardrails.append("human_style_rewrite")
        if unresolved:
            guardrails.append("human_style_unresolved")

        return styled, HumanStyleResult(
            safe=not unresolved,
            changed=changed,
            original_length=len(original),
            final_length=len(styled),
            violations=original_violations,
            unresolved_violations=unresolved,
            guardrails=guardrails,
        )

    def _violations(self, text: str) -> List[str]:
        violations = []
        if not text:
            violations.append("empty_reply")
            return violations

        for phrase in self.profile.banned_phrases:
            if phrase and phrase in text:
                violations.append(f"banned_phrase:{phrase}")

        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) > self.profile.max_lines:
            violations.append("too_many_lines")
        if len(text) > self.profile.max_chars:
            violations.append("too_long")
        if re.search(r"(^|\n)\s*(?:[-*•]|\d+[.、])\s+", text):
            violations.append("list_like_reply")
        return violations

    def _normalize(self, text: str) -> str:
        text = self._strip_code_fences(text)
        text = self._remove_list_markers(text)
        text = self._drop_machine_sentences(text)

        for source, target in self.profile.replacements.items():
            text = text.replace(source, target)

        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[，,]\s*[。.!！?？]", "。", text)
        text = re.sub(r"([。.!！?？]){2,}", r"\1", text)
        text = text.strip(" \t\r\n\"'“”")
        text = self._trim_to_human_length(text)
        return text or "我这边看到了，你直接说想确认哪点就行。"

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```") and text.endswith("```"):
            text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return text

    @staticmethod
    def _remove_list_markers(text: str) -> str:
        lines = []
        for line in text.splitlines():
            lines.append(re.sub(r"^\s*(?:[-*•]|\d+[.、])\s+", "", line).strip())
        return " ".join(line for line in lines if line)

    @staticmethod
    def _drop_machine_sentences(text: str) -> str:
        parts = re.split(r"(?<=[。.!！?？])", text)
        kept = []
        machine_patterns = ["作为AI", "作为 AI", "我是AI", "我是 AI", "智能客服", "机器人"]
        for part in parts:
            if any(pattern in part for pattern in machine_patterns):
                continue
            kept.append(part)
        return "".join(kept) if kept else text

    def _trim_to_human_length(self, text: str) -> str:
        if len(text) <= self.profile.max_chars:
            return text

        sentences = [part.strip() for part in re.split(r"(?<=[。.!！?？])", text) if part.strip()]
        result = ""
        for sentence in sentences:
            if not result and len(sentence) <= self.profile.max_chars:
                result = sentence
            elif result and len(result) + len(sentence) <= self.profile.max_chars:
                result += sentence
            else:
                break
        if result:
            return result
        return text[: self.profile.max_chars].rstrip("，,；;、") + "..."
