import asyncio
import base64
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from XianyuAgent import XianyuReplyBot
from context_manager import ChatContextManager
from core.evaluation import DeterministicLLMClient
from core.manual_takeover import ManualTakeoverStore
from core.reply_outbox import ReplyOutbox
from main import XianyuLive


class FakeSession:
    def __init__(self):
        self.cookies = {}


class FakeXianyuApi:
    def __init__(self):
        self.session = FakeSession()

    def get_item_info(self, item_id):
        raise AssertionError(f"unexpected item API call for {item_id}")


class RecordingWebSocket:
    def __init__(self, error=None):
        self.error = error
        self.payloads = []

    async def send(self, payload):
        if self.error:
            raise self.error
        self.payloads.append(json.loads(payload))


def build_live(tmp_path, dry_run):
    bot = XianyuReplyBot(
        client=DeterministicLLMClient(),
        db_path=str(tmp_path / "chat_history.db"),
    )
    outbox = ReplyOutbox(db_path=str(tmp_path / "reply_outbox.db"))
    takeover_store = ManualTakeoverStore(str(tmp_path / "manual_takeovers.db"))
    live = XianyuLive(
        "unb=test_seller",
        reply_bot=bot,
        context_manager=bot.db,
        xianyu_api=FakeXianyuApi(),
        reply_outbox=outbox,
        reply_send_dry_run=dry_run,
        manual_takeover_store=takeover_store,
    )
    live.simulate_human_typing = False
    bot.db.save_item_info("item_1", {
        "title": "二手 iPad Pro",
        "desc": "屏幕贴膜使用，无拆修，电池健康 93%",
        "soldPrice": 4299,
        "quantity": 1,
        "skuList": [],
    })
    return live, bot, outbox


def source_id(message="在吗，这个屏幕有划痕吗？"):
    return ReplyOutbox.build_source_message_id(
        "chat_1",
        "item_1",
        "buyer_1",
        message,
        event_time_ms=1720000000000,
    )


def process(live, websocket, message="在吗，这个屏幕有划痕吗？", event_id=None):
    return asyncio.run(live._process_buyer_message(
        websocket,
        "chat_1",
        "buyer_1",
        "item_1",
        message,
        source_message_id=event_id or source_id(message),
    ))


def test_live_dry_run_records_once_without_network_send(tmp_path):
    live, bot, outbox = build_live(tmp_path, dry_run=True)
    websocket = RecordingWebSocket()
    event_id = source_id()

    process(live, websocket, event_id=event_id)
    process(live, websocket, event_id=event_id)

    dedupe_key = ReplyOutbox.build_dedupe_key("chat_1", "item_1", "buyer_1", event_id)
    record = outbox.get(dedupe_key)
    snapshot = bot.db.get_memory_snapshot("chat_1")

    assert record.status == "skipped"
    assert record.last_error == "dry_run"
    assert record.attempt_count == 1
    assert len(snapshot.messages) == 2
    assert websocket.payloads == []


def test_live_price_memory_commits_after_takeover_gate(tmp_path):
    live, bot, _ = build_live(tmp_path, dry_run=True)

    process(live, RecordingWebSocket(), message="3000 元能出吗", event_id=source_id("3000 元能出吗"))

    snapshot = bot.db.get_memory_snapshot("chat_1")
    assert snapshot.bargain_count == 1
    assert snapshot.lowest_price_committed is not None
    assert snapshot.buyer_highest_offer == 3000
    assert [message["role"] for message in snapshot.messages] == ["user", "assistant"]


def test_live_retry_reuses_failed_reply_without_duplicate_memory(tmp_path):
    live, bot, outbox = build_live(tmp_path, dry_run=False)
    event_id = source_id()

    with pytest.raises(RuntimeError, match="websocket closed"):
        process(live, RecordingWebSocket(RuntimeError("websocket closed")), event_id=event_id)

    dedupe_key = ReplyOutbox.build_dedupe_key("chat_1", "item_1", "buyer_1", event_id)
    failed_record = outbox.get(dedupe_key)
    original_reply = failed_record.reply_text
    first_snapshot = bot.db.get_memory_snapshot("chat_1")

    websocket = RecordingWebSocket()
    process(live, websocket, event_id=event_id)

    sent_record = outbox.get(dedupe_key)
    second_snapshot = bot.db.get_memory_snapshot("chat_1")
    encoded_payload = websocket.payloads[0]["body"][0]["content"]["custom"]["data"]

    assert failed_record.status == "failed"
    assert sent_record.status == "sent"
    assert sent_record.reply_text == original_reply
    assert sent_record.attempt_count == 2
    assert first_snapshot.messages == []
    assert len(second_snapshot.messages) == 2
    decoded_content = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    assert decoded_content["text"]["text"] == original_reply


def test_live_recovers_pending_reply_without_agent_generation(tmp_path):
    live, bot, outbox = build_live(tmp_path, dry_run=False)
    event_id = source_id("刚才的回复发一下")
    pending = outbox.enqueue(
        "chat_1",
        "item_1",
        "buyer_1",
        event_id,
        "在的，刚才网络断了一下。",
    )
    websocket = RecordingWebSocket()

    process(live, websocket, message="刚才的回复发一下", event_id=event_id)

    record = outbox.get(pending.dedupe_key)
    snapshot = bot.db.get_memory_snapshot("chat_1")
    encoded_payload = websocket.payloads[0]["body"][0]["content"]["custom"]["data"]
    decoded_content = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))

    assert record.status == "sent"
    assert record.attempt_count == 1
    assert snapshot.messages == []
    assert decoded_content["text"]["text"] == pending.reply_text


def test_manual_takeover_records_buyer_message_without_agent_or_network(tmp_path, monkeypatch):
    live, bot, outbox = build_live(tmp_path, dry_run=False)
    live.enter_manual_mode("chat_1", item_id="item_1")
    monkeypatch.setattr(
        bot,
        "generate_reply",
        lambda *args, **kwargs: pytest.fail("agent must not run during takeover"),
    )
    websocket = RecordingWebSocket()
    event_id = source_id("我刚付款了，怎么发货")

    process(live, websocket, message="我刚付款了，怎么发货", event_id=event_id)

    dedupe_key = ReplyOutbox.build_dedupe_key("chat_1", "item_1", "buyer_1", event_id)
    record = outbox.get(dedupe_key)
    snapshot = bot.db.get_memory_snapshot("chat_1")
    assert record.status == "skipped"
    assert record.last_error == "manual_takeover"
    assert record.attempt_count == 0
    assert [message["role"] for message in snapshot.messages] == ["user"]
    assert websocket.payloads == []


def test_duplicate_takeover_events_write_buyer_memory_once(tmp_path, monkeypatch):
    live, bot, outbox = build_live(tmp_path, dry_run=False)
    live.enter_manual_mode("chat_1", item_id="item_1")
    event_id = source_id("同一条接管消息")
    dedupe_key = ReplyOutbox.build_dedupe_key("chat_1", "item_1", "buyer_1", event_id)
    barrier = threading.Barrier(2)
    original_get = outbox.get

    def synchronized_initial_get(key):
        record = original_get(key)
        if key == dedupe_key and record is None:
            barrier.wait(timeout=2)
        return record

    monkeypatch.setattr(outbox, "get", synchronized_initial_get)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                process,
                live,
                RecordingWebSocket(),
                "同一条接管消息",
                event_id,
            )
            for _ in range(2)
        ]
        for future in futures:
            future.result(timeout=5)

    snapshot = bot.db.get_memory_snapshot("chat_1")
    assert [message["role"] for message in snapshot.messages] == ["user"]
    assert outbox.get(dedupe_key).last_error == "manual_takeover"


def test_takeover_cancels_pending_reply_before_recovery_send(tmp_path):
    live, bot, outbox = build_live(tmp_path, dry_run=False)
    event_id = source_id("恢复这条待发送回复")
    pending = outbox.enqueue(
        "chat_1",
        "item_1",
        "buyer_1",
        event_id,
        "这条回复不应再发送。",
    )
    ManualTakeoverStore(live.manual_takeovers.path).enable("chat_1", ttl_seconds=600)
    websocket = RecordingWebSocket()

    process(live, websocket, message="恢复这条待发送回复", event_id=event_id)

    record = outbox.get(pending.dedupe_key)
    assert record.status == "skipped"
    assert record.last_error == "manual_takeover"
    assert record.attempt_count == 0
    assert bot.db.get_memory_snapshot("chat_1").messages == []
    assert websocket.payloads == []


def test_takeover_never_rewrites_already_sent_outbox_terminal_state(tmp_path):
    live, _, outbox = build_live(tmp_path, dry_run=False)
    event_id = source_id("已经发送完成")
    record = outbox.enqueue("chat_1", "item_1", "buyer_1", event_id, "已发送回复")
    claimed = outbox.claim_for_send(record.dedupe_key)
    sent = outbox.mark_sent(claimed.record.dedupe_key)
    live.enter_manual_mode("chat_1", item_id="item_1")

    asyncio.run(live._deliver_outbox_record(RecordingWebSocket(), sent))

    assert outbox.get(sent.dedupe_key).status == "sent"


def test_takeover_during_agent_generation_discards_unsent_assistant_turn(tmp_path, monkeypatch):
    live, bot, outbox = build_live(tmp_path, dry_run=False)
    original_generate = bot.generate_reply

    def generate_then_take_over(*args, **kwargs):
        reply = original_generate(*args, **kwargs)
        ManualTakeoverStore(live.manual_takeovers.path).enable("chat_1", ttl_seconds=600)
        return reply

    monkeypatch.setattr(bot, "generate_reply", generate_then_take_over)
    websocket = RecordingWebSocket()
    event_id = source_id("100 元能卖吗")

    process(live, websocket, message="100 元能卖吗", event_id=event_id)

    dedupe_key = ReplyOutbox.build_dedupe_key("chat_1", "item_1", "buyer_1", event_id)
    snapshot = bot.db.get_memory_snapshot("chat_1")
    assert outbox.get(dedupe_key).last_error == "manual_takeover"
    assert [message["role"] for message in snapshot.messages] == ["user"]
    assert snapshot.bargain_count == 0
    assert snapshot.lowest_price_committed is None
    assert snapshot.buyer_highest_offer is None
    assert websocket.payloads == []


def test_takeover_after_outbox_enqueue_discards_unsent_price_commitment(tmp_path, monkeypatch):
    live, bot, outbox = build_live(tmp_path, dry_run=False)
    original_enqueue = outbox.enqueue

    def enqueue_then_take_over(*args, **kwargs):
        record = original_enqueue(*args, **kwargs)
        ManualTakeoverStore(live.manual_takeovers.path).enable("chat_1", ttl_seconds=600)
        return record

    monkeypatch.setattr(outbox, "enqueue", enqueue_then_take_over)
    event_id = source_id("3000 元能出吗")

    process(
        live,
        RecordingWebSocket(),
        message="3000 元能出吗",
        event_id=event_id,
    )

    dedupe_key = ReplyOutbox.build_dedupe_key("chat_1", "item_1", "buyer_1", event_id)
    snapshot = bot.db.get_memory_snapshot("chat_1")
    assert outbox.get(dedupe_key).last_error == "manual_takeover"
    assert snapshot.messages == [{"role": "user", "content": "3000 元能出吗"}]
    assert snapshot.bargain_count == 0
    assert snapshot.lowest_price_committed is None
    assert snapshot.buyer_highest_offer is None


def test_sent_terminal_upgrades_prior_manual_user_only_memory(tmp_path):
    live, bot, outbox = build_live(tmp_path, dry_run=False)
    event_id = source_id("3000 元能出吗")
    record = outbox.enqueue(
        "chat_1",
        "item_1",
        "buyer_1",
        event_id,
        "最低 4149 元",
        trace={"price_decision": {"calculated_price": 4149, "buyer_offer": 3000}},
        user_text="3000 元能出吗",
        intent="price",
    )
    outbox.claim_for_send(record.dedupe_key)
    skipped = outbox.mark_skipped(record.dedupe_key, "manual_takeover")
    live._commit_outbox_memory(skipped)

    sent = outbox.mark_sent(record.dedupe_key)
    live._commit_outbox_memory(sent)
    live._commit_outbox_memory(sent)

    snapshot = bot.db.get_memory_snapshot("chat_1")
    assert [message["role"] for message in snapshot.messages] == ["user", "assistant"]
    assert snapshot.bargain_count == 1
    assert snapshot.lowest_price_committed == 4149
    assert snapshot.buyer_highest_offer == 3000


def test_takeover_racing_with_inflight_network_send_upgrades_memory_if_send_wins(tmp_path):
    live, bot, outbox = build_live(tmp_path, dry_run=False)
    event_id = source_id("3000 元能出吗")

    async def scenario():
        send_started = asyncio.Event()
        allow_send_to_finish = asyncio.Event()

        class BlockingWebSocket(RecordingWebSocket):
            async def send(self, payload):
                send_started.set()
                await allow_send_to_finish.wait()
                self.payloads.append(json.loads(payload))

        websocket = BlockingWebSocket()
        sending = asyncio.create_task(live._process_buyer_message(
            websocket,
            "chat_1",
            "buyer_1",
            "item_1",
            "3000 元能出吗",
            source_message_id=event_id,
        ))
        await asyncio.wait_for(send_started.wait(), timeout=2)
        ManualTakeoverStore(live.manual_takeovers.path).enable("chat_1", ttl_seconds=600)
        await live._process_buyer_message(
            RecordingWebSocket(),
            "chat_1",
            "buyer_1",
            "item_1",
            "3000 元能出吗",
            source_message_id=event_id,
        )
        allow_send_to_finish.set()
        await asyncio.wait_for(sending, timeout=2)
        return websocket

    websocket = asyncio.run(scenario())

    dedupe_key = ReplyOutbox.build_dedupe_key("chat_1", "item_1", "buyer_1", event_id)
    snapshot = bot.db.get_memory_snapshot("chat_1")
    assert outbox.get(dedupe_key).status == "sent"
    assert len(websocket.payloads) == 1
    assert [message["role"] for message in snapshot.messages] == ["user", "assistant"]
    assert snapshot.bargain_count == 1
    assert snapshot.lowest_price_committed is not None
    assert snapshot.buyer_highest_offer == 3000


def test_live_rejects_split_memory_stores(tmp_path):
    bot = XianyuReplyBot(
        client=DeterministicLLMClient(),
        db_path=str(tmp_path / "bot_history.db"),
    )
    different_context = ChatContextManager(db_path=str(tmp_path / "live_history.db"))

    with pytest.raises(ValueError, match="share one ChatContextManager"):
        XianyuLive(
            "unb=test_seller",
            reply_bot=bot,
            context_manager=different_context,
            xianyu_api=FakeXianyuApi(),
            reply_outbox=ReplyOutbox(db_path=str(tmp_path / "reply_outbox.db")),
        )


def test_takeover_commands_are_comma_separated_exact_messages(tmp_path, monkeypatch):
    monkeypatch.setenv("TOGGLE_KEYWORDS", "。, 接管，转人工")
    live, _, _ = build_live(tmp_path, dry_run=True)

    assert live.check_toggle_keywords("。") is True
    assert live.check_toggle_keywords(" 接管 ") is True
    assert live.check_toggle_keywords("转人工") is True
    assert live.check_toggle_keywords("请转人工处理") is False
