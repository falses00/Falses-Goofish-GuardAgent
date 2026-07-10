import asyncio
import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from XianyuAgent import XianyuReplyBot
from context_manager import ChatContextManager
from core.evaluation import DeterministicLLMClient
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
    live = XianyuLive(
        "unb=test_seller",
        reply_bot=bot,
        context_manager=bot.db,
        xianyu_api=FakeXianyuApi(),
        reply_outbox=outbox,
        reply_send_dry_run=dry_run,
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
    assert len(first_snapshot.messages) == 2
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
