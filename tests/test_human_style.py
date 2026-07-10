import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from XianyuAgent import XianyuReplyBot


class RoboticCompletions:
    def create(self, model, messages, temperature=0.4, max_tokens=500, top_p=0.8):
        content = "您好，感谢咨询。作为AI客服，我建议您根据本商品规则理性判断，请问还有什么可以帮您？"
        return type("RoboticResponse", (), {
            "choices": [type("RoboticChoice", (), {
                "message": type("RoboticMessage", (), {"content": content})()
            })()]
        })()


class RoboticChat:
    def __init__(self):
        self.completions = RoboticCompletions()


class RoboticClient:
    def __init__(self):
        self.chat = RoboticChat()


def test_agent_rewrites_robotic_customer_service_tone(tmp_path):
    bot = XianyuReplyBot(client=RoboticClient(), db_path=str(tmp_path / "chat.db"))
    item_desc = (
        '当前商品的信息如下：标题:二手 iPad Pro 价格:4299元 '
        '详情: {"title": "二手 iPad Pro", "original_price": 4299, "min_price": 3800}'
    )

    reply = bot.generate_reply(
        "在吗？",
        item_desc,
        context=[],
        chat_id="style_chat",
        item_id="item_ipad",
    )
    trace = bot.last_trace.to_dict()

    assert "您好" not in reply
    assert "感谢咨询" not in reply
    assert "作为AI" not in reply
    assert "AI客服" not in reply
    assert len(reply) <= 140
    assert "human_reply_style" in trace["guardrails"]
    assert "human_style_rewrite" in trace["guardrails"]
    assert trace["style"]["changed"] is True
