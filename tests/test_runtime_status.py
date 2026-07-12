import json
from datetime import datetime, timezone

import pytest

from core.runtime_status import RuntimeStatusStore, build_runtime_status_report


def test_runtime_status_is_atomic_merge_and_secret_free(tmp_path):
    path = tmp_path / "runtime_status.json"
    store = RuntimeStatusStore(str(path))

    first = store.update("connecting", dry_run=True, reconnect_attempt=1)
    second = store.update("registered", last_error_type=None, reconnect_attempt=0)

    assert first["state"] == "connecting"
    assert second["state"] == "registered"
    assert second["dry_run"] is True
    assert json.loads(path.read_text(encoding="utf-8")) == second
    assert not list(tmp_path.glob("*.tmp"))

    with pytest.raises(ValueError, match="unsupported runtime status fields"):
        store.update(api_key="must-not-be-written")


def test_runtime_status_drops_tainted_fields_from_old_snapshot(tmp_path):
    path = tmp_path / "runtime_status.json"
    path.write_text(
        json.dumps(
            {
                "state": "registered",
                "dry_run": True,
                "api_key": "old-secret",
                "cookie": "old-cookie",
                "message": "buyer-private-message",
            }
        ),
        encoding="utf-8",
    )
    store = RuntimeStatusStore(str(path))

    assert store.read() == {"state": "registered", "dry_run": True}
    assert build_runtime_status_report(str(path))["status"] == {
        "state": "registered",
        "dry_run": True,
    }

    updated = store.update("registered", reconnect_attempt=0)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert updated == persisted
    assert not {"api_key", "cookie", "message"} & persisted.keys()


def test_runtime_status_report_detects_healthy_and_stale_snapshots(tmp_path):
    path = tmp_path / "runtime_status.json"
    store = RuntimeStatusStore(str(path))
    store.update("registered", last_heartbeat_response_at="now")

    healthy = build_runtime_status_report(str(path), stale_after_seconds=30)
    stale_snapshot = store.read()
    stale_snapshot["updated_at"] = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
    path.write_text(json.dumps(stale_snapshot), encoding="utf-8")
    stale = build_runtime_status_report(str(path), stale_after_seconds=30)

    assert healthy["healthy"] is True
    assert healthy["reason"] == "ok"
    assert stale["healthy"] is False
    assert stale["reason"] == "status_stale"


def test_runtime_status_report_handles_missing_or_corrupt_files(tmp_path):
    path = tmp_path / "runtime_status.json"
    assert build_runtime_status_report(str(path))["reason"] == "status_missing"

    path.write_text("not-json", encoding="utf-8")
    assert build_runtime_status_report(str(path))["reason"] == "status_missing"


def test_runtime_status_report_handles_invalid_stale_configuration(tmp_path, monkeypatch):
    path = tmp_path / "runtime_status.json"
    RuntimeStatusStore(str(path)).update("registered")
    monkeypatch.setenv("RUNTIME_STATUS_STALE_SECONDS", "not-a-number")

    report = build_runtime_status_report(str(path))

    assert report["healthy"] is False
    assert report["reason"] == "invalid_stale_after_seconds"
