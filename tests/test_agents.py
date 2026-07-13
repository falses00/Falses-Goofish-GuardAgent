import os
import sys
import pytest

# 确保项目根目录在 Python 模块搜索路径中
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.experts import BargainExpert, FAQExpert
from core.model_provider import AGNES_BASE_URL, AGNES_MODEL_NAME, has_model_api_key, resolve_model_config
from context_manager import ChatContextManager
from XianyuAgent import IntentRouter, PriceAgent

def test_bargain_expert_pan_bargain():
    """测试买家没有提出具体价格时的泛议价策略"""
    original_price = 4299.0
    min_price = 3800.0
    expert = BargainExpert(original_price, min_price)

    # 模拟首轮泛议价
    decision = expert.calculate_next_price(buyer_offer=None, last_committed_price=None)
    assert decision["action"] == "NEGOTIATE"
    # 应主动给出微调降价 (concession = (4299-3800)*0.15 = 74.85， 4299-75 = 4224)
    assert decision["price"] == 4224

def test_bargain_expert_below_min():
    """测试买家提出低于绝对底价的出价时的拒绝策略"""
    original_price = 4299.0
    min_price = 3800.0
    expert = BargainExpert(original_price, min_price)

    # 买家出价 3000 元（低于底线 3800）
    decision = expert.calculate_next_price(buyer_offer=3000.0, last_committed_price=4299.0)
    assert decision["action"] == "REFUSE_AND_COUNTER"
    # 我们应拒绝并在原报价基础上降 30% 差额，但守住 3800
    # suggested = 4299 - (4299-3800)*0.3 = 4299 - 149.7 = 4149.3 -> 4149
    assert decision["price"] == 4149


def test_bargain_expert_negotiate():
    """测试买家提出处于合理价格区间时的拉锯与妥协策略"""
    original_price = 4299.0
    min_price = 3800.0
    expert = BargainExpert(original_price, min_price)

    # 上一次我方报价 4150，买家出价 3900 元（在底线 3800 以上）
    decision = expert.calculate_next_price(buyer_offer=3900.0, last_committed_price=4150.0)
    assert decision["action"] == "NEGOTIATE"
    # 差额 = 4150 - 3900 = 250。我们退让 40%，即退让 100 元 -> 4150 - 100 = 4050 元
    assert decision["price"] == 4050

def test_bargain_expert_accept():
    """测试买家出价与我方极其接近时的直接同意成交策略"""
    original_price = 4299.0
    min_price = 3800.0
    expert = BargainExpert(original_price, min_price)

    # 上一次我方报价 3820 元，买家出价 3815 元（与我们极其贴近）
    decision = expert.calculate_next_price(buyer_offer=3815.0, last_committed_price=3820.0)
    assert decision["action"] == "ACCEPT"
    assert decision["price"] == 3815.0


def test_bargain_expert_never_raises_committed_price():
    """买家出价高于历史承诺价时，不能重新报更高价格。"""
    expert = BargainExpert(original_price=4299.0, min_price=3800.0)

    decision = expert.calculate_next_price(buyer_offer=4100.0, last_committed_price=4050.0)

    assert decision["action"] == "ACCEPT"
    assert decision["price"] == 4050.0

def test_faq_expert_rag():
    """测试 FAQ 知识库对不同关键词的 RAG 参数精准匹配"""
    product_info = {
      "title": "二手 iPad Pro 11寸",
      "shipping_fee": "包邮 (顺丰包邮)",
      "specs": { "battery_health": "93%" },
      "condition": { "screen": "完美无划痕", "repair": "无任何拆修历史" },
      "accessories": { "charger": "带原装 20W 充电头" }
    }

    expert = FAQExpert(product_info)

    # 咨询屏幕/成色
    kb1 = expert.extract_related_kb("这个机子屏幕有划痕吗")
    assert "完美无划痕" in kb1

    # 咨询配件
    kb2 = expert.extract_related_kb("送充电头吗")
    assert "带原装 20W 充电头" in kb2

    # 咨询拆修
    kb3 = expert.extract_related_kb("有没有拆过或者换过屏幕")
    assert "无任何拆修历史" in kb3

    # 未命中时不伪装成 RAG 命中，交给商品描述和通用提示词兜底
    kb4 = expert.extract_related_kb("你好")
    assert kb4 == ""


def test_price_profile_prefers_json_floor(monkeypatch):
    """商品配置显式 min_price 时，应优先于环境折扣底线。"""
    monkeypatch.setenv("DEFAULT_DISCOUNT_LIMIT", "0.50")
    item_desc = '当前商品的信息如下：标题:iPad 价格:4299元 详情: {"original_price": 4299, "min_price": 3800}'

    original_price, min_price, source = PriceAgent._extract_price_profile(item_desc)

    assert original_price == 4299
    assert min_price == 3800
    assert source == "json"


def test_invalid_discount_limit_falls_back(monkeypatch):
    """错误折扣配置不能把底价算成 0 或高于原价。"""
    monkeypatch.setenv("DEFAULT_DISCOUNT_LIMIT", "1.5")

    original_price, min_price, source = PriceAgent._extract_price_profile("价格:4299元")

    assert original_price == 4299
    assert min_price == pytest.approx(3654.15)
    assert source == "text_price+discount_limit"


def test_offer_extraction_ignores_storage_numbers():
    """规格数字在具体报价之前出现时，不应误判为买家出价。"""
    offer = PriceAgent._extract_buyer_offer("128G 的话，3000 元能出吗", original_price=4299)

    assert offer == 3000


def test_router_prefers_explicit_offer_over_storage_spec():
    router = IntentRouter(classify_agent=None)

    intent = router.detect("128G 的话，3000 元能出吗", item_desc="", context="")

    assert intent == "price"


def test_faq_expert_extracts_storage_and_battery_facts():
    expert = FAQExpert({
        "specs": {
            "model": "iPad Pro M2",
            "storage": "128GB",
            "network": "WiFi版",
            "color": "深空灰色",
            "battery_health": "93%",
            "charge_cycles": 184,
        }
    })

    context = expert.extract_related_kb("128GB 版本吗，电池健康和循环次数多少？")

    assert "iPad Pro M2" in context
    assert "128GB" in context
    assert "93%" in context
    assert "184" in context


def test_price_router_detects_bare_number_offer():
    """真实买家常说 '4100 可以马上拍'，不能漏到 default。"""
    router = IntentRouter(classify_agent=None)

    intent = router.detect("4100 可以的话我马上拍", item_desc="", context="")

    assert intent == "price"


def test_price_router_detects_number_offer_with_action_later():
    """裸数字后面隔着中文动作词时，也应识别为议价。"""
    router = IntentRouter(classify_agent=None)

    intent = router.detect("4300 给你，直接拍", item_desc="", context="")

    assert intent == "price"


def test_price_commitment_memory_is_monotonic(tmp_path):
    """价格记忆应保守更新：我方最低承诺取更低值，买家最高出价取更高值。"""
    db_path = tmp_path / "chat_history.db"
    manager = ChatContextManager(db_path=str(db_path))

    manager.update_price_commitments(
        "chat_a",
        lowest_price_committed=4100,
        buyer_highest_offer=3900,
    )
    manager.update_price_commitments(
        "chat_a",
        lowest_price_committed=4200,
        buyer_highest_offer=3800,
    )

    lowest_committed, buyer_highest = manager.get_price_commitments("chat_a")

    assert lowest_committed == 4100
    assert buyer_highest == 3900

    manager.update_price_commitments(
        "chat_a",
        lowest_price_committed=4050,
        buyer_highest_offer=4000,
    )

    lowest_committed, buyer_highest = manager.get_price_commitments("chat_a")

    assert lowest_committed == 4050
    assert buyer_highest == 4000


def test_append_turn_atomically_updates_memory_snapshot(tmp_path):
    """一轮对话应原子写入用户消息、助手回复和议价次数。"""
    db_path = tmp_path / "chat_history.db"
    manager = ChatContextManager(db_path=str(db_path))

    manager.append_turn(
        "chat_atomic",
        "buyer",
        "item_1",
        "3000 元能出吗",
        "seller",
        assistant_text="最低 4149 元",
        intent="price",
    )

    snapshot = manager.get_memory_snapshot("chat_atomic")

    assert snapshot.bargain_count == 1
    assert snapshot.messages == [
        {"role": "user", "content": "3000 元能出吗"},
        {"role": "assistant", "content": "最低 4149 元"},
    ]


def test_append_turn_trims_history_by_chat(tmp_path):
    """超过 max_history 后，只保留当前 chat 的最新消息。"""
    db_path = tmp_path / "chat_history.db"
    manager = ChatContextManager(max_history=3, db_path=str(db_path))

    for idx in range(4):
        manager.append_turn(
            "chat_trim",
            "buyer",
            "item_1",
            f"消息 {idx}",
            "seller",
            assistant_text=None,
            intent="default",
        )

    snapshot = manager.get_memory_snapshot("chat_trim")

    assert len(snapshot.messages) == 3
    assert snapshot.messages[0]["content"] == "消息 1"
    assert snapshot.messages[-1]["content"] == "消息 3"


def test_agnes_provider_is_default(monkeypatch):
    """默认模型提供商应指向 Agnes 的 OpenAI-compatible API。"""
    for key in [
        "MODEL_PROVIDER",
        "AGNES_API_KEY",
        "AGNES_BASE_URL",
        "AGNES_MODEL_NAME",
        "API_KEY",
        "MODEL_BASE_URL",
        "MODEL_NAME",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AGNES_API_KEY", "test-agnes-key")

    config = resolve_model_config()

    assert config.provider == "agnes"
    assert config.api_key == "test-agnes-key"
    assert config.base_url == AGNES_BASE_URL
    assert config.model_name == AGNES_MODEL_NAME


def test_placeholder_model_api_key_is_not_treated_as_configured(monkeypatch):
    """示例占位符不能让 API 服务误以为已配置真实密钥。"""
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "your_api_key_here")

    assert has_model_api_key() is False
