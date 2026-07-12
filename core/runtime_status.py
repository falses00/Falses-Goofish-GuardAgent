import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


ALLOWED_STATUS_FIELDS = {
    "dry_run",
    "last_error_type",
    "last_heartbeat_response_at",
    "last_heartbeat_sent_at",
    "last_registered_at",
    "last_token_refresh_at",
    "next_retry_seconds",
    "reconnect_attempt",
}
PERSISTED_STATUS_FIELDS = ALLOWED_STATUS_FIELDS | {"pid", "state", "updated_at"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NullRuntimeStatusStore:
    def update(self, state: Optional[str] = None, **fields: Any) -> Dict[str, Any]:
        return {}


class RuntimeStatusStore:
    """Atomic, secret-free status snapshot for the live Xianyu worker."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.getenv("RUNTIME_STATUS_PATH", "logs/runtime_status.json"))

    def read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {key: value for key, value in data.items() if key in PERSISTED_STATUS_FIELDS}

    def update(self, state: Optional[str] = None, **fields: Any) -> Dict[str, Any]:
        unknown = set(fields) - ALLOWED_STATUS_FIELDS
        if unknown:
            raise ValueError(f"unsupported runtime status fields: {sorted(unknown)}")

        payload = self.read()
        if state is not None:
            payload["state"] = state
        payload.update(fields)
        payload["pid"] = os.getpid()
        payload["updated_at"] = utc_now_iso()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, self.path)
        return payload


def build_runtime_status_report(
    path: Optional[str] = None,
    stale_after_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    store = RuntimeStatusStore(path)
    snapshot = store.read()
    stale_after_value = (
        stale_after_seconds
        if stale_after_seconds is not None
        else os.getenv("RUNTIME_STATUS_STALE_SECONDS", "45")
    )
    try:
        stale_after = float(stale_after_value)
    except (TypeError, ValueError):
        return {
            "healthy": False,
            "reason": "invalid_stale_after_seconds",
            "age_seconds": None,
            "status": snapshot,
        }
    if not snapshot:
        return {
            "healthy": False,
            "reason": "status_missing",
            "age_seconds": None,
            "status": {},
        }

    updated_at = snapshot.get("updated_at")
    try:
        updated_timestamp = datetime.fromisoformat(updated_at).timestamp()
        age_seconds = max(0.0, time.time() - updated_timestamp)
    except (TypeError, ValueError):
        age_seconds = None

    stale = age_seconds is None or age_seconds > max(1.0, stale_after)
    healthy = snapshot.get("state") == "registered" and not stale
    reason = "ok" if healthy else "status_stale" if stale else f"state_{snapshot.get('state', 'unknown')}"
    return {
        "healthy": healthy,
        "reason": reason,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "status": snapshot,
    }
