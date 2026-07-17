import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.app import create_app
from core.runtime_status import RuntimeStatusStore


def build_client(tmp_path):
    app = create_app(
        offline_mode=True,
        db_path=str(tmp_path / "api_chat_history.db"),
        trace_path=str(tmp_path / "agent_traces.jsonl"),
        request_replay_path=str(tmp_path / "api_request_replay.db"),
    )
    return TestClient(app)


def test_health_reports_offline_mode(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "offline_mode": True}


def test_capabilities_exposes_registered_intents(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/api/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "intents": ["price", "tech", "default"],
        "offline_mode": True,
        "extension_contract": "register_agent",
    }


def test_reply_routes_tech_question_and_persists_memory(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/api/reply",
        json={
            "chat_id": "api_chat_tech",
            "item_id": "item_ipad",
            "user_msg": "这个屏幕有划痕吗，电池怎么样",
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["intent"] == "tech"
    assert payload["trace"]["routed_agent"] == "TechAgent"
    assert payload["trace"]["knowledge"]["matched"] is True
    assert payload["memory"]["bargain_count"] == 0
    assert len(payload["memory"]["messages"]) == 2


def test_reply_persists_price_guardrail_trace(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/api/reply",
        json={
            "chat_id": "api_chat_price",
            "item_id": "item_ipad",
            "user_msg": "3000 元能出吗",
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["intent"] == "price"
    assert payload["trace"]["price_decision"]["buyer_offer"] == 3000
    assert payload["trace"]["price_decision"]["calculated_price"] >= payload["trace"]["price_decision"]["min_price"]
    assert "pricing_floor" in payload["trace"]["guardrails"]
    assert payload["memory"]["bargain_count"] == 1
    assert payload["memory"]["lowest_price_committed"] == payload["trace"]["price_decision"]["calculated_price"]

    traces = client.get("/api/traces", params={"limit": 1}).json()
    assert traces["count"] == 1
    assert traces["items"][0]["trace"]["chat_id"] == "api_chat_price"


def test_reply_combines_additional_user_messages_before_agent_loop(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/api/reply",
        json={
            "chat_id": "api_chat_batch",
            "item_id": "item_ipad",
            "user_msg": "你好",
            "additional_user_msgs": ["128G 吗", "3000 元能出吗"],
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["intent"] == "price"
    assert payload["trace"]["price_decision"]["buyer_offer"] == 3000
    assert len(payload["memory"]["messages"]) == 2
    assert "用户连续发送了以下消息" in payload["memory"]["messages"][0]["content"]
    assert "128G 吗" in payload["memory"]["messages"][0]["content"]


def test_empty_user_message_is_rejected(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/api/reply",
        json={
            "chat_id": "api_chat_bad",
            "item_id": "item_ipad",
            "user_msg": "",
        },
    )

    assert response.status_code == 422


def test_api_falls_back_to_offline_when_key_is_placeholder(tmp_path, monkeypatch):
    monkeypatch.setenv("API_OFFLINE_MODE", "false")
    monkeypatch.setenv("AGNES_API_KEY", "your_agnes_api_key_here")
    monkeypatch.delenv("API_KEY", raising=False)

    app = create_app(
        db_path=str(tmp_path / "api_chat_history.db"),
        trace_path=str(tmp_path / "agent_traces.jsonl"),
        request_replay_path=str(tmp_path / "api_request_replay.db"),
    )
    client = TestClient(app)

    assert client.get("/health").json()["offline_mode"] is True


def test_request_id_replays_completed_response_without_duplicate_memory(tmp_path):
    client = build_client(tmp_path)
    payload = {
        "request_id": "gateway-retry-001",
        "chat_id": "api_chat_retry",
        "item_id": "item_ipad",
        "user_msg": "3000 元能出吗",
    }

    first = client.post("/api/reply", json=payload)
    second = client.post("/api/reply", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert second.json()["idempotent_replay"] is True
    assert second.json()["request_id"] == payload["request_id"]
    assert second.json()["reply"] == first.json()["reply"]
    assert second.json()["trace"] == first.json()["trace"]
    assert second.json()["memory"]["bargain_count"] == 1
    assert len(second.json()["memory"]["messages"]) == 2
    assert client.get("/api/traces").json()["count"] == 1


def test_request_id_rejects_different_payload(tmp_path):
    client = build_client(tmp_path)
    first = {
        "request_id": "gateway-conflict-001",
        "chat_id": "api_chat_conflict",
        "item_id": "item_ipad",
        "user_msg": "3000 元能出吗",
    }
    conflicting = {**first, "user_msg": "4000 元能出吗"}

    assert client.post("/api/reply", json=first).status_code == 200
    response = client.post("/api/reply", json=conflicting)

    assert response.status_code == 409
    assert response.json()["detail"] == "request_id_payload_mismatch"


def test_shared_agent_decisions_are_serialized_and_traces_do_not_cross(tmp_path):
    app = create_app(
        offline_mode=True,
        db_path=str(tmp_path / "api_chat_history.db"),
        trace_path=str(tmp_path / "agent_traces.jsonl"),
        request_replay_path=str(tmp_path / "api_request_replay.db"),
    )
    client = TestClient(app)
    original_generate_reply = app.state.bot.generate_reply
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def observed_generate_reply(*args, **kwargs):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.03)
            return original_generate_reply(*args, **kwargs)
        finally:
            with counter_lock:
                active -= 1

    app.state.bot.generate_reply = observed_generate_reply
    payloads = [
        {
            "request_id": f"parallel-{index}",
            "chat_id": f"parallel-chat-{index}",
            "item_id": "item_ipad",
            "user_msg": "3000 元能出吗" if index % 2 == 0 else "电池健康多少",
        }
        for index in range(6)
    ]

    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(executor.map(lambda payload: client.post("/api/reply", json=payload), payloads))

    assert max_active == 1
    for index, response in enumerate(responses):
        assert response.status_code == 200
        expected_intent = "price" if index % 2 == 0 else "tech"
        assert response.json()["intent"] == expected_intent
        assert response.json()["trace"]["intent"] == expected_intent


def test_slow_request_renews_replay_lease_across_app_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("API_REQUEST_REPLAY_LEASE_SECONDS", "1")
    db_path = str(tmp_path / "shared_chat.db")
    trace_path = str(tmp_path / "shared_traces.jsonl")
    replay_path = str(tmp_path / "shared_replays.db")
    app_one = create_app(
        offline_mode=True,
        db_path=db_path,
        trace_path=trace_path,
        request_replay_path=replay_path,
    )
    app_two = create_app(
        offline_mode=True,
        db_path=db_path,
        trace_path=trace_path,
        request_replay_path=replay_path,
    )
    client_one = TestClient(app_one)
    client_two = TestClient(app_two)
    started = threading.Event()
    original_generate_reply = app_one.state.bot.generate_reply

    def slow_generate_reply(*args, **kwargs):
        started.set()
        time.sleep(2.2)
        return original_generate_reply(*args, **kwargs)

    app_one.state.bot.generate_reply = slow_generate_reply
    payload = {
        "request_id": "slow-shared-request",
        "chat_id": "slow-shared-chat",
        "item_id": "item_ipad",
        "user_msg": "3000 元能出吗",
    }

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(client_one.post, "/api/reply", json=payload)
        assert started.wait(timeout=2)
        time.sleep(1.2)
        in_progress = client_two.post("/api/reply", json=payload)
        first = first_future.result(timeout=5)

    replayed = client_two.post("/api/reply", json=payload)
    memory = client_two.get("/api/memory/slow-shared-chat").json()
    traces = client_two.get("/api/traces", params={"chat_id": "slow-shared-chat"}).json()

    assert in_progress.status_code == 409
    assert in_progress.json()["detail"] == "request_id_in_progress"
    assert first.status_code == 200
    assert replayed.status_code == 200
    assert replayed.json()["idempotent_replay"] is True
    assert len(memory["messages"]) == 2
    assert memory["bargain_count"] == 1
    assert traces["count"] == 1


def test_request_id_rejects_unsafe_characters(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/api/reply",
        json={
            "request_id": "contains spaces/and/slashes",
            "chat_id": "api_chat_bad_request_id",
            "item_id": "item_ipad",
            "user_msg": "还在吗",
        },
    )

    assert response.status_code == 422


def test_operator_console_and_static_assets_are_served_with_security_headers(tmp_path):
    client = build_client(tmp_path)

    page = client.get("/")
    stylesheet = client.get("/static/styles.css")

    assert page.status_code == 200
    assert "Falses Goofish GuardAgent" in page.text
    assert 'data-view="dashboard"' in page.text
    assert 'data-view="workbench"' in page.text
    assert 'data-view="traces"' in page.text
    assert 'data-view="runtime"' in page.text
    assert 'id="globalSearch"' in page.text
    assert 'id="appWorkspace"' in page.text
    assert 'id="dashboardTraceTable"' in page.text
    assert 'id="runtimeAlert"' in page.text
    assert 'id="traceSearch"' in page.text
    assert 'id="traceStatusFilter"' in page.text
    assert "/static/styles.css?v=20260718.3" in page.text
    assert "/static/app.js?v=20260718.3" in page.text
    assert stylesheet.status_code == 200
    assert page.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-request-id"]


def test_optional_bearer_token_protects_sensitive_api_routes(tmp_path):
    app = create_app(
        offline_mode=True,
        db_path=str(tmp_path / "api_chat_history.db"),
        trace_path=str(tmp_path / "agent_traces.jsonl"),
        request_replay_path=str(tmp_path / "api_request_replay.db"),
        access_token="local-test-token",
    )
    client = TestClient(app)

    assert client.get("/api/access").json()["token_required"] is True
    assert client.get("/api/traces").status_code == 401
    assert client.post("/api/reply", json={"user_msg": "还在吗"}).status_code == 401

    headers = {"Authorization": "Bearer local-test-token"}
    assert client.get("/api/traces", headers=headers).status_code == 200
    assert client.post("/api/reply", json={"user_msg": "还在吗"}, headers=headers).status_code == 200


def test_readiness_and_overview_report_real_worker_snapshot(tmp_path):
    runtime_path = tmp_path / "runtime_status.json"
    RuntimeStatusStore(str(runtime_path)).update(
        "registered",
        dry_run=True,
        reconnect_attempt=0,
        last_heartbeat_response_at=1,
    )
    app = create_app(
        offline_mode=True,
        db_path=str(tmp_path / "api_chat_history.db"),
        trace_path=str(tmp_path / "agent_traces.jsonl"),
        request_replay_path=str(tmp_path / "api_request_replay.db"),
        runtime_status_path=str(runtime_path),
    )
    client = TestClient(app)

    readiness = client.get("/health/ready")
    overview = client.get("/api/overview")

    assert readiness.status_code == 200
    assert readiness.json()["status"] == "ready"
    assert overview.status_code == 200
    assert overview.json()["worker"]["healthy"] is True
    assert overview.json()["worker"]["status"]["dry_run"] is True
    assert overview.json()["agent"]["intent_count"] == 3


def test_memory_endpoint_returns_persisted_chat_snapshot(tmp_path):
    client = build_client(tmp_path)
    response = client.post(
        "/api/reply",
        json={
            "chat_id": "memory-console-chat",
            "item_id": "item_ipad",
            "user_msg": "3000 元能出吗",
        },
    )

    memory = client.get("/api/memory/memory-console-chat")

    assert response.status_code == 200
    assert memory.status_code == 200
    assert memory.json()["chat_id"] == "memory-console-chat"
    assert memory.json()["bargain_count"] == 1
    assert len(memory.json()["messages"]) == 2


def test_trace_filters_and_request_size_limits(tmp_path):
    client = build_client(tmp_path)
    assert client.post(
        "/api/reply",
        json={"chat_id": "filter-price", "item_id": "item", "user_msg": "3000 元能出吗"},
    ).status_code == 200
    assert client.post(
        "/api/reply",
        json={"chat_id": "filter-tech", "item_id": "item", "user_msg": "电池怎么样"},
    ).status_code == 200

    filtered = client.get("/api/traces", params={"intent": "price", "limit": 10})
    oversized = client.post("/api/reply", json={"user_msg": "x" * 2001})

    assert filtered.status_code == 200
    assert filtered.json()["count"] == 1
    assert filtered.json()["items"][0]["trace"]["chat_id"] == "filter-price"
    assert oversized.status_code == 422


def test_reply_rejects_blank_messages_and_identifiers(tmp_path):
    client = build_client(tmp_path)

    blank_message = client.post("/api/reply", json={"user_msg": "   "})
    blank_chat_id = client.post(
        "/api/reply",
        json={"user_msg": "还在吗", "chat_id": "   "},
    )

    assert blank_message.status_code == 422
    assert blank_chat_id.status_code == 422


def test_non_persistent_price_simulation_has_no_memory_side_effects(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/api/reply",
        json={
            "chat_id": "dry-simulation-chat",
            "item_id": "item_ipad",
            "user_msg": "3000 元能出吗",
            "persist_turn": False,
        },
    )
    memory = client.get("/api/memory/dry-simulation-chat")

    assert response.status_code == 200
    assert response.json()["memory"]["messages"] == []
    assert response.json()["memory"]["bargain_count"] == 0
    assert response.json()["memory"]["lowest_price_committed"] is None
    assert response.json()["memory"]["buyer_highest_offer"] is None
    assert memory.json() == response.json()["memory"]
