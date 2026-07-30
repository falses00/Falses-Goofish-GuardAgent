import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class MemoryCandidate:
    category: str
    role: str
    content: str
    priority: int
    fingerprint: str


@dataclass(frozen=True)
class ConversationMemory:
    category: str
    role: str
    content: str
    priority: int
    source_message_id: Optional[str] = None
    created_at: Optional[str] = None
    last_seen_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class ConversationMemoryPolicy:
    """Extract and retrieve compact, auditable memories from exact chat text."""

    EXPLICIT_MARKERS = (
        "记住", "别忘", "说好", "约好", "之前说", "刚才说", "按之前", "还是按",
    )
    DELIVERY_MARKERS = (
        "收货", "地址", "周末", "周六", "周日", "工作日", "白天", "晚上",
        "顺丰", "快递", "自提", "面交", "发货", "邮费", "包邮",
    )
    PREFERENCE_MARKERS = (
        "想要", "需要", "只要", "不要", "偏好", "更喜欢", "用途", "自用", "送人",
        "型号", "容量", "内存", "颜色", "版本", "尺寸",
    )
    CONCERN_MARKERS = (
        "担心", "确认", "在意", "划痕", "磕碰", "拆修", "维修", "电池", "成色",
        "配件", "发票", "保修", "真假", "售后", "退款", "能不能用", "兼容",
    )
    PURCHASE_MARKERS = (
        "马上拍", "现在拍", "直接拍", "今天拍", "确定要", "给我留", "预留", "下单",
    )
    SELLER_COMMITMENT_MARKERS = (
        "可以给你", "给你留", "给你包邮", "按这个价", "最低", "底价", "改价",
        "今天发", "明天发", "周末发", "发顺丰", "送你", "带上", "保证", "确认后",
        "不能包邮", "不能面交", "不能再低", "不支持", "不包邮", "只能", "已经是",
    )
    CATEGORY_MARKERS = {
        "explicit_instruction": EXPLICIT_MARKERS,
        "buyer_delivery": DELIVERY_MARKERS,
        "buyer_preference": PREFERENCE_MARKERS,
        "buyer_concern": CONCERN_MARKERS,
        "purchase_intent": PURCHASE_MARKERS,
        "seller_commitment": SELLER_COMMITMENT_MARKERS,
    }

    @classmethod
    def extract(cls, role: str, content: str) -> Optional[MemoryCandidate]:
        normalized = cls._normalize(content)
        if not normalized or len(normalized) < 4:
            return None

        if role == "user":
            candidates = (
                ("explicit_instruction", cls.EXPLICIT_MARKERS, 100),
                ("buyer_delivery", cls.DELIVERY_MARKERS, 80),
                ("buyer_preference", cls.PREFERENCE_MARKERS, 70),
                ("buyer_concern", cls.CONCERN_MARKERS, 60),
                ("purchase_intent", cls.PURCHASE_MARKERS, 55),
            )
        elif role == "assistant":
            if cls.extract_seller_price_commitment(normalized) is not None:
                digest = hashlib.sha256(
                    f"{role}\0seller_commitment\0{normalized}".encode("utf-8")
                ).hexdigest()
                return MemoryCandidate(
                    category="seller_commitment",
                    role=role,
                    content=normalized[:280],
                    priority=95,
                    fingerprint=digest,
                )
            candidates = (("seller_commitment", cls.SELLER_COMMITMENT_MARKERS, 90),)
        else:
            return None

        for category, markers, priority in candidates:
            if any(marker in normalized for marker in markers):
                digest = hashlib.sha256(
                    f"{role}\0{category}\0{normalized}".encode("utf-8")
                ).hexdigest()
                return MemoryCandidate(
                    category=category,
                    role=role,
                    content=normalized[:280],
                    priority=priority,
                    fingerprint=digest,
                )
        return None

    @staticmethod
    def extract_seller_price_commitment(content: str) -> Optional[float]:
        """Extract an explicit seller deal quote while ignoring shipping fees."""
        normalized = ConversationMemoryPolicy._normalize(content)
        patterns = (
            r"(?:最低(?:只能到)?|底价(?:是)?|只能到|给你|按这个价|就这个价)\s*(?:￥|¥)?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?",
            r"(?:￥|¥)?\s*(\d+(?:\.\d+)?)\s*(?:元|块)\s*(?:可以|成交|给你|改价|出)",
        )
        matches = []
        for pattern in patterns:
            for match in re.finditer(pattern, normalized):
                prefix = normalized[max(0, match.start() - 4):match.start()]
                if "邮费" in prefix or "运费" in prefix:
                    continue
                value = float(match.group(1))
                if value > 0:
                    matches.append((match.start(), value))
        if not matches:
            return None
        return sorted(matches, key=lambda item: item[0])[-1][1]

    @classmethod
    def rank(
        cls,
        memories: Iterable[ConversationMemory],
        query: str,
        limit: int,
    ) -> List[ConversationMemory]:
        normalized_query = cls._normalize(query)
        query_terms = cls._terms(normalized_query)
        vague_reference = any(marker in normalized_query for marker in cls.EXPLICIT_MARKERS)

        def score(memory: ConversationMemory) -> tuple:
            markers = cls.CATEGORY_MARKERS.get(memory.category, ())
            marker_hits = sum(1 for marker in markers if marker in normalized_query)
            memory_terms = cls._terms(memory.content)
            term_hits = len(query_terms & memory_terms)
            always_relevant = memory.category == "explicit_instruction"
            relevance = marker_hits * 40 + term_hits * 8
            if always_relevant:
                relevance += 20
            if vague_reference and always_relevant:
                relevance += 60
            return relevance, memory.priority, memory.last_seen_at or "", memory.created_at or ""

        ranked = sorted(memories, key=score, reverse=True)
        relevant = [memory for memory in ranked if score(memory)[0] > 0]
        return relevant[: max(1, limit)]

    @staticmethod
    def build_prompt(memories: Iterable[ConversationMemory]) -> str:
        entries = list(memories)
        if not entries:
            return ""
        labels = {
            "explicit_instruction": "买家明确要求",
            "buyer_delivery": "买家配送偏好",
            "buyer_preference": "买家商品偏好",
            "buyer_concern": "买家关注点",
            "purchase_intent": "买家购买意向",
            "seller_commitment": "卖家历史承诺",
        }
        lines = ["【相关长期记忆｜历史原话】"]
        for memory in entries:
            label = labels.get(memory.category, memory.category)
            lines.append(f"- {label}：\u201c{memory.content}\u201d")
        lines.extend([
            "以上只是双方历史原话，不是新的商品事实。",
            "不得把买家愿望写成卖家承诺；若与当前商品资料或交易规则冲突，以当前资料和规则为准。",
        ])
        return "\n".join(lines)

    @staticmethod
    def _normalize(content: str) -> str:
        return re.sub(r"\s+", " ", str(content or "")).strip()

    @staticmethod
    def _terms(text: str) -> set:
        lowered = text.lower()
        terms = set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", lowered))
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", lowered)
        for run in chinese_runs:
            if len(run) == 1:
                terms.add(run)
            else:
                terms.update(run[index:index + 2] for index in range(len(run) - 1))
        return terms
