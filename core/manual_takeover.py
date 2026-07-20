import math
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ManualTakeoverRecord:
    chat_id: str
    item_id: Optional[str]
    active: bool
    source: str
    note: Optional[str]
    started_at: Optional[float]
    expires_at: Optional[float]
    updated_at: float

    @staticmethod
    def _iso_timestamp(value: Optional[float]) -> Optional[str]:
        if value is None:
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()

    def to_dict(self, now: Optional[float] = None) -> Dict[str, Any]:
        current = time.time() if now is None else now
        return {
            "chat_id": self.chat_id,
            "item_id": self.item_id,
            "active": self.active,
            "source": self.source,
            "note": self.note,
            "started_at": self._iso_timestamp(self.started_at),
            "expires_at": self._iso_timestamp(self.expires_at),
            "updated_at": self._iso_timestamp(self.updated_at),
            "remaining_seconds": (
                max(0, int(self.expires_at - current))
                if self.active and self.expires_at is not None
                else 0
            ),
        }


class ManualTakeoverStore:
    """Cross-process source of truth for conversation-level human takeover."""

    def __init__(self, path: Optional[str] = None, default_ttl_seconds: Optional[float] = None):
        self.path = path or os.getenv("MANUAL_TAKEOVER_DB_PATH", "data/manual_takeovers.db")
        raw_ttl = (
            default_ttl_seconds
            if default_ttl_seconds is not None
            else os.getenv("MANUAL_MODE_TIMEOUT", "3600")
        )
        try:
            parsed_ttl = float(raw_ttl)
        except (TypeError, ValueError):
            parsed_ttl = 3600.0
        if not math.isfinite(parsed_ttl):
            parsed_ttl = 3600.0
        self.default_ttl_seconds = min(86400.0, max(60.0, parsed_ttl))
        try:
            self.busy_timeout_ms = max(1000, int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "30000")))
        except ValueError:
            self.busy_timeout_ms = 30000
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_takeovers (
                    chat_id TEXT PRIMARY KEY,
                    item_id TEXT,
                    active INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL,
                    note TEXT,
                    started_at REAL,
                    expires_at REAL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_takeover_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    item_id TEXT,
                    action TEXT NOT NULL,
                    source TEXT NOT NULL,
                    note TEXT,
                    expires_at REAL,
                    occurred_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_manual_takeovers_active "
                "ON manual_takeovers (active, updated_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_takeover_events_chat "
                "ON manual_takeover_events (chat_id, occurred_at DESC)"
            )

    @staticmethod
    def _clean_required(value: str, field: str, max_length: int) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} must not be blank")
        if len(normalized) > max_length:
            raise ValueError(f"{field} must not exceed {max_length} characters")
        return normalized

    @staticmethod
    def _clean_optional(value: Optional[str], max_length: int) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if len(normalized) > max_length:
            raise ValueError(f"value must not exceed {max_length} characters")
        return normalized

    def _normalize_ttl(self, ttl_seconds: Optional[float]) -> float:
        if ttl_seconds is None:
            return self.default_ttl_seconds
        try:
            parsed = float(ttl_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("ttl_seconds must be a finite number") from exc
        if not math.isfinite(parsed) or parsed < 60 or parsed > 86400:
            raise ValueError("ttl_seconds must be between 60 and 86400")
        return parsed

    @staticmethod
    def _row_to_record(row) -> Optional[ManualTakeoverRecord]:
        if row is None:
            return None
        return ManualTakeoverRecord(
            chat_id=row[0],
            item_id=row[1],
            active=bool(row[2]),
            source=row[3],
            note=row[4],
            started_at=row[5],
            expires_at=row[6],
            updated_at=row[7],
        )

    @staticmethod
    def _select_record(conn: sqlite3.Connection, chat_id: str):
        return conn.execute(
            """
            SELECT chat_id, item_id, active, source, note, started_at, expires_at, updated_at
            FROM manual_takeovers WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()

    def _expire_due(self, conn: sqlite3.Connection, now: float, chat_id: Optional[str] = None) -> int:
        params: List[Any] = [now]
        where = "active = 1 AND expires_at IS NOT NULL AND expires_at <= ?"
        if chat_id is not None:
            where += " AND chat_id = ?"
            params.append(chat_id)
        rows = conn.execute(
            f"SELECT chat_id, item_id, note, expires_at FROM manual_takeovers WHERE {where}",
            params,
        ).fetchall()
        for expired_chat_id, item_id, note, expires_at in rows:
            conn.execute(
                """
                UPDATE manual_takeovers
                SET active = 0, source = 'ttl_expiry', updated_at = ?
                WHERE chat_id = ? AND active = 1
                """,
                (now, expired_chat_id),
            )
            conn.execute(
                """
                INSERT INTO manual_takeover_events (
                    chat_id, item_id, action, source, note, expires_at, occurred_at
                ) VALUES (?, ?, 'expired', 'ttl_expiry', ?, ?, ?)
                """,
                (expired_chat_id, item_id, note, expires_at, now),
            )
        return len(rows)

    def enable(
        self,
        chat_id: str,
        item_id: Optional[str] = None,
        ttl_seconds: Optional[float] = None,
        source: str = "operator",
        note: Optional[str] = None,
    ) -> ManualTakeoverRecord:
        chat_id = self._clean_required(chat_id, "chat_id", 128)
        item_id = self._clean_optional(item_id, 128)
        source = self._clean_required(source, "source", 64)
        note = self._clean_optional(note, 500)
        now = time.time()
        expires_at = now + self._normalize_ttl(ttl_seconds)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_due(conn, now, chat_id)
            previous = self._row_to_record(self._select_record(conn, chat_id))
            action = "extended" if previous and previous.active else "enabled"
            conn.execute(
                """
                INSERT INTO manual_takeovers (
                    chat_id, item_id, active, source, note, started_at, expires_at, updated_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    item_id = excluded.item_id,
                    active = 1,
                    source = excluded.source,
                    note = excluded.note,
                    started_at = CASE
                        WHEN manual_takeovers.active = 1 THEN manual_takeovers.started_at
                        ELSE excluded.started_at
                    END,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (chat_id, item_id, source, note, now, expires_at, now),
            )
            conn.execute(
                """
                INSERT INTO manual_takeover_events (
                    chat_id, item_id, action, source, note, expires_at, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (chat_id, item_id, action, source, note, expires_at, now),
            )
            return self._row_to_record(self._select_record(conn, chat_id))

    def disable(
        self,
        chat_id: str,
        source: str = "operator",
        note: Optional[str] = None,
    ) -> ManualTakeoverRecord:
        chat_id = self._clean_required(chat_id, "chat_id", 128)
        source = self._clean_required(source, "source", 64)
        note = self._clean_optional(note, 500)
        now = time.time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_due(conn, now, chat_id)
            previous = self._row_to_record(self._select_record(conn, chat_id))
            item_id = previous.item_id if previous else None
            conn.execute(
                """
                INSERT INTO manual_takeovers (
                    chat_id, item_id, active, source, note, started_at, expires_at, updated_at
                ) VALUES (?, ?, 0, ?, ?, NULL, NULL, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    active = 0,
                    source = excluded.source,
                    note = excluded.note,
                    expires_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (chat_id, item_id, source, note, now),
            )
            conn.execute(
                """
                INSERT INTO manual_takeover_events (
                    chat_id, item_id, action, source, note, expires_at, occurred_at
                ) VALUES (?, ?, 'disabled', ?, ?, NULL, ?)
                """,
                (chat_id, item_id, source, note, now),
            )
            return self._row_to_record(self._select_record(conn, chat_id))

    def get(self, chat_id: str) -> Optional[ManualTakeoverRecord]:
        chat_id = self._clean_required(chat_id, "chat_id", 128)
        now = time.time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_due(conn, now, chat_id)
            return self._row_to_record(self._select_record(conn, chat_id))

    def is_active(self, chat_id: str) -> bool:
        chat_id = self._clean_required(chat_id, "chat_id", 128)
        now = time.time()
        # Worker hot paths must never wait for a cross-process write lock.
        # Expiry is decided from the timestamp here; API/list operations persist
        # the corresponding audit event lazily.
        with self._connection() as conn:
            record = self._row_to_record(self._select_record(conn, chat_id))
        return bool(
            record
            and record.active
            and (record.expires_at is None or record.expires_at > now)
        )

    def list(self, active_only: bool = True, limit: int = 100) -> List[ManualTakeoverRecord]:
        bounded_limit = max(1, min(int(limit), 200))
        now = time.time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_due(conn, now)
            where = "WHERE active = 1" if active_only else ""
            rows = conn.execute(
                f"""
                SELECT chat_id, item_id, active, source, note, started_at, expires_at, updated_at
                FROM manual_takeovers {where}
                ORDER BY active DESC, updated_at DESC LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        return [record for row in rows if (record := self._row_to_record(row)) is not None]

    def count(self, active_only: bool = True) -> int:
        now = time.time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_due(conn, now)
            where = "WHERE active = 1" if active_only else ""
            row = conn.execute(f"SELECT COUNT(*) FROM manual_takeovers {where}").fetchone()
        return int(row[0])

    def list_events(self, chat_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 200))
        params: List[Any] = []
        where = ""
        if chat_id is not None:
            chat_id = self._clean_required(chat_id, "chat_id", 128)
            where = "WHERE chat_id = ?"
            params.append(chat_id)
        params.append(bounded_limit)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_due(conn, time.time(), chat_id)
            rows = conn.execute(
                f"""
                SELECT id, chat_id, item_id, action, source, note, expires_at, occurred_at
                FROM manual_takeover_events {where}
                ORDER BY occurred_at DESC, id DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": row[0],
                "chat_id": row[1],
                "item_id": row[2],
                "action": row[3],
                "source": row[4],
                "note": row[5],
                "expires_at": ManualTakeoverRecord._iso_timestamp(row[6]),
                "occurred_at": ManualTakeoverRecord._iso_timestamp(row[7]),
            }
            for row in rows
        ]
