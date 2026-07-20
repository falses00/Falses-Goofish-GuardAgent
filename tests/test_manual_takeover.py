import os
import sqlite3
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import core.manual_takeover as takeover_module
from core.manual_takeover import ManualTakeoverStore


def test_takeover_is_visible_across_store_instances_and_survives_reopen(tmp_path):
    path = str(tmp_path / "manual_takeovers.db")
    console_store = ManualTakeoverStore(path)
    worker_store = ManualTakeoverStore(path)

    enabled = console_store.enable(
        "chat_1",
        item_id="item_1",
        ttl_seconds=600,
        source="operator_console",
        note="buyer dispute",
    )

    assert enabled.active is True
    assert worker_store.is_active("chat_1") is True
    assert worker_store.count() == 1
    assert ManualTakeoverStore(path).get("chat_1").note == "buyer dispute"

    worker_store.disable("chat_1", source="seller_command")

    assert console_store.is_active("chat_1") is False
    assert console_store.count() == 0
    assert [event["action"] for event in console_store.list_events("chat_1")] == [
        "disabled",
        "enabled",
    ]


def test_takeover_expires_lazily_and_records_audit_event(tmp_path, monkeypatch):
    current_time = 1_720_000_000.0
    monkeypatch.setattr(takeover_module.time, "time", lambda: current_time)
    store = ManualTakeoverStore(str(tmp_path / "manual_takeovers.db"))
    store.enable("chat_expiring", ttl_seconds=60)

    current_time += 61

    assert store.is_active("chat_expiring") is False
    assert store.get("chat_expiring").source == "ttl_expiry"
    assert store.list_events("chat_expiring")[0]["action"] == "expired"


@pytest.mark.parametrize("ttl_seconds", [0, 59, 86401, float("inf")])
def test_takeover_rejects_unsafe_ttl_values(tmp_path, ttl_seconds):
    store = ManualTakeoverStore(str(tmp_path / "manual_takeovers.db"))

    with pytest.raises(ValueError, match="between 60 and 86400"):
        store.enable("chat_1", ttl_seconds=ttl_seconds)


@pytest.mark.parametrize(
    ("configured_ttl", "expected_ttl"),
    [("10", 60.0), ("999999", 86400.0), ("invalid", 3600.0)],
)
def test_default_takeover_ttl_is_safe_when_environment_is_misconfigured(
    tmp_path,
    monkeypatch,
    configured_ttl,
    expected_ttl,
):
    monkeypatch.setenv("MANUAL_MODE_TIMEOUT", configured_ttl)

    store = ManualTakeoverStore(str(tmp_path / "manual_takeovers.db"))

    assert store.default_ttl_seconds == expected_ttl


def test_worker_active_check_does_not_wait_for_cross_process_write_lock(tmp_path):
    path = str(tmp_path / "manual_takeovers.db")
    store = ManualTakeoverStore(path)
    store.enable("chat_1", ttl_seconds=600)
    blocker = sqlite3.connect(path, timeout=1)
    blocker.execute("BEGIN IMMEDIATE")

    try:
        started_at = time.perf_counter()
        assert store.is_active("chat_1") is True
        elapsed = time.perf_counter() - started_at
    finally:
        blocker.rollback()
        blocker.close()

    assert elapsed < 0.5
