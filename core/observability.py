from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class AgentTrace:
    """Lightweight runtime trace for one agent turn."""

    chat_id: str = ""
    user_msg: str = ""
    intent: str = ""
    routed_agent: str = ""
    bargain_count: int = 0
    no_reply: bool = False
    guardrails: List[str] = field(default_factory=list)
    price_decision: Dict[str, Any] = field(default_factory=dict)
    knowledge: Dict[str, Any] = field(default_factory=dict)
    model: Dict[str, Any] = field(default_factory=dict)
    rules: Dict[str, Any] = field(default_factory=dict)
    style: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
