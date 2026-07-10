import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.reply_outbox import ReplyOutbox


def test_reply_outbox_deduplicates_same_source_message(tmp_path):
    outbox = ReplyOutbox(db_path=str(tmp_path / "reply_outbox.db"))
    source_id = ReplyOutbox.build_source_message_id(
        "chat_1",
        "item_1",
        "buyer_1",
        "在吗",
        event_time_ms=123456,
    )

    first = outbox.enqueue("chat_1", "item_1", "buyer_1", source_id, "在的")
    second = outbox.enqueue("chat_1", "item_1", "buyer_1", source_id, "在的")

    assert first.created is True
    assert second.created is False
    assert first.dedupe_key == second.dedupe_key
    assert outbox.count_by_status("pending") == 1


def test_reply_outbox_claim_blocks_duplicate_sends(tmp_path):
    outbox = ReplyOutbox(db_path=str(tmp_path / "reply_outbox.db"))
    source_id = ReplyOutbox.build_source_message_id(
        "chat_1",
        "item_1",
        "buyer_1",
        "这个还在吗",
        event_time_ms=123456,
    )
    record = outbox.enqueue("chat_1", "item_1", "buyer_1", source_id, "在的，可以拍")

    first_claim = outbox.claim_for_send(record.dedupe_key)
    second_claim = outbox.claim_for_send(record.dedupe_key)

    assert first_claim.claimed is True
    assert first_claim.record.attempt_count == 1
    assert second_claim.claimed is False
    assert second_claim.reason == "already_sending"

    outbox.mark_sent(record.dedupe_key)
    third_claim = outbox.claim_for_send(record.dedupe_key)

    assert third_claim.claimed is False
    assert third_claim.reason == "already_sent"


def test_reply_outbox_allows_retry_after_send_failure(tmp_path):
    outbox = ReplyOutbox(db_path=str(tmp_path / "reply_outbox.db"))
    source_id = ReplyOutbox.build_source_message_id(
        "chat_1",
        "item_1",
        "buyer_1",
        "能便宜点吗",
        event_time_ms=123456,
    )
    record = outbox.enqueue("chat_1", "item_1", "buyer_1", source_id, "最低 99")

    first_claim = outbox.claim_for_send(record.dedupe_key)
    outbox.mark_failed(record.dedupe_key, "websocket closed")
    retry_claim = outbox.claim_for_send(record.dedupe_key)

    assert first_claim.claimed is True
    assert retry_claim.claimed is True
    assert retry_claim.record.attempt_count == 2


def test_reply_outbox_refreshes_failed_record_before_retry(tmp_path):
    outbox = ReplyOutbox(db_path=str(tmp_path / "reply_outbox.db"))
    source_id = ReplyOutbox.build_source_message_id(
        "chat_1",
        "item_1",
        "buyer_1",
        "还在吗",
        event_time_ms=123456,
    )
    record = outbox.enqueue("chat_1", "item_1", "buyer_1", source_id, "旧回复")

    outbox.claim_for_send(record.dedupe_key)
    outbox.mark_failed(record.dedupe_key, "websocket closed")
    refreshed = outbox.enqueue("chat_1", "item_1", "buyer_1", source_id, "新回复")

    assert refreshed.created is False
    assert refreshed.status == "failed"
    assert refreshed.reply_text == "新回复"


def test_reply_outbox_allows_only_one_concurrent_claim(tmp_path):
    outbox = ReplyOutbox(db_path=str(tmp_path / "reply_outbox.db"))
    source_id = ReplyOutbox.build_source_message_id(
        "chat_1",
        "item_1",
        "buyer_1",
        "还在吗",
        event_time_ms=123456,
    )
    record = outbox.enqueue("chat_1", "item_1", "buyer_1", source_id, "在的")

    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(lambda _: outbox.claim_for_send(record.dedupe_key), range(8)))

    assert sum(claim.claimed for claim in claims) == 1
    assert outbox.get(record.dedupe_key).attempt_count == 1


def test_reply_outbox_reclaims_stale_sending_lease(tmp_path):
    outbox = ReplyOutbox(db_path=str(tmp_path / "reply_outbox.db"))
    source_id = ReplyOutbox.build_source_message_id(
        "chat_1",
        "item_1",
        "buyer_1",
        "发一下",
        event_time_ms=123456,
    )
    record = outbox.enqueue("chat_1", "item_1", "buyer_1", source_id, "马上发")
    first_claim = outbox.claim_for_send(record.dedupe_key)

    conn = sqlite3.connect(outbox.db_path)
    conn.execute(
        "UPDATE reply_outbox SET updated_at = ? WHERE dedupe_key = ?",
        ("2000-01-01T00:00:00", record.dedupe_key),
    )
    conn.commit()
    conn.close()

    recovered = outbox.claim_for_send(record.dedupe_key, stale_after_seconds=300)

    assert first_claim.claimed is True
    assert recovered.claimed is True
    assert recovered.reason == "reclaimed_stale_sending"
    assert recovered.record.attempt_count == 2
