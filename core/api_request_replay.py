import json
import math
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class RequestReplayConflict(ValueError):
    pass


class RequestReplayLeaseLost(RuntimeError):
    pass


@dataclass(frozen=True)
class RequestReplayClaim:
    execute: bool
    reason: str
    response: Optional[Dict[str, Any]] = None
    claim_token: Optional[str] = None


class RequestReplayLease:
    """Renews one owned replay claim while a slow Agent decision is running."""

    def __init__(
        self,
        store: "ApiRequestReplayStore",
        request_id: str,
        request_hash: str,
        claim_token: str,
    ):
        self.store = store
        self.request_id = request_id
        self.request_hash = request_hash
        self.claim_token = claim_token
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._interval = max(0.1, min(5.0, store.lease_seconds / 3.0))
        self._thread = threading.Thread(
            target=self._renew_loop,
            name=f"request-replay-lease-{request_id[:24]}",
            daemon=True,
        )

    def __enter__(self) -> "RequestReplayLease":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._interval * 2))

    def _renew_loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                renewed = self.store.renew(
                    self.request_id,
                    self.request_hash,
                    self.claim_token,
                )
            except sqlite3.Error:
                renewed = False
            if not renewed:
                self._lost.set()
                return

    def assert_held(self) -> None:
        if self._lost.is_set() or not self.store.is_claim_current(
            self.request_id,
            self.request_hash,
            self.claim_token,
        ):
            raise RequestReplayLeaseLost("request replay lease ownership was lost")


class ApiRequestReplayStore:
    """Durable request replay records for completed API decisions."""

    def __init__(self, path: Optional[str] = None, lease_seconds: Optional[float] = None):
        self.path = path or os.getenv("API_REQUEST_REPLAY_DB_PATH", "data/api_request_replay.db")
        raw_lease = (
            lease_seconds
            if lease_seconds is not None
            else os.getenv("API_REQUEST_REPLAY_LEASE_SECONDS", "60")
        )
        try:
            parsed_lease = float(raw_lease)
        except (TypeError, ValueError):
            parsed_lease = 60.0
        if not math.isfinite(parsed_lease):
            parsed_lease = 60.0
        self.lease_seconds = max(1.0, parsed_lease)
        try:
            self.busy_timeout_ms = max(
                1000,
                int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "30000")),
            )
        except ValueError:
            self.busy_timeout_ms = 30000
        self._init_db()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _connect(self):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_request_replays (
                    request_id TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claim_token TEXT,
                    response_json TEXT,
                    last_error TEXT,
                    lease_expires_at REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_request_replays_status "
                "ON api_request_replays (status)"
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(api_request_replays)").fetchall()
            }
            if "claim_token" not in columns:
                conn.execute("ALTER TABLE api_request_replays ADD COLUMN claim_token TEXT")

    def claim(self, request_id: str, request_hash: str) -> RequestReplayClaim:
        now = time.time()
        now_iso = self._utc_now()
        lease_expires_at = now + self.lease_seconds
        claim_token = uuid.uuid4().hex
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT request_hash, status, response_json, lease_expires_at
                FROM api_request_replays
                WHERE request_id = ?
                """,
                (request_id,),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    INSERT INTO api_request_replays (
                        request_id, request_hash, status, claim_token, response_json,
                        last_error, lease_expires_at, created_at, updated_at
                    ) VALUES (?, ?, 'processing', ?, NULL, NULL, ?, ?, ?)
                    """,
                    (
                        request_id,
                        request_hash,
                        claim_token,
                        lease_expires_at,
                        now_iso,
                        now_iso,
                    ),
                )
                conn.commit()
                return RequestReplayClaim(True, "claimed", claim_token=claim_token)

            stored_hash, status, response_json, stored_lease = row
            if stored_hash != request_hash:
                conn.commit()
                raise RequestReplayConflict("request_id_payload_mismatch")

            if status == "completed" and response_json:
                conn.commit()
                return RequestReplayClaim(False, "completed", json.loads(response_json))

            if status == "processing" and (stored_lease or 0) > now:
                conn.commit()
                return RequestReplayClaim(False, "in_progress")

            cursor.execute(
                """
                UPDATE api_request_replays
                SET status = 'processing', response_json = NULL, last_error = NULL,
                    claim_token = ?, lease_expires_at = ?, updated_at = ?
                WHERE request_id = ? AND request_hash = ?
                """,
                (claim_token, lease_expires_at, now_iso, request_id, request_hash),
            )
            conn.commit()
            return RequestReplayClaim(True, "reclaimed", claim_token=claim_token)
        finally:
            conn.close()

    def maintain_claim(
        self,
        request_id: str,
        request_hash: str,
        claim_token: str,
    ) -> RequestReplayLease:
        return RequestReplayLease(self, request_id, request_hash, claim_token)

    def renew(self, request_id: str, request_hash: str, claim_token: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE api_request_replays
                SET lease_expires_at = ?, updated_at = ?
                WHERE request_id = ? AND request_hash = ?
                  AND claim_token = ? AND status = 'processing'
                """,
                (
                    time.time() + self.lease_seconds,
                    self._utc_now(),
                    request_id,
                    request_hash,
                    claim_token,
                ),
            )
            return cursor.rowcount == 1

    def is_claim_current(self, request_id: str, request_hash: str, claim_token: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT status, lease_expires_at
                FROM api_request_replays
                WHERE request_id = ? AND request_hash = ? AND claim_token = ?
                """,
                (request_id, request_hash, claim_token),
            ).fetchone()
        return bool(row and row[0] == "processing" and (row[1] or 0) > time.time())

    def complete(
        self,
        request_id: str,
        request_hash: str,
        claim_token: str,
        response: Dict[str, Any],
    ) -> None:
        response_json = json.dumps(response, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE api_request_replays
                SET status = 'completed', response_json = ?, last_error = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE request_id = ? AND request_hash = ?
                  AND claim_token = ? AND status = 'processing'
                """,
                (
                    response_json,
                    self._utc_now(),
                    request_id,
                    request_hash,
                    claim_token,
                ),
            )
            if cursor.rowcount != 1:
                raise RequestReplayLeaseLost("request replay claim was lost before completion")

    def fail(
        self,
        request_id: str,
        request_hash: str,
        claim_token: str,
        error: str,
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE api_request_replays
                SET status = 'failed', last_error = ?, lease_expires_at = NULL,
                    updated_at = ?
                WHERE request_id = ? AND request_hash = ?
                  AND claim_token = ? AND status = 'processing'
                """,
                (
                    error[:500],
                    self._utc_now(),
                    request_id,
                    request_hash,
                    claim_token,
                ),
            )
            return cursor.rowcount == 1
