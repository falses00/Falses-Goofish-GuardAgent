import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from core.reply_outbox import ReplyOutboxRecord


@dataclass
class ChatEvent:
    id: int
    event_key: str
    chat_id: str
    item_id: str
    user_id: str
    sender_name: str
    role: str
    direction: str
    content: str
    status: str
    source_message_id: Optional[str] = None
    outbox_dedupe_key: Optional[str] = None
    intent: Optional[str] = None
    platform_created_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ChatEventStore:
    """Cross-process message fact stream for the seller operations inbox."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.getenv("CHAT_EVENT_DB_PATH", "data/chat_events.db")
        try:
            self.busy_timeout_ms = max(1000, int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "30000")))
        except ValueError:
            self.busy_timeout_ms = 30000
        try:
            self.semantic_dedupe_seconds = min(
                30.0,
                max(0.0, float(os.getenv("PLATFORM_REPLAY_DEDUPE_SECONDS", "3"))),
            )
        except ValueError:
            self.semantic_dedupe_seconds = 3.0
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    chat_id TEXT NOT NULL,
                    item_id TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    sender_name TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL CHECK(role IN ('buyer', 'seller', 'assistant', 'system')),
                    direction TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound', 'internal')),
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_message_id TEXT,
                    outbox_dedupe_key TEXT,
                    intent TEXT,
                    platform_created_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_events_chat ON chat_events (chat_id, id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_events_updated ON chat_events (updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_events_status ON chat_events (status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_events_semantic "
                "ON chat_events (chat_id, role, updated_at DESC)"
            )

    def record_inbound(
        self,
        chat_id: str,
        item_id: str,
        user_id: str,
        sender_name: str,
        content: str,
        source_message_id: str,
        event_time_ms: Optional[int] = None,
    ) -> ChatEvent:
        event, _ = self.record_inbound_once(
            chat_id,
            item_id,
            user_id,
            sender_name,
            content,
            source_message_id,
            event_time_ms,
        )
        return event

    def record_inbound_once(
        self,
        chat_id: str,
        item_id: str,
        user_id: str,
        sender_name: str,
        content: str,
        source_message_id: str,
        event_time_ms: Optional[int] = None,
    ) -> tuple[ChatEvent, bool]:
        replayed = self._recent_semantic_fact(
            chat_id,
            item_id,
            user_id,
            "buyer",
            content,
            source_message_id,
        )
        if replayed:
            return replayed, False
        platform_time = (
            datetime.fromtimestamp(event_time_ms / 1000).astimezone().isoformat()
            if event_time_ms
            else None
        )
        return self._persist(
            event_key=f"in:{source_message_id}",
            chat_id=chat_id,
            item_id=item_id,
            user_id=user_id,
            sender_name=sender_name,
            role="buyer",
            direction="inbound",
            content=content,
            status="received",
            source_message_id=source_message_id,
            platform_created_at=platform_time,
            update_existing=False,
        )

    def record_seller(
        self,
        chat_id: str,
        item_id: str,
        seller_id: str,
        content: str,
        source_message_id: str,
        event_time_ms: Optional[int] = None,
    ) -> ChatEvent:
        event, _ = self.record_seller_once(
            chat_id,
            item_id,
            seller_id,
            content,
            source_message_id,
            event_time_ms,
        )
        return event

    def record_seller_once(
        self,
        chat_id: str,
        item_id: str,
        seller_id: str,
        content: str,
        source_message_id: str,
        event_time_ms: Optional[int] = None,
    ) -> tuple[ChatEvent, bool]:
        replayed = self._recent_semantic_fact(
            chat_id,
            item_id,
            seller_id,
            "seller",
            content,
            source_message_id,
        )
        if replayed:
            return replayed, False
        platform_time = (
            datetime.fromtimestamp(event_time_ms / 1000).astimezone().isoformat()
            if event_time_ms
            else None
        )
        return self._persist(
            event_key=f"seller:{source_message_id}",
            chat_id=chat_id,
            item_id=item_id,
            user_id=seller_id,
            sender_name="卖家",
            role="seller",
            direction="outbound",
            content=content,
            status="sent",
            source_message_id=source_message_id,
            platform_created_at=platform_time,
            update_existing=False,
        )

    def sync_outbox(self, record: ReplyOutboxRecord) -> Optional[ChatEvent]:
        status = self._outbox_status(record)
        silent_reply = not record.reply_text or record.reply_text == "-"
        if silent_reply and status not in {"no_reply", "cancelled_takeover"}:
            return None
        content = record.reply_text
        role = "assistant"
        direction = "outbound"
        sender_name = "GuardAgent"
        if silent_reply:
            role = "system"
            direction = "internal"
            sender_name = "系统"
            content = (
                "自动回复已由人工接管取消"
                if status == "cancelled_takeover"
                else "Agent 判定本轮无需回复"
            )
        event, _ = self._persist(
            event_key=f"out:{record.dedupe_key}",
            chat_id=record.chat_id,
            item_id=record.item_id,
            user_id=record.user_id,
            sender_name=sender_name,
            role=role,
            direction=direction,
            content=content,
            status=status,
            source_message_id=record.source_message_id,
            outbox_dedupe_key=record.dedupe_key,
            intent=record.intent,
            platform_created_at=record.sent_at,
            created_at=record.created_at,
            metadata={
                "trace": record.trace,
                "attempt_count": record.attempt_count,
                "delivery_reason": record.last_error,
            },
        )
        return event

    def link_inbound_to_outbox(self, source_message_ids: list[str], dedupe_key: str) -> int:
        """Mark raw platform facts as durably handled by one Outbox record."""
        normalized_ids = list(dict.fromkeys(str(value or "").strip() for value in source_message_ids))
        event_keys = [f"in:{value}" for value in normalized_ids if value]
        if not event_keys:
            return 0
        placeholders = ", ".join("?" for _ in event_keys)
        with self._connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE chat_events
                SET status = 'processed', outbox_dedupe_key = ?
                WHERE event_key IN ({placeholders}) AND role = 'buyer'
                """,
                [dedupe_key, *event_keys],
            )
            return int(cursor.rowcount)

    def linked_outbox_key(self, source_message_ids: list[str]) -> Optional[str]:
        """Return the shared Outbox key only when every raw message is linked."""
        normalized_ids = list(dict.fromkeys(str(value or "").strip() for value in source_message_ids))
        event_keys = [f"in:{value}" for value in normalized_ids if value]
        if not event_keys:
            return None
        placeholders = ", ".join("?" for _ in event_keys)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT event_key, outbox_dedupe_key
                FROM chat_events
                WHERE event_key IN ({placeholders}) AND role = 'buyer'
                """,
                event_keys,
            ).fetchall()
        if len(rows) != len(event_keys):
            return None
        linked_keys = {row[1] for row in rows if row[1]}
        if len(linked_keys) != 1 or any(not row[1] for row in rows):
            return None
        return linked_keys.pop()

    def change_token(self) -> str:
        """Cheap change detector for realtime subscribers."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(MAX(updated_at), '') FROM chat_events"
            ).fetchone()
        return f"{row[0]}:{row[1]}:{row[2]}"

    def _recent_semantic_fact(
        self,
        chat_id: str,
        item_id: str,
        user_id: str,
        role: str,
        content: str,
        source_message_id: str,
    ) -> Optional[ChatEvent]:
        if self.semantic_dedupe_seconds <= 0:
            return None
        cutoff = (datetime.now().astimezone() - timedelta(seconds=self.semantic_dedupe_seconds)).isoformat()
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, event_key, chat_id, item_id, user_id, sender_name,
                       role, direction, content, status, source_message_id,
                       outbox_dedupe_key, intent, platform_created_at,
                       created_at, updated_at, metadata_json
                FROM chat_events
                WHERE chat_id = ? AND item_id = ? AND user_id = ? AND role = ?
                  AND content = ? AND source_message_id <> ? AND updated_at >= ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (
                    chat_id,
                    item_id or "",
                    user_id or "",
                    role,
                    content,
                    source_message_id,
                    cutoff,
                ),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_recent(self, limit: int = 1000, chat_id: Optional[str] = None) -> list[ChatEvent]:
        safe_limit = min(5000, max(1, int(limit)))
        with self._connection() as conn:
            where = "WHERE chat_id = ?" if chat_id else ""
            params = [chat_id, safe_limit] if chat_id else [safe_limit]
            order_by = "id DESC" if chat_id else "updated_at DESC, id DESC"
            rows = conn.execute(
                f"""
                SELECT id, event_key, chat_id, item_id, user_id, sender_name,
                       role, direction, content, status, source_message_id,
                       outbox_dedupe_key, intent, platform_created_at,
                       created_at, updated_at, metadata_json
                FROM chat_events
                {where}
                ORDER BY {order_by}
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def search_conversations(
        self,
        query: str,
        max_chats: int = 200,
        per_chat: int = 200,
    ) -> list[ChatEvent]:
        """Search the full fact history, then load a bounded window per matching chat."""
        normalized = " ".join(str(query or "").lower().split())
        if not normalized:
            return []
        safe_chats = min(200, max(1, int(max_chats)))
        safe_per_chat = min(500, max(1, int(per_chat)))
        with self._connection() as conn:
            chat_rows = conn.execute(
                """
                SELECT chat_id, MAX(id) AS latest_id
                FROM chat_events
                WHERE instr(lower(chat_id), ?) > 0
                   OR instr(lower(item_id), ?) > 0
                   OR instr(lower(user_id), ?) > 0
                   OR instr(lower(sender_name), ?) > 0
                   OR instr(lower(content), ?) > 0
                   OR instr(lower(COALESCE(intent, '')), ?) > 0
                   OR instr(lower(metadata_json), ?) > 0
                GROUP BY chat_id
                ORDER BY latest_id DESC
                LIMIT ?
                """,
                [normalized] * 7 + [safe_chats],
            ).fetchall()
            chat_ids = [row[0] for row in chat_rows]
            if not chat_ids:
                return []
            placeholders = ", ".join("?" for _ in chat_ids)
            rows = conn.execute(
                f"""
                WITH ranked AS (
                    SELECT id, event_key, chat_id, item_id, user_id, sender_name,
                           role, direction, content, status, source_message_id,
                           outbox_dedupe_key, intent, platform_created_at,
                           created_at, updated_at, metadata_json,
                           ROW_NUMBER() OVER (PARTITION BY chat_id ORDER BY id DESC) AS row_number
                    FROM chat_events
                    WHERE chat_id IN ({placeholders})
                )
                SELECT id, event_key, chat_id, item_id, user_id, sender_name,
                       role, direction, content, status, source_message_id,
                       outbox_dedupe_key, intent, platform_created_at,
                       created_at, updated_at, metadata_json
                FROM ranked
                WHERE row_number <= ?
                ORDER BY id DESC
                """,
                [*chat_ids, safe_per_chat],
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def _persist(
        self,
        *,
        event_key: str,
        chat_id: str,
        item_id: str,
        user_id: str,
        sender_name: str,
        role: str,
        direction: str,
        content: str,
        status: str,
        source_message_id: Optional[str] = None,
        outbox_dedupe_key: Optional[str] = None,
        intent: Optional[str] = None,
        platform_created_at: Optional[str] = None,
        created_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        update_existing: bool = True,
    ) -> tuple[ChatEvent, bool]:
        now = datetime.now().astimezone().isoformat()
        created = created_at or platform_created_at or now
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        conflict_clause = (
            """
                ON CONFLICT(event_key) DO UPDATE SET
                    content = excluded.content,
                    status = excluded.status,
                    outbox_dedupe_key = COALESCE(excluded.outbox_dedupe_key, chat_events.outbox_dedupe_key),
                    intent = COALESCE(excluded.intent, chat_events.intent),
                    platform_created_at = COALESCE(excluded.platform_created_at, chat_events.platform_created_at),
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
            """
            if update_existing
            else "ON CONFLICT(event_key) DO NOTHING"
        )
        with self._connection() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO chat_events (
                    event_key, chat_id, item_id, user_id, sender_name, role,
                    direction, content, status, source_message_id,
                    outbox_dedupe_key, intent, platform_created_at,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                {conflict_clause}
                """,
                (
                    event_key,
                    chat_id,
                    item_id or "",
                    user_id or "",
                    sender_name or "",
                    role,
                    direction,
                    content,
                    status,
                    source_message_id,
                    outbox_dedupe_key,
                    intent,
                    platform_created_at,
                    metadata_json,
                    created,
                    now,
                ),
            )
            created_event = cursor.rowcount == 1 if not update_existing else False
            row = conn.execute(
                """
                SELECT id, event_key, chat_id, item_id, user_id, sender_name,
                       role, direction, content, status, source_message_id,
                       outbox_dedupe_key, intent, platform_created_at,
                       created_at, updated_at, metadata_json
                FROM chat_events WHERE event_key = ?
                """,
                (event_key,),
            ).fetchone()
        return self._from_row(row), created_event

    @staticmethod
    def _outbox_status(record: ReplyOutboxRecord) -> str:
        if record.status in {"pending", "sending", "sent", "failed"}:
            return record.status
        if record.last_error == "dry_run":
            return "simulated"
        if record.last_error == "manual_takeover":
            return "cancelled_takeover"
        if record.last_error == "no_reply":
            return "no_reply"
        return "skipped"

    @staticmethod
    def _from_row(row) -> ChatEvent:
        try:
            metadata = json.loads(row[16] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return ChatEvent(
            id=row[0],
            event_key=row[1],
            chat_id=row[2],
            item_id=row[3],
            user_id=row[4],
            sender_name=row[5],
            role=row[6],
            direction=row[7],
            content=row[8],
            status=row[9],
            source_message_id=row[10],
            outbox_dedupe_key=row[11],
            intent=row[12],
            platform_created_at=row[13],
            created_at=row[14],
            updated_at=row[15],
            metadata=metadata,
        )
