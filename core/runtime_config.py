import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from core.model_provider import has_model_api_key, resolve_model_config
from utils.xianyu_utils import trans_cookies


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class RuntimeReadiness:
    mode: str
    ready: bool
    checks: List[ReadinessCheck]

    def to_dict(self):
        return {
            "mode": self.mode,
            "ready": self.ready,
            "checks": [asdict(check) for check in self.checks],
        }

    def failure_summary(self) -> str:
        return "; ".join(check.detail for check in self.checks if not check.ok)


def _available_prompt(root: Path, name: str) -> Optional[Path]:
    custom = root / "prompts" / f"{name}.txt"
    example = root / "prompts" / f"{name}_example.txt"
    if custom.is_file():
        return custom
    if example.is_file():
        return example
    return None


def diagnose_runtime(mode: str = "xianyu", root: Optional[Path] = None) -> RuntimeReadiness:
    """Validate local runtime prerequisites without exposing credentials or calling the network."""
    normalized_mode = (mode or "xianyu").strip().lower()
    project_root = Path(root or ".").resolve()
    checks: List[ReadinessCheck] = []

    config = resolve_model_config()
    model_ok = has_model_api_key()
    checks.append(ReadinessCheck(
        "model_credentials",
        model_ok,
        f"模型配置可用: provider={config.provider}, model={config.model_name}"
        if model_ok
        else "缺少有效模型密钥，请配置 AGNES_API_KEY 或 API_KEY",
    ))

    cookies_str = (os.getenv("COOKIES_STR") or "").strip()
    cookies = trans_cookies(cookies_str) if cookies_str and cookies_str != "your_cookies_here" else {}
    cookie_ok = bool(cookies.get("unb"))
    checks.append(ReadinessCheck(
        "xianyu_cookie",
        cookie_ok,
        "Cookie 格式可用且包含 unb"
        if cookie_ok
        else "COOKIES_STR 未配置或缺少 unb，无法标识闲鱼卖家账号",
    ))

    for prompt_name in ("classify_prompt", "price_prompt", "tech_prompt", "default_prompt"):
        prompt_path = _available_prompt(project_root, prompt_name)
        checks.append(ReadinessCheck(
            prompt_name,
            prompt_path is not None,
            f"提示词可用: {prompt_path.relative_to(project_root)}"
            if prompt_path
            else f"缺少 prompts/{prompt_name}.txt 或对应 example 文件",
        ))

    for check_name, relative_path in (
        ("product_info", "data/product_info.json"),
        ("product_rules", "data/product_rules.json"),
        ("human_reply_style", "data/human_reply_style.json"),
    ):
        path = project_root / relative_path
        checks.append(ReadinessCheck(
            check_name,
            path.is_file(),
            f"配置文件可用: {relative_path}" if path.is_file() else f"缺少配置文件: {relative_path}",
        ))

    required_checks = checks if normalized_mode == "xianyu" else [
        check for check in checks if check.name not in {"xianyu_cookie"}
    ]
    return RuntimeReadiness(
        mode=normalized_mode,
        ready=all(check.ok for check in required_checks),
        checks=checks,
    )
