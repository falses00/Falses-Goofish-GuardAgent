import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from XianyuAgent import XianyuReplyBot
from XianyuApis import XianyuApis, XianyuAuthenticationError, XianyuRiskControlError
from core.agent_registry import AgentRegistry
from core.runtime_config import diagnose_runtime


ROOT = Path(__file__).resolve().parents[1]


class FailingCompletions:
    def create(self, **kwargs):
        raise TimeoutError("model timeout")


class FailingChat:
    def __init__(self):
        self.completions = FailingCompletions()


class FailingLLMClient:
    def __init__(self):
        self.chat = FailingChat()


class ShippingAgent:
    def __init__(self):
        self.last_trace = {}

    def generate(self, **kwargs):
        self.last_trace = {
            "guardrails": ["shipping_policy"],
            "model": {"status": "not_used"},
        }
        return "付款后我按平台订单发，具体时间以商品说明为准。"


def build_failing_bot(tmp_path):
    return XianyuReplyBot(
        client=FailingLLMClient(),
        db_path=str(tmp_path / "chat_history.db"),
    )


def test_custom_agent_registration_survives_prompt_reload(tmp_path):
    bot = build_failing_bot(tmp_path)
    shipping_agent = ShippingAgent()
    bot.register_agent(
        "shipping",
        shipping_agent,
        keywords=["多久发货"],
        priority=5,
    )

    first_reply = bot.generate_reply(
        "付款后多久发货",
        "当前商品的信息如下：标题:测试商品 价格:100元",
        context=[],
        chat_id="chat_shipping",
        item_id="item_shipping",
    )
    bot.reload_prompts()
    second_reply = bot.generate_reply(
        "付款后多久发货",
        "当前商品的信息如下：标题:测试商品 价格:100元",
        context=[],
        chat_id="chat_shipping",
        item_id="item_shipping",
    )

    assert first_reply == second_reply
    assert bot.last_intent == "shipping"
    assert bot.last_trace.routed_agent == "ShippingAgent"
    assert "shipping" in bot.available_intents()
    assert "shipping_policy" in bot.last_trace.guardrails


def test_registry_rejects_duplicate_and_invalid_handlers():
    registry = AgentRegistry()
    handler = ShippingAgent()
    registry.register("shipping", handler)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("shipping", handler)
    with pytest.raises(TypeError, match="must define generate"):
        registry.register("broken", object())


def test_model_timeout_uses_safe_default_reply(tmp_path):
    bot = build_failing_bot(tmp_path)

    reply = bot.generate_reply(
        "你好，还在吗？",
        "当前商品的信息如下：标题:测试商品 价格:100元",
        context=[],
        chat_id="chat_model_failure",
        item_id="item_failure",
    )

    assert reply == "在的，你具体想问商品哪方面？我按商品信息跟你说。"
    assert bot.last_trace.model["router"]["model"] == {
        "status": "fallback",
        "error_type": "TimeoutError",
    }
    assert bot.last_trace.model["responder"] == {
        "status": "fallback",
        "error_type": "TimeoutError",
    }
    assert "router_model_fallback" in bot.last_trace.guardrails
    assert "model_fallback" in bot.last_trace.guardrails


def test_price_agent_fallback_preserves_guardrail_price(tmp_path):
    bot = build_failing_bot(tmp_path)
    item_desc = (
        '当前商品的信息如下：标题:iPad 价格:4299元 '
        '详情: {"title": "iPad", "original_price": 4299, "min_price": 3800}'
    )

    reply = bot.generate_reply(
        "3000 元能出吗",
        item_desc,
        context=[],
        chat_id="chat_price_failure",
        item_id="item_price_failure",
    )

    assert "4149" in reply
    assert bot.last_trace.price_decision["calculated_price"] == 4149
    assert bot.last_trace.model["router"] == {"source": "rule", "intent": "price"}
    assert bot.last_trace.model["responder"]["status"] == "fallback"
    assert "pricing_floor" in bot.last_trace.guardrails
    assert "model_fallback" in bot.last_trace.guardrails


def test_tech_agent_never_leaks_demo_product_facts_into_another_item(tmp_path):
    bot = build_failing_bot(tmp_path)
    item_desc = (
        '当前商品的信息如下：详情: {"title": "阿里云优惠教程", '
        '"desc": "付款后发送领取步骤，资格以阿里云账号页面为准"}'
    )

    reply = bot.generate_reply(
        "这个有划痕吗",
        item_desc,
        context=[],
        chat_id="chat_cross_product",
        item_id="aliyun_coupon_300",
    )

    assert bot.last_trace.knowledge["source"] == "item_context"
    assert "阿里云账号页面" in reply
    assert "iPad" not in reply
    assert "电池健康" not in reply


def test_runtime_doctor_accepts_cookie_without_spaces(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", "doctor-test-key")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("COOKIES_STR", "foo=1;unb=doctor_seller;bar=2")

    report = diagnose_runtime(mode="xianyu", root=ROOT)

    assert report.ready is True
    assert all(check.ok for check in report.checks)


def test_runtime_doctor_fails_without_credentials(monkeypatch):
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("COOKIES_STR", "your_cookies_here")

    report = diagnose_runtime(mode="xianyu", root=ROOT)

    assert report.ready is False
    failed_names = {check.name for check in report.checks if not check.ok}
    assert failed_names == {"model_credentials", "xianyu_cookie"}
    assert "doctor-test-key" not in str(report.to_dict())


def test_expired_cookie_raises_typed_error_instead_of_exiting(monkeypatch):
    api = XianyuApis()
    monkeypatch.setattr(api, "hasLogin", lambda retry_count=0: False)

    with pytest.raises(XianyuAuthenticationError, match="Cookie"):
        api.get_token("device", retry_count=2)


def test_risk_control_fails_fast_in_non_interactive_mode(monkeypatch):
    class RiskControlResponse:
        headers = {}

        @staticmethod
        def json():
            return {"ret": ["RGV587_ERROR::被挤爆啦"]}

    api = XianyuApis()
    api.session.cookies.set("_m_h5_tk", "token_123")
    monkeypatch.setenv("NON_INTERACTIVE", "true")
    monkeypatch.setattr(api.session, "post", lambda *args, **kwargs: RiskControlResponse())

    with pytest.raises(XianyuRiskControlError, match="风控"):
        api.get_token("device")
