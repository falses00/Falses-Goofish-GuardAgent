import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.chat_event_store import ChatEventStore
from core.manual_takeover import ManualTakeoverStore
from core.reply_outbox import ReplyOutbox
from core.seller_inbox import SellerInbox


def build_inbox(tmp_path):
    events = ChatEventStore(str(tmp_path / "chat_events.db"))
    outbox = ReplyOutbox(str(tmp_path / "reply_outbox.db"))
    takeovers = ManualTakeoverStore(str(tmp_path / "manual_takeovers.db"))
    return SellerInbox(events, outbox, takeovers), events, outbox, takeovers


def seed_reply(events, outbox):
    events.record_inbound(
        "chat_1", "item_1", "buyer_1", "小林", "最低多少", "source_1", 1720000000000
    )
    record = outbox.enqueue(
        "chat_1",
        "item_1",
        "buyer_1",
        "source_1",
        "目前最低 4200 元",
        trace={
            "intent": "price",
            "routed_agent": "PriceAgent",
            "rules": {"safe": True},
            "guardrails": [],
            "model": {"status": "success"},
        },
        user_text="最低多少",
        intent="price",
    )
    events.sync_outbox(record)
    return record


def test_snapshot_and_detail_follow_real_delivery_state(tmp_path):
    inbox, events, outbox, _ = build_inbox(tmp_path)
    record = seed_reply(events, outbox)

    pending = inbox.snapshot()
    detail = inbox.conversation("chat_1")

    assert pending["counts"] == {
        "total": 1,
        "attention": 1,
        "takeover": 0,
        "failed": 0,
        "pending": 1,
    }
    assert pending["items"][0]["buyer_name"] == "小林"
    assert pending["items"][0]["agent"] == "PriceAgent"
    assert [message["role"] for message in detail["messages"]] == ["buyer", "assistant"]

    outbox.claim_for_send(record.dedupe_key)
    sent = outbox.mark_sent(record.dedupe_key)
    events.sync_outbox(sent)
    handled = inbox.snapshot()

    assert handled["items"][0]["state"] == "handled"
    assert handled["items"][0]["delivery_status"] == "sent"
    assert handled["counts"]["attention"] == 0


def test_takeover_search_and_state_filter_are_composable(tmp_path):
    inbox, events, outbox, takeovers = build_inbox(tmp_path)
    seed_reply(events, outbox)
    takeovers.enable("chat_1", item_id="item_1", ttl_seconds=600, note="买家要求人工")

    result = inbox.snapshot(query="小林", state="takeover")
    missing = inbox.snapshot(query="不存在", state="takeover")

    assert len(result["items"]) == 1
    assert result["items"][0]["state_reason"] == "人工接管中"
    assert result["counts"]["takeover"] == 1
    assert missing["items"] == []


def test_legacy_outbox_is_visible_before_chat_event_migration(tmp_path):
    inbox, _, outbox, _ = build_inbox(tmp_path)
    record = outbox.enqueue(
        "legacy_chat", "legacy_item", "buyer_9", "source_9", "在的", user_text="还在吗"
    )
    outbox.claim_for_send(record.dedupe_key)
    outbox.mark_sent(record.dedupe_key)

    result = inbox.snapshot(query="legacy_chat")
    detail = inbox.conversation("legacy_chat")

    assert result["items"][0]["source"] == "reply_outbox"
    assert [message["role"] for message in detail["messages"]] == ["buyer", "assistant"]


def test_no_reply_terminal_event_does_not_leave_conversation_pending(tmp_path):
    inbox, events, outbox, _ = build_inbox(tmp_path)
    events.record_inbound(
        "chat_silent", "item_1", "buyer_1", "小林", "谢谢", "silent_source"
    )
    record = outbox.enqueue(
        "chat_silent", "item_1", "buyer_1", "silent_source", "-", user_text="谢谢"
    )
    events.sync_outbox(outbox.mark_skipped(record.dedupe_key, "no_reply"))

    result = inbox.snapshot()
    detail = inbox.conversation("chat_silent")

    assert result["items"][0]["state"] == "handled"
    assert result["counts"]["pending"] == 0
    assert detail["messages"][-1]["role"] == "system"
    assert detail["messages"][-1]["delivery_status"] == "no_reply"


def test_late_failure_on_older_outbox_event_becomes_latest_attention_state(tmp_path):
    inbox, events, outbox, _ = build_inbox(tmp_path)
    events.record_inbound(
        "chat_late_failure", "item_1", "buyer_1", "小林", "第一条", "source_1"
    )
    record = outbox.enqueue(
        "chat_late_failure", "item_1", "buyer_1", "source_1", "第一条回复", user_text="第一条"
    )
    events.sync_outbox(record)
    events.record_inbound(
        "chat_late_failure", "item_1", "buyer_1", "小林", "后发的新消息", "source_2"
    )
    outbox.claim_for_send(record.dedupe_key)
    events.sync_outbox(outbox.mark_failed(record.dedupe_key, "late websocket failure"))

    result = inbox.snapshot()

    assert result["items"][0]["state"] == "failed"
    assert result["items"][0]["delivery_reason"] == "late websocket failure"
    assert result["items"][0]["last_message"] == "第一条回复"


def test_query_finds_conversation_outside_default_result_window(tmp_path):
    inbox, events, _, _ = build_inbox(tmp_path)
    events.record_inbound(
        "old_target", "target_item", "target_buyer", "唯一买家", "唯一历史消息", "source_target"
    )
    timestamp = "2099-07-31T00:00:00+08:00"
    rows = [
        (
            f"in:source_{index}", f"new_chat_{index}", f"item_{index}", f"buyer_{index}",
            f"买家{index}", "buyer", "inbound", f"较新的消息 {index}", "received",
            f"source_{index}", None, None, None, "{}", timestamp, timestamp,
        )
        for index in range(5100)
    ]
    with events._connection() as conn:
        conn.executemany(
            """
            INSERT INTO chat_events (
                event_key, chat_id, item_id, user_id, sender_name, role, direction,
                content, status, source_message_id, outbox_dedupe_key, intent,
                platform_created_at, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    unfiltered = inbox.snapshot(limit=200)
    searched = inbox.snapshot(limit=200, query="唯一历史消息")

    assert all(item["chat_id"] != "old_target" for item in unfiltered["items"])
    assert [item["chat_id"] for item in searched["items"]] == ["old_target"]


def test_duplicate_inbound_replay_does_not_reopen_handled_conversation(tmp_path):
    inbox, events, outbox, _ = build_inbox(tmp_path)
    record = seed_reply(events, outbox)
    outbox.claim_for_send(record.dedupe_key)
    sent = outbox.mark_sent(record.dedupe_key)
    events.link_inbound_to_outbox(["source_1"], sent.dedupe_key)
    events.sync_outbox(sent)

    before = inbox.snapshot()["items"][0]
    replayed, created = events.record_inbound_once(
        "chat_1", "item_1", "buyer_1", "小林", "还在吗", "source_1"
    )
    after = inbox.snapshot()["items"][0]

    assert before["state"] == "handled"
    assert created is False
    assert replayed.outbox_dedupe_key == sent.dedupe_key
    assert after["state"] == "handled"
    assert after["last_message"] == sent.reply_text


def test_change_token_tracks_event_outbox_and_takeover_transitions(tmp_path):
    inbox, events, outbox, takeovers = build_inbox(tmp_path)
    initial = inbox.change_token()
    events.record_inbound("chat_1", "item_1", "buyer_1", "小林", "还在吗", "source_1")
    after_event = inbox.change_token()
    record = outbox.enqueue("chat_1", "item_1", "buyer_1", "source_1", "在的")
    after_outbox = inbox.change_token()
    takeovers.enable("chat_1", ttl_seconds=600)
    after_takeover = inbox.change_token()

    assert len({initial, after_event, after_outbox, after_takeover}) == 4
    assert inbox.change_token() == after_takeover
