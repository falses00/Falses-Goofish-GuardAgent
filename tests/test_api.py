import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.app import create_app


def build_client(tmp_path):
    app = create_app(
        offline_mode=True,
        db_path=str(tmp_path / "api_chat_history.db"),
        trace_path=str(tmp_path / "agent_traces.jsonl"),
    )
    return TestClient(app)


def test_health_reports_offline_mode(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "offline_mode": True}


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
    )
    client = TestClient(app)

    assert client.get("/health").json()["offline_mode"] is True
