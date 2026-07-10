from dataclasses import dataclass
from typing import Any, Dict, Iterable, Protocol


class AgentHandler(Protocol):
    last_trace: Dict[str, Any]

    def generate(self, **kwargs) -> str:
        ...


@dataclass(frozen=True)
class AgentRegistration:
    intent: str
    handler: AgentHandler
    internal: bool = False


class AgentRegistry:
    """Runtime registry for intent handlers with one explicit fallback."""

    def __init__(self, fallback_intent: str = "default"):
        self.fallback_intent = self._normalize_intent(fallback_intent)
        self._registrations: Dict[str, AgentRegistration] = {}

    @staticmethod
    def _normalize_intent(intent: str) -> str:
        normalized = (intent or "").strip().lower()
        if not normalized:
            raise ValueError("agent intent cannot be empty")
        return normalized

    def register(self, intent: str, handler: AgentHandler, internal: bool = False, replace: bool = False) -> None:
        normalized = self._normalize_intent(intent)
        if not callable(getattr(handler, "generate", None)):
            raise TypeError(f"agent handler for {normalized} must define generate()")
        if normalized in self._registrations and not replace:
            raise ValueError(f"agent intent already registered: {normalized}")
        self._registrations[normalized] = AgentRegistration(normalized, handler, internal)

    def require(self, intent: str) -> AgentHandler:
        normalized = self._normalize_intent(intent)
        try:
            return self._registrations[normalized].handler
        except KeyError as exc:
            raise KeyError(f"agent intent is not registered: {normalized}") from exc

    def resolve(self, intent: str) -> AgentRegistration:
        normalized = self._normalize_intent(intent)
        registration = self._registrations.get(normalized)
        if registration and not registration.internal:
            return registration
        fallback = self._registrations.get(self.fallback_intent)
        if not fallback:
            raise RuntimeError(f"fallback agent is not registered: {self.fallback_intent}")
        return fallback

    def intents(self, include_internal: bool = False) -> Iterable[str]:
        return tuple(
            intent
            for intent, registration in self._registrations.items()
            if include_internal or not registration.internal
        )

    def as_dict(self) -> Dict[str, AgentHandler]:
        return {intent: registration.handler for intent, registration in self._registrations.items()}
