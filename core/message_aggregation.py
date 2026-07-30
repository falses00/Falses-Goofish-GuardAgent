import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


AggregationKey = Tuple[str, str, str]


@dataclass
class MessageBatch:
    chat_id: str
    item_id: str
    user_id: str
    messages: List[str] = field(default_factory=list)
    source_message_ids: List[str] = field(default_factory=list)
    first_seen_ms: int = 0
    last_seen_ms: int = 0

    @property
    def count(self) -> int:
        return len(self.messages)

    def combined_text(self) -> str:
        if len(self.messages) == 1:
            return self.messages[0]
        lines = ["用户连续发送了以下消息，请合并理解后只回复一次："]
        lines.extend(f"{index}. {message}" for index, message in enumerate(self.messages, start=1))
        return "\n".join(lines)

    def durable_source_message_id(self) -> str:
        """Stable identity for the exact ordered set of platform messages."""
        if not self.source_message_ids:
            return ""
        digest = hashlib.sha256("\x1f".join(self.source_message_ids).encode("utf-8")).hexdigest()[:24]
        return f"batch:{digest}"


class MessageAggregator:
    """Debounce consecutive buyer messages before they enter the agent loop."""

    def __init__(self, debounce_seconds: float = 1.2, max_messages: int = 5, max_chars: int = 1200):
        self.debounce_seconds = max(0.0, float(debounce_seconds))
        self.debounce_ms = int(self.debounce_seconds * 1000)
        self.max_messages = max(1, int(max_messages))
        self.max_chars = max(1, int(max_chars))
        self._buffers: Dict[AggregationKey, MessageBatch] = {}

    def key_for(self, chat_id: str, item_id: str, user_id: str) -> AggregationKey:
        return chat_id, item_id, user_id

    def append(
        self,
        chat_id: str,
        item_id: str,
        user_id: str,
        text: str,
        now_ms: int,
    ) -> Tuple[AggregationKey, bool]:
        key, should_flush, _ = self.append_once(
            chat_id,
            item_id,
            user_id,
            text,
            now_ms,
        )
        return key, should_flush

    def append_once(
        self,
        chat_id: str,
        item_id: str,
        user_id: str,
        text: str,
        now_ms: int,
        source_message_id: Optional[str] = None,
    ) -> Tuple[AggregationKey, bool, bool]:
        key = self.key_for(chat_id, item_id, user_id)
        clean_text = text.strip()
        batch = self._buffers.get(key)
        if not batch:
            batch = MessageBatch(
                chat_id=chat_id,
                item_id=item_id,
                user_id=user_id,
                first_seen_ms=now_ms,
                last_seen_ms=now_ms,
            )
            self._buffers[key] = batch

        normalized_source_id = str(source_message_id or "").strip()
        if normalized_source_id and normalized_source_id in batch.source_message_ids:
            should_flush = batch.count >= self.max_messages or len(batch.combined_text()) >= self.max_chars
            return key, should_flush, False

        batch.messages.append(clean_text)
        if normalized_source_id:
            batch.source_message_ids.append(normalized_source_id)
        batch.last_seen_ms = now_ms
        should_flush = batch.count >= self.max_messages or len(batch.combined_text()) >= self.max_chars
        return key, should_flush, True

    def pop(self, key: AggregationKey) -> Optional[MessageBatch]:
        return self._buffers.pop(key, None)

    def pop_ready(self, now_ms: int) -> List[MessageBatch]:
        ready = []
        for key, batch in list(self._buffers.items()):
            if now_ms - batch.last_seen_ms >= self.debounce_ms:
                ready.append(self._buffers.pop(key))
        return ready

    def flush_all(self) -> List[MessageBatch]:
        batches = list(self._buffers.values())
        self._buffers.clear()
        return batches
