import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.chat_event_store import ChatEventStore
from core.reply_outbox import ReplyOutbox


def test_inbound_platform_event_is_idempotent(tmp_path):
    store = ChatEventStore(str(tmp_path / "chat_events.db"))

    first = store.record_inbound(
        "chat_1", "item_1", "buyer_1", "小林", "还在吗", "source_1", 1720000000000
    )
    second = store.record_inbound(
        "chat_1", "item_1", "buyer_1", "小林", "还在吗", "source_1", 1720000000000
    )

    events = store.list_recent(chat_id="chat_1")
    assert first.id == second.id
    assert len(events) == 1
    assert events[0].sender_name == "小林"
    assert events[0].platform_created_at is not None


def test_outbox_event_tracks_delivery_lifecycle_without_duplicate_messages(tmp_path):
    store = ChatEventStore(str(tmp_path / "chat_events.db"))
    outbox = ReplyOutbox(str(tmp_path / "reply_outbox.db"))
    record = outbox.enqueue(
        "chat_1",
        "item_1",
        "buyer_1",
        "source_1",
        "在的，可以直接拍",
        trace={"intent": "default", "routed_agent": "DefaultAgent"},
        user_text="还在吗",
        intent="default",
    )

    pending = store.sync_outbox(record)
    sending = store.sync_outbox(outbox.claim_for_send(record.dedupe_key).record)
    failed = store.sync_outbox(outbox.mark_failed(record.dedupe_key, "websocket closed"))

    events = store.list_recent(chat_id="chat_1")
    assert pending.id == sending.id == failed.id
    assert len(events) == 1
    assert events[0].status == "failed"
    assert events[0].metadata["attempt_count"] == 1
    assert events[0].metadata["delivery_reason"] == "websocket closed"


def test_seller_message_is_distinct_from_agent_reply(tmp_path):
    store = ChatEventStore(str(tmp_path / "chat_events.db"))

    event = store.record_seller(
        "chat_1", "item_1", "seller_1", "我来人工处理", "seller_source", 1720000000000
    )

    assert event.role == "seller"
    assert event.direction == "outbound"
    assert event.status == "sent"


def test_silent_terminal_decision_is_visible_as_internal_event(tmp_path):
    store = ChatEventStore(str(tmp_path / "chat_events.db"))
    outbox = ReplyOutbox(str(tmp_path / "reply_outbox.db"))
    record = outbox.enqueue(
        "chat_1", "item_1", "buyer_1", "source_1", "-", user_text="谢谢"
    )

    event = store.sync_outbox(outbox.mark_skipped(record.dedupe_key, "no_reply"))

    assert event.role == "system"
    assert event.direction == "internal"
    assert event.status == "no_reply"
    assert event.content == "Agent 判定本轮无需回复"
