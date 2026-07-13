import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.product_rules import ProductRuleStore
from XianyuAgent import XianyuReplyBot


class UnsafeCompletions:
    def create(self, model, messages, temperature=0.4, max_tokens=500, top_p=0.8):
        content = "这是官方内部渠道，百分百成功，保证每个账号都能领取。"
        return type("UnsafeResponse", (), {
            "choices": [type("UnsafeChoice", (), {
                "message": type("UnsafeMessage", (), {"content": content})()
            })()]
        })()


class UnsafeChat:
    def __init__(self):
        self.completions = UnsafeCompletions()


class UnsafeClient:
    def __init__(self):
        self.chat = UnsafeChat()


def test_product_rule_resolves_by_item_id():
    store = ProductRuleStore()

    rule = store.resolve(item_id="aliyun_coupon_300")

    assert rule.rule_id == "aliyun_coupon_300_tutorial"
    assert rule.delivery.type == "digital_link"
    assert rule.delivery.requires_manual_confirm is False


def test_product_rule_inherits_global_forbidden_promises():
    store = ProductRuleStore()

    rule = store.resolve(item_id="item_ipad")

    assert "100%成功" in rule.forbidden_promises
    assert "官方内部渠道" in rule.forbidden_promises
    assert "加微信" in rule.forbidden_promises


def test_delivery_decision_waits_until_paid():
    store = ProductRuleStore()

    decision = store.delivery_decision(item_id="aliyun_coupon_300", order_status="created")

    assert decision.ready is False
    assert decision.action == "wait_for_payment"


def test_delivery_decision_allows_paid_digital_tutorial():
    store = ProductRuleStore()

    decision = store.delivery_decision(item_id="aliyun_coupon_300", order_status="paid")

    assert decision.ready is True
    assert decision.action == "auto_deliver"
    assert "阿里云优惠 300 教程" in decision.message


def test_delivery_decision_requires_manual_review_for_physical_item():
    store = ProductRuleStore()

    decision = store.delivery_decision(item_id="item_ipad", order_status="paid")

    assert decision.ready is False
    assert decision.action == "manual_review"
    assert decision.rule_id == "ipad_pro_m2_physical_trade"


def test_agent_blocks_forbidden_product_promises(tmp_path):
    bot = XianyuReplyBot(client=UnsafeClient(), db_path=str(tmp_path / "chat.db"))
    item_desc = (
        '当前商品的信息如下：标题:阿里云优惠 300 教程 价格:19.9元 '
        '详情: {"title": "阿里云优惠 300 教程", "original_price": 19.9, "min_price": 15}'
    )

    reply = bot.generate_reply(
        "这个能保证成功领取吗？",
        item_desc,
        context=[],
        chat_id="rule_guardrail_chat",
        item_id="aliyun_coupon_300",
    )
    trace = bot.last_trace.to_dict()

    assert "官方内部渠道" not in reply
    assert "百分百成功" not in reply
    assert "rule_forbidden_promise" in trace["guardrails"]
    assert trace["rules"]["safe"] is False
    assert trace["rules"]["rule_id"] == "aliyun_coupon_300_tutorial"
