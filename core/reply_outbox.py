import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


TERMINAL_STATUSES = {"sent", "skipped"}


@dataclass
class ReplyOutboxRecord:
    id: int
    dedupe_key: str
    chat_id: str
    item_id: str
    user_id: str
    source_message_id: str
    reply_text: str
    status: str
    attempt_count: int
    user_text: str = ""
    intent: Optional[str] = None
    trace: Dict[str, Any] = field(default_factory=dict)
    last_error: Optional[str] = None
    updated_at: Optional[str] = None
    created: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReplySendClaim:
    claimed: bool
    record: ReplyOutboxRecord
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claimed": self.claimed,
            "reason": self.reason,
            "record": self.record.to_dict(),
        }


class ReplyOutbox:
    """
    Durable execution queue for Xianyu reply sending.

    The LLM decides what to say, but the outbox decides whether this exact source
    event is still allowed to be sent. This blocks concurrent duplicate sends
    and suppresses replayed terminal events. End-to-end exactly-once delivery
    still depends on idempotency or acknowledgements from the remote platform.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("REPLY_OUTBOX_DB_PATH", "data/reply_outbox.db")
        self._init_db()

    def _init_db(self) -> None:
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reply_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL UNIQUE,
                chat_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL,
                reply_text TEXT NOT NULL,
                trace_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                sent_at DATETIME
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reply_outbox_status ON reply_outbox (status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reply_outbox_chat ON reply_outbox (chat_id)")
        cursor.execute("PRAGMA table_info(reply_outbox)")
        columns = {row[1] for row in cursor.fetchall()}
        if "user_text" not in columns:
            cursor.execute("ALTER TABLE reply_outbox ADD COLUMN user_text TEXT NOT NULL DEFAULT ''")
        if "intent" not in columns:
            cursor.execute("ALTER TABLE reply_outbox ADD COLUMN intent TEXT")
        conn.commit()
        conn.close()

    @staticmethod
    def build_source_message_id(
        chat_id: str,
        item_id: str,
        user_id: str,
        message_text: str,
        event_time_ms: Optional[int] = None,
    ) -> str:
        normalized = " ".join((message_text or "").split())
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        timestamp = str(event_time_ms or "no-ts")
        return f"{chat_id}:{item_id}:{user_id}:{timestamp}:{digest}"

    @staticmethod
    def build_dedupe_key(chat_id: str, item_id: str, user_id: str, source_message_id: str) -> str:
        raw = f"{chat_id}|{item_id}|{user_id}|{source_message_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def enqueue(
        self,
        chat_id: str,
        item_id: str,
        user_id: str,
        source_message_id: str,
        reply_text: str,
        trace: Optional[Dict[str, Any]] = None,
        user_text: str = "",
        intent: Optional[str] = None,
    ) -> ReplyOutboxRecord:
        dedupe_key = self.build_dedupe_key(chat_id, item_id, user_id, source_message_id)
        trace_json = json.dumps(trace or {}, ensure_ascii=False)
        now = datetime.now().isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO reply_outbox (
                    dedupe_key, chat_id, item_id, user_id, source_message_id,
                    reply_text, trace_json, user_text, intent, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    dedupe_key,
                    chat_id,
                    item_id,
                    user_id,
                    source_message_id,
                    reply_text,
                    trace_json,
                    user_text,
                    intent,
                    now,
                    now,
                ),
            )
            created = cursor.rowcount == 1
            conn.commit()
            record = self._fetch_by_key(cursor, dedupe_key)
            if not created and record.status == "failed":
                cursor.execute(
                    """
                    UPDATE reply_outbox
                    SET reply_text = ?,
                        trace_json = ?,
                        user_text = ?,
                        intent = ?,
                        updated_at = ?
                    WHERE dedupe_key = ?
                    """,
                    (reply_text, trace_json, user_text, intent, datetime.now().isoformat(), dedupe_key),
                )
                conn.commit()
                record = self._fetch_by_key(cursor, dedupe_key)
            record.created = created
            return record
        finally:
            conn.close()

    def claim_for_send(self, dedupe_key: str, stale_after_seconds: int = 300) -> ReplySendClaim:
        now = datetime.now()
        stale_before = (now - timedelta(seconds=max(0, stale_after_seconds))).isoformat()
        conn = sqlite3.connect(self.db_path, timeout=30)
        cursor = conn.cursor()
        try:
            # Serialize the read-and-claim transition so concurrent workers cannot
            # both observe a pending record and send the same reply.
            cursor.execute("BEGIN IMMEDIATE")
            record = self._fetch_by_key(cursor, dedupe_key)
            if record.status in TERMINAL_STATUSES:
                conn.commit()
                return ReplySendClaim(False, record, f"already_{record.status}")
            if record.status == "sending" and (record.updated_at or "") > stale_before:
                conn.commit()
                return ReplySendClaim(False, record, "already_sending")

            if record.status not in {"pending", "failed", "sending"}:
                conn.commit()
                return ReplySendClaim(False, record, f"unsupported_status_{record.status}")

            cursor.execute(
                """
                UPDATE reply_outbox
                SET status = 'sending',
                    attempt_count = attempt_count + 1,
                    last_error = NULL,
                    updated_at = ?
                WHERE dedupe_key = ?
                  AND (
                    status IN ('pending', 'failed')
                    OR (status = 'sending' AND updated_at <= ?)
                  )
                """,
                (now.isoformat(), dedupe_key, stale_before),
            )
            if cursor.rowcount != 1:
                conn.commit()
                current = self._fetch_by_key(cursor, dedupe_key)
                return ReplySendClaim(False, current, f"already_{current.status}")
            conn.commit()
            reason = "reclaimed_stale_sending" if record.status == "sending" else "claimed"
            return ReplySendClaim(True, self._fetch_by_key(cursor, dedupe_key), reason)
        finally:
            conn.close()

    def mark_sent(self, dedupe_key: str) -> ReplyOutboxRecord:
        return self._mark(dedupe_key, "sent", sent=True, allowed_statuses={"sending", "skipped"})

    def mark_skipped(self, dedupe_key: str, reason: str) -> ReplyOutboxRecord:
        return self._mark(dedupe_key, "skipped", error=reason, allowed_statuses={"pending", "failed", "sending"})

    def mark_failed(self, dedupe_key: str, error: str) -> ReplyOutboxRecord:
        return self._mark(dedupe_key, "failed", error=error, allowed_statuses={"sending", "failed"})

    def _mark(
        self,
        dedupe_key: str,
        status: str,
        error: Optional[str] = None,
        sent: bool = False,
        allowed_statuses: Optional[set] = None,
    ) -> ReplyOutboxRecord:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            status_filter = ""
            params = [
                status,
                error,
                datetime.now().isoformat(),
                1 if sent else 0,
                datetime.now().isoformat(),
                dedupe_key,
            ]
            if allowed_statuses:
                placeholders = ", ".join("?" for _ in allowed_statuses)
                status_filter = f" AND status IN ({placeholders})"
                params.extend(sorted(allowed_statuses))
            cursor.execute(
                f"""
                UPDATE reply_outbox
                SET status = ?,
                    last_error = ?,
                    updated_at = ?,
                    sent_at = CASE WHEN ? THEN ? ELSE sent_at END
                WHERE dedupe_key = ?
                {status_filter}
                """,
                params,
            )
            conn.commit()
            return self._fetch_by_key(cursor, dedupe_key)
        finally:
            conn.close()

    def get(self, dedupe_key: str) -> Optional[ReplyOutboxRecord]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            return self._fetch_by_key(cursor, dedupe_key, required=False)
        finally:
            conn.close()

    def count_by_status(self, status: str) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM reply_outbox WHERE status = ?", (status,))
            return int(cursor.fetchone()[0])
        finally:
            conn.close()

    @staticmethod
    def _fetch_by_key(cursor, dedupe_key: str, required: bool = True) -> Optional[ReplyOutboxRecord]:
        cursor.execute(
            """
            SELECT id, dedupe_key, chat_id, item_id, user_id, source_message_id,
                   reply_text, user_text, intent, trace_json, status, attempt_count,
                   last_error, updated_at
            FROM reply_outbox
            WHERE dedupe_key = ?
            """,
            (dedupe_key,),
        )
        row = cursor.fetchone()
        if not row:
            if required:
                raise KeyError(f"reply outbox record not found: {dedupe_key}")
            return None
        trace = {}
        try:
            trace = json.loads(row[9] or "{}")
        except (TypeError, json.JSONDecodeError):
            pass
        return ReplyOutboxRecord(
            id=row[0],
            dedupe_key=row[1],
            chat_id=row[2],
            item_id=row[3],
            user_id=row[4],
            source_message_id=row[5],
            reply_text=row[6],
            user_text=row[7] or "",
            intent=row[8],
            trace=trace,
            status=row[10],
            attempt_count=row[11],
            last_error=row[12],
            updated_at=row[13],
        )
