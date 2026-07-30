import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.chat_event_store import ChatEventStore
from core.reply_outbox import ReplyOutbox


def test_inbound_platform_event_is_idempotent(tmp_path):
    store = ChatEventStore(str(tmp_path / "chat_events.db"))

    first, first_created = store.record_inbound_once(
        "chat_1", "item_1", "buyer_1", "小林", "还在吗", "source_1", 1720000000000
    )
    second, second_created = store.record_inbound_once(
        "chat_1", "item_1", "buyer_1", "错误重放名称", "错误重放正文", "source_1", 1720000009000
    )

    events = store.list_recent(chat_id="chat_1")
    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert first.updated_at == second.updated_at
    assert len(events) == 1
    assert events[0].sender_name == "小林"
    assert events[0].content == "还在吗"
    assert events[0].platform_created_at is not None


def test_inbound_fact_links_to_outbox_without_changing_activity_time(tmp_path):
    store = ChatEventStore(str(tmp_path / "chat_events.db"))
    event = store.record_inbound(
        "chat_1", "item_1", "buyer_1", "小林", "还在吗", "source_1", 1720000000000
    )

    linked = store.link_inbound_to_outbox(["source_1", "source_1"], "outbox_key_1")
    replayed, created = store.record_inbound_once(
        "chat_1", "item_1", "buyer_1", "小林", "还在吗", "source_1", 1720000000000
    )

    assert linked == 1
    assert created is False
    assert replayed.status == "processed"
    assert replayed.outbox_dedupe_key == "outbox_key_1"
    assert replayed.updated_at == event.updated_at
    assert store.linked_outbox_key(["source_1"]) == "outbox_key_1"
    assert store.linked_outbox_key(["source_1", "missing"]) is None


def test_near_term_timestamp_drift_reuses_canonical_buyer_source_id(tmp_path):
    store = ChatEventStore(str(tmp_path / "chat_events.db"))
    first, first_created = store.record_inbound_once(
        "chat_1", "item_1", "buyer_1", "小林", "还在吗", "source_ts_1", 1720000000000
    )
    replayed, replay_created = store.record_inbound_once(
        "chat_1", "item_1", "buyer_1", "小林", "还在吗", "source_ts_2", 1720000009000
    )

    assert first_created is True
    assert replay_created is False
    assert replayed.id == first.id
    assert replayed.source_message_id == "source_ts_1"
    assert len(store.list_recent(chat_id="chat_1")) == 1


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


def test_global_recent_events_prioritize_late_status_updates(tmp_path):
    store = ChatEventStore(str(tmp_path / "chat_events.db"))
    outbox = ReplyOutbox(str(tmp_path / "reply_outbox.db"))
    old_record = outbox.enqueue("chat_old", "item_1", "buyer_1", "source_1", "旧回复")
    store.sync_outbox(old_record)
    store.record_inbound("chat_new", "item_2", "buyer_2", "新买家", "新消息", "source_2")

    outbox.claim_for_send(old_record.dedupe_key)
    store.sync_outbox(outbox.mark_failed(old_record.dedupe_key, "late failure"))

    latest = store.list_recent(limit=1)[0]
    assert latest.chat_id == "chat_old"
    assert latest.status == "failed"


def test_seller_message_is_distinct_from_agent_reply(tmp_path):
    store = ChatEventStore(str(tmp_path / "chat_events.db"))

    event, created = store.record_seller_once(
        "chat_1", "item_1", "seller_1", "我来人工处理", "seller_source", 1720000000000
    )
    replayed, replay_created = store.record_seller_once(
        "chat_1", "item_1", "seller_1", "我来人工处理", "seller_source_drift", 1720000009000
    )

    assert created is True
    assert replay_created is False
    assert event.role == "seller"
    assert event.direction == "outbound"
    assert event.status == "sent"
    assert replayed.content == "我来人工处理"
    assert replayed.updated_at == event.updated_at


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
