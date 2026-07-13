import sqlite3

import pytest

from core.api_request_replay import (
    ApiRequestReplayStore,
    RequestReplayConflict,
    RequestReplayLeaseLost,
)


def test_completed_request_is_replayed(tmp_path):
    store = ApiRequestReplayStore(str(tmp_path / "replays.db"))

    first = store.claim("request-1", "hash-1")
    store.complete("request-1", "hash-1", first.claim_token, {"reply": "ok"})
    replay = store.claim("request-1", "hash-1")

    assert first.execute is True
    assert first.reason == "claimed"
    assert replay.execute is False
    assert replay.reason == "completed"
    assert replay.response == {"reply": "ok"}


def test_same_request_id_with_different_hash_is_rejected(tmp_path):
    store = ApiRequestReplayStore(str(tmp_path / "replays.db"))
    store.claim("request-1", "hash-1")

    with pytest.raises(RequestReplayConflict, match="request_id_payload_mismatch"):
        store.claim("request-1", "hash-2")


def test_processing_request_is_blocked_until_lease_expires(tmp_path):
    path = tmp_path / "replays.db"
    store = ApiRequestReplayStore(str(path), lease_seconds=30)
    store.claim("request-1", "hash-1")

    in_progress = store.claim("request-1", "hash-1")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE api_request_replays SET lease_expires_at = 0 WHERE request_id = ?",
            ("request-1",),
        )
    reclaimed = store.claim("request-1", "hash-1")

    assert in_progress.execute is False
    assert in_progress.reason == "in_progress"
    assert reclaimed.execute is True
    assert reclaimed.reason == "reclaimed"


def test_failed_request_can_be_reclaimed(tmp_path):
    store = ApiRequestReplayStore(str(tmp_path / "replays.db"))
    first = store.claim("request-1", "hash-1")
    store.fail("request-1", "hash-1", first.claim_token, "model_timeout")

    reclaimed = store.claim("request-1", "hash-1")

    assert reclaimed.execute is True
    assert reclaimed.reason == "reclaimed"


def test_invalid_lease_configuration_falls_back_and_enables_wal(tmp_path, monkeypatch):
    monkeypatch.setenv("API_REQUEST_REPLAY_LEASE_SECONDS", "not-a-number")
    store = ApiRequestReplayStore(str(tmp_path / "replays.db"))

    with store._connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert store.lease_seconds == 60.0
    assert journal_mode == "wal"


def test_reclaimed_request_fences_out_previous_owner(tmp_path):
    path = tmp_path / "replays.db"
    store = ApiRequestReplayStore(str(path), lease_seconds=30)
    first = store.claim("request-1", "hash-1")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE api_request_replays SET lease_expires_at = 0 WHERE request_id = ?",
            ("request-1",),
        )
    second = store.claim("request-1", "hash-1")

    with pytest.raises(RequestReplayLeaseLost):
        store.complete("request-1", "hash-1", first.claim_token, {"reply": "stale"})
    store.complete("request-1", "hash-1", second.claim_token, {"reply": "current"})

    replay = store.claim("request-1", "hash-1")
    assert replay.response == {"reply": "current"}
