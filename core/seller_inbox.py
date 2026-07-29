import hashlib
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from core.chat_event_store import ChatEvent, ChatEventStore
from core.manual_takeover import ManualTakeoverStore
from core.reply_outbox import ReplyOutbox, ReplyOutboxRecord


ATTENTION_STATES = {"takeover", "failed", "pending", "review"}


class SellerInbox:
    """Read model for live seller conversations with legacy Outbox fallback."""

    def __init__(
        self,
        events: ChatEventStore,
        outbox: ReplyOutbox,
        takeovers: ManualTakeoverStore,
    ):
        self.events = events
        self.outbox = outbox
        self.takeovers = takeovers

    def snapshot(
        self,
        limit: int = 100,
        query: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Dict[str, Any]:
        safe_limit = min(200, max(1, int(limit)))
        events = self.events.list_recent(limit=5000)
        outbox_records = self.outbox.list_recent(limit=2000)
        active_takeovers = {
            record.chat_id: record
            for record in self.takeovers.list(active_only=True, limit=500)
        }

        event_groups: "OrderedDict[str, list[ChatEvent]]" = OrderedDict()
        for event in events:
            event_groups.setdefault(event.chat_id, []).append(event)
        outbox_groups: "OrderedDict[str, list[ReplyOutboxRecord]]" = OrderedDict()
        for record in outbox_records:
            outbox_groups.setdefault(record.chat_id, []).append(record)

        conversations = [
            self._event_summary(chat_events, active_takeovers.get(chat_id))
            for chat_id, chat_events in event_groups.items()
        ]
        conversations.extend(
            self._legacy_summary(chat_records, active_takeovers.get(chat_id))
            for chat_id, chat_records in outbox_groups.items()
            if chat_id not in event_groups
        )
        conversations.sort(key=lambda item: item.get("last_activity_at") or "", reverse=True)

        all_counts = self._counts(conversations)
        normalized_query = " ".join((query or "").lower().split())
        if normalized_query:
            conversations = [
                conversation
                for conversation in conversations
                if normalized_query in self._search_text(conversation)
            ]
        if state:
            conversations = [conversation for conversation in conversations if conversation["state"] == state]

        return {
            "generated_at": datetime.now().astimezone().isoformat(),
            "version": self._version(events, outbox_records, active_takeovers.values()),
            "counts": all_counts,
            "items": conversations[:safe_limit],
        }

    def conversation(self, chat_id: str, limit: int = 200) -> Optional[Dict[str, Any]]:
        events = list(reversed(self.events.list_recent(limit=limit, chat_id=chat_id)))
        takeover = self.takeovers.get(chat_id)
        active_takeover = takeover if takeover and takeover.active else None
        if events:
            summary = self._event_summary(list(reversed(events)), active_takeover)
            decision = self._latest_trace(events)
            return {
                "conversation": summary,
                "messages": [self._event_message(event) for event in events],
                "takeover": active_takeover.to_dict() if active_takeover else None,
                "decision": decision,
            }

        records = list(reversed(self.outbox.list_recent(limit=limit, chat_id=chat_id)))
        if not records:
            return None
        return {
            "conversation": self._legacy_summary(list(reversed(records)), active_takeover),
            "messages": self._legacy_messages(records),
            "takeover": active_takeover.to_dict() if active_takeover else None,
            "decision": self._latest_outbox_trace(records),
        }

    @staticmethod
    def _event_summary(events_newest_first: list[ChatEvent], takeover) -> Dict[str, Any]:
        latest = max(
            events_newest_first,
            key=lambda event: (event.updated_at or event.created_at or "", event.id),
        )
        decision = SellerInbox._latest_trace(list(reversed(events_newest_first)))
        rules = decision.get("rules", {}) if isinstance(decision.get("rules"), dict) else {}
        guardrails = decision.get("guardrails", []) if isinstance(decision.get("guardrails"), list) else []
        has_fallback = SellerInbox._contains_fallback(decision.get("model", {}))
        state, state_reason = SellerInbox._event_state(latest, takeover, rules, has_fallback)
        buyer_event = next((event for event in events_newest_first if event.role == "buyer"), latest)
        return {
            "chat_id": latest.chat_id,
            "item_id": latest.item_id or buyer_event.item_id,
            "user_id": buyer_event.user_id,
            "buyer_name": buyer_event.sender_name or "买家",
            "state": state,
            "state_reason": state_reason,
            "last_message": latest.content,
            "last_message_role": latest.role,
            "last_activity_at": latest.updated_at or latest.created_at,
            "intent": latest.intent or decision.get("intent"),
            "agent": decision.get("routed_agent"),
            "guardrails": guardrails,
            "has_fallback": has_fallback,
            "delivery_status": latest.status,
            "delivery_reason": latest.metadata.get("delivery_reason"),
            "attempt_count": latest.metadata.get("attempt_count", 0),
            "record_count": len(events_newest_first),
            "buyer_message_count": sum(event.role == "buyer" for event in events_newest_first),
            "assistant_message_count": sum(event.role in {"assistant", "seller"} for event in events_newest_first),
            "takeover_expires_at": takeover.expires_at if takeover else None,
            "source": "chat_events",
        }

    @staticmethod
    def _legacy_summary(records_newest_first: list[ReplyOutboxRecord], takeover) -> Dict[str, Any]:
        latest = records_newest_first[0]
        trace = latest.trace if isinstance(latest.trace, dict) else {}
        rules = trace.get("rules", {}) if isinstance(trace.get("rules"), dict) else {}
        guardrails = trace.get("guardrails", []) if isinstance(trace.get("guardrails"), list) else []
        has_fallback = SellerInbox._contains_fallback(trace.get("model", {}))
        state, state_reason = SellerInbox._outbox_state(latest, takeover, rules, has_fallback)
        assistant_is_last = latest.reply_text != "-" and (
            latest.status == "sent" or (latest.status == "skipped" and latest.last_error == "dry_run")
        )
        return {
            "chat_id": latest.chat_id,
            "item_id": latest.item_id,
            "user_id": latest.user_id,
            "buyer_name": "买家",
            "state": state,
            "state_reason": state_reason,
            "last_message": latest.reply_text if assistant_is_last else latest.user_text or "暂无可展示文本",
            "last_message_role": "assistant" if assistant_is_last else "buyer",
            "last_activity_at": latest.updated_at or latest.created_at,
            "intent": latest.intent or trace.get("intent"),
            "agent": trace.get("routed_agent"),
            "guardrails": guardrails,
            "has_fallback": has_fallback,
            "delivery_status": SellerInbox._outbox_delivery_status(latest),
            "delivery_reason": latest.last_error,
            "attempt_count": latest.attempt_count,
            "record_count": len(records_newest_first),
            "buyer_message_count": sum(bool(record.user_text) for record in records_newest_first),
            "assistant_message_count": sum(bool(record.reply_text and record.reply_text != "-") for record in records_newest_first),
            "takeover_expires_at": takeover.expires_at if takeover else None,
            "source": "reply_outbox",
        }

    @staticmethod
    def _event_state(event: ChatEvent, takeover, rules: Dict[str, Any], has_fallback: bool) -> tuple[str, str]:
        if takeover:
            return "takeover", "人工接管中"
        if event.status == "failed":
            return "failed", "回复发送失败"
        if event.status in {"received", "pending", "sending"}:
            labels = {"received": "等待 Agent 决策", "pending": "等待发送", "sending": "正在发送"}
            return "pending", labels[event.status]
        if rules.get("safe") is False or has_fallback:
            return "review", "护栏拦截" if rules.get("safe") is False else "模型已降级"
        return "handled", "已处理"

    @staticmethod
    def _outbox_state(record, takeover, rules: Dict[str, Any], has_fallback: bool) -> tuple[str, str]:
        if takeover:
            return "takeover", "人工接管中"
        if record.status == "failed":
            return "failed", "回复发送失败"
        if record.status in {"pending", "sending"}:
            return "pending", "等待发送" if record.status == "pending" else "正在发送"
        if rules.get("safe") is False or has_fallback:
            return "review", "护栏拦截" if rules.get("safe") is False else "模型已降级"
        return "handled", "已自动处理"

    @staticmethod
    def _event_message(event: ChatEvent) -> Dict[str, Any]:
        return {
            "id": str(event.id),
            "source_message_id": event.source_message_id,
            "role": event.role,
            "sender_name": event.sender_name,
            "content": event.content,
            "timestamp": event.platform_created_at or event.created_at,
            "delivery_status": event.status,
            "delivery_reason": event.metadata.get("delivery_reason"),
            "intent": event.intent,
        }

    @staticmethod
    def _legacy_messages(records: list[ReplyOutboxRecord]) -> list[Dict[str, Any]]:
        messages = []
        for record in records:
            if record.user_text:
                messages.append({
                    "id": f"{record.id}:buyer",
                    "source_message_id": record.source_message_id,
                    "role": "buyer",
                    "sender_name": "买家",
                    "content": record.user_text,
                    "timestamp": record.created_at or record.updated_at,
                    "delivery_status": "received",
                    "intent": record.intent,
                })
            if record.reply_text and record.reply_text != "-":
                messages.append({
                    "id": f"{record.id}:assistant",
                    "source_message_id": record.source_message_id,
                    "role": "assistant",
                    "sender_name": "GuardAgent",
                    "content": record.reply_text,
                    "timestamp": record.sent_at or record.updated_at,
                    "delivery_status": SellerInbox._outbox_delivery_status(record),
                    "delivery_reason": record.last_error,
                    "intent": record.intent,
                })
        return messages

    @staticmethod
    def _latest_trace(events_ascending: list[ChatEvent]) -> Dict[str, Any]:
        for event in reversed(events_ascending):
            trace = event.metadata.get("trace") if isinstance(event.metadata, dict) else None
            if isinstance(trace, dict) and trace:
                return trace
        return {}

    @staticmethod
    def _latest_outbox_trace(records_ascending: list[ReplyOutboxRecord]) -> Dict[str, Any]:
        for record in reversed(records_ascending):
            if isinstance(record.trace, dict) and record.trace:
                return record.trace
        return {}

    @staticmethod
    def _outbox_delivery_status(record: ReplyOutboxRecord) -> str:
        if record.status in {"sent", "failed", "sending", "pending"}:
            return record.status
        if record.last_error == "dry_run":
            return "simulated"
        if record.last_error == "manual_takeover":
            return "cancelled_takeover"
        if record.last_error == "no_reply":
            return "no_reply"
        return "skipped"

    @staticmethod
    def _contains_fallback(value: Any) -> bool:
        if isinstance(value, dict):
            return value.get("status") == "fallback" or any(
                SellerInbox._contains_fallback(child) for child in value.values()
            )
        if isinstance(value, list):
            return any(SellerInbox._contains_fallback(child) for child in value)
        return False

    @staticmethod
    def _search_text(conversation: Dict[str, Any]) -> str:
        values = [
            conversation.get("chat_id"), conversation.get("item_id"),
            conversation.get("user_id"), conversation.get("buyer_name"),
            conversation.get("last_message"), conversation.get("intent"),
            conversation.get("agent"), *conversation.get("guardrails", []),
        ]
        return " ".join(str(value).lower() for value in values if value)

    @staticmethod
    def _counts(conversations: list[Dict[str, Any]]) -> Dict[str, int]:
        return {
            "total": len(conversations),
            "attention": sum(item["state"] in ATTENTION_STATES for item in conversations),
            "takeover": sum(item["state"] == "takeover" for item in conversations),
            "failed": sum(item["state"] == "failed" for item in conversations),
            "pending": sum(item["state"] == "pending" for item in conversations),
        }

    @staticmethod
    def _version(
        events: Iterable[ChatEvent],
        records: Iterable[ReplyOutboxRecord],
        takeovers: Iterable[Any],
    ) -> str:
        parts = [f"event:{event.id}:{event.status}:{event.updated_at}" for event in events]
        parts.extend(
            f"outbox:{record.id}:{record.status}:{record.updated_at}:{record.last_error}"
            for record in records
        )
        parts.extend(
            f"takeover:{record.chat_id}:{record.updated_at}:{record.expires_at}"
            for record in takeovers
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
