import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.message_aggregation import MessageAggregator


def test_message_aggregator_debounces_same_conversation():
    aggregator = MessageAggregator(debounce_seconds=1.0)

    key, should_flush = aggregator.append("chat_1", "item_1", "buyer_1", "你好", now_ms=1000)
    assert should_flush is False
    aggregator.append("chat_1", "item_1", "buyer_1", "3000 元能出吗", now_ms=1500)

    assert aggregator.pop_ready(now_ms=2000) == []

    batches = aggregator.pop_ready(now_ms=2500)
    assert len(batches) == 1
    assert batches[0].count == 2
    assert "你好" in batches[0].combined_text()
    assert "3000 元能出吗" in batches[0].combined_text()
    assert aggregator.pop(key) is None


def test_message_aggregator_isolates_items_and_buyers():
    aggregator = MessageAggregator(debounce_seconds=0.5)

    aggregator.append("chat_1", "item_1", "buyer_1", "消息 A", now_ms=1000)
    aggregator.append("chat_1", "item_2", "buyer_1", "消息 B", now_ms=1000)
    aggregator.append("chat_1", "item_1", "buyer_2", "消息 C", now_ms=1000)

    batches = aggregator.pop_ready(now_ms=1600)

    assert sorted(batch.combined_text() for batch in batches) == ["消息 A", "消息 B", "消息 C"]


def test_message_aggregator_forces_flush_at_max_messages():
    aggregator = MessageAggregator(debounce_seconds=10, max_messages=2)

    _, should_flush_first = aggregator.append("chat_1", "item_1", "buyer_1", "第一条", now_ms=1000)
    key, should_flush_second = aggregator.append("chat_1", "item_1", "buyer_1", "第二条", now_ms=1100)

    assert should_flush_first is False
    assert should_flush_second is True
    batch = aggregator.pop(key)
    assert batch.count == 2
