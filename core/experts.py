import json
from typing import Dict, Any, Optional


class BargainExpert:
    """
    议价决策专家模块。
    通过将 LLM 的口语化表达与绝对的数值护栏 (Guardrails) 相结合，进行多轮退让议价。
    核心原则：守住最大折扣门限，确保不发生亏损。
    """

    def __init__(self, original_price: float, min_price: float):
        self.original_price = original_price
        self.min_price = min_price

    def calculate_next_price(
        self,
        buyer_offer: Optional[float],
        last_committed_price: Optional[float],
        bargain_count: int = 0,
        buyer_highest_offer: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        根据买家出价和上一次的报价，计算我方的新报价。

        Args:
            buyer_offer: 买家当前给出的具体出价，如果没有为 None
            last_committed_price: 之前承诺过的最低价，如果没有则默认为原价

        Returns:
            Dict 包含：
            - "price": 新的合理出价 (float)
            - "action": 决策动作
              ("ACCEPT" | "REFUSE_AND_COUNTER" | "REFUSE_AND_HOLD" | "NEGOTIATE")
        """
        committed_price = last_committed_price if last_committed_price is not None else self.original_price
        committed_price = max(self.min_price, min(committed_price, self.original_price))

        # 1. 泛议价只在首轮主动小让；后续必须由买家给出进展。
        if buyer_offer is None:
            if bargain_count > 0 or committed_price <= self.min_price:
                return {
                    "price": committed_price,
                    "action": "REFUSE_AND_HOLD",
                    "reason": "买家未给出新报价，维持历史承诺价，避免卖家单方面连续让步",
                }
            concession = (self.original_price - self.min_price) * 0.15
            suggested = round(committed_price - concession)
            suggested = max(self.min_price, suggested)

            return {
                "price": suggested,
                "action": "NEGOTIATE",
                "reason": "买家泛议价，主动微降以示诚意，引导其具体出价"
            }

        # 2. 达到历史承诺价时必须兑现承诺，不能临时涨价。
        if buyer_offer >= committed_price:
            return {
                "price": committed_price,
                "action": "ACCEPT",
                "reason": "买家出价已达到我方历史承诺价，直接同意成交"
            }

        buyer_made_progress = (
            buyer_highest_offer is None or buyer_offer > buyer_highest_offer
        )
        if bargain_count > 0 and not buyer_made_progress:
            return {
                "price": committed_price,
                "action": "REFUSE_AND_HOLD",
                "reason": "买家报价没有高于历史最高出价，维持我方历史承诺价",
            }

        gap = committed_price - buyer_offer
        acceptance_gap = max(
            10.0,
            self.original_price * (0.005 if bargain_count == 0 else 0.015),
        )
        if buyer_offer >= self.min_price and gap <= acceptance_gap:
            return {
                "price": buyer_offer,
                "action": "ACCEPT",
                "reason": "买家报价在底价之上且已接近我方历史报价，爽快成交",
            }

        # 3. 低于保留价始终拒绝。只有买家提高报价时才给一次更小的反报价让步。
        if buyer_offer < self.min_price:
            concession_rate = 0.3 if bargain_count == 0 else 0.15
            suggested = committed_price - (committed_price - self.min_price) * concession_rate
            suggested = max(self.min_price, round(suggested))

            return {
                "price": suggested,
                "action": "REFUSE_AND_COUNTER",
                "reason": f"买家出价 {buyer_offer} 低于绝对底线 {self.min_price}，拒绝并给出有限反报价"
            }

        # 4. 合理区间内按轮次缩小让步幅度，避免越谈越快。
        concession_rate = 0.4 if bargain_count == 0 else 0.25
        suggested = committed_price - gap * concession_rate
        suggested = max(self.min_price, round(suggested))

        return {
            "price": suggested,
            "action": "NEGOTIATE",
            "reason": f"买家出价 {buyer_offer} 处于合理区间内，双方折中报价 {suggested}"
        }


class FAQExpert:
    """
    商品参数 RAG FAQ 专家模块。
    加载本地商品属性 JSON 数据库，提取关键参数，组装上下文防止大模型幻觉。
    """

    def __init__(self, product_info: Dict[str, Any]):
        self.product_info = product_info

    def get_product_context_str(self) -> str:
        """格式化商品参数上下文，作为 LLM 的注入输入"""
        return json.dumps(self.product_info, ensure_ascii=False, indent=2)

    def extract_related_kb(self, user_msg: str) -> str:
        """
        轻量级关键词知识库匹配。
        提取与买家提问相关的商品参数，强化大模型回答的准确性。
        """
        matched = []
        user_msg_lower = user_msg.lower()
        generic_description = str(self.product_info.get("desc") or "").strip()

        def append_fact(label: str, *values: Any) -> None:
            facts = [str(value).strip() for value in values if value not in (None, "")]
            if facts:
                matched.append(f"【{label}】: {' | '.join(facts)}")
            elif generic_description:
                matched.append(f"【商品描述】: {generic_description}")

        # 简单成色/外观匹配
        if any(kw in user_msg_lower for kw in ["成色", "划痕", "磕碰", "磨损", "几成新"]):
            condition = self.product_info.get("condition", {})
            append_fact("外观与成色", condition.get("screen"), condition.get("body"))

        # 型号、容量、电池等规格匹配
        if any(
            kw in user_msg_lower
            for kw in ["型号", "容量", "内存", "存储", "gb", "128g", "256g", "512g", "1tb"]
        ):
            specs = self.product_info.get("specs", {})
            append_fact(
                "型号与规格",
                specs.get("model"),
                specs.get("storage"),
                specs.get("network"),
                specs.get("color"),
            )

        if any(kw in user_msg_lower for kw in ["电池", "健康", "循环", "续航"]):
            specs = self.product_info.get("specs", {})
            append_fact("电池状态", specs.get("battery_health"), specs.get("charge_cycles"))

        # 配件匹配
        if any(kw in user_msg_lower for kw in ["配件", "充电器", "线", "盒", "送", "包装"]):
            acc = self.product_info.get("accessories", {})
            append_fact("随附配件", acc.get("charger"), acc.get("cable"), acc.get("box"), acc.get("gifts"))

        # 拆修匹配
        if any(kw in user_msg_lower for kw in ["拆", "修", "换过", "屏幕坏", "绿"]):
            append_fact("拆修情况", self.product_info.get("condition", {}).get("repair"))

        # 快递/发货匹配
        if any(kw in user_msg_lower for kw in ["快递", "发什么", "包邮", "邮费", "发货", "哪里发"]):
            shipping = self.product_info.get("shipping", {})
            append_fact("发货与物流", self.product_info.get("shipping_fee"), shipping.get("courier"), shipping.get("origin"))

        # 面交匹配
        if any(kw in user_msg_lower for kw in ["面交", "当面", "自提"]):
            append_fact("面交与线下自提", self.product_info.get("faq", {}).get("face_to_face_trade"))

        # 换机原因匹配
        if any(kw in user_msg_lower for kw in ["为什么卖", "为什么出", "换机", "转手", "出掉"]):
            append_fact("转让原因", self.product_info.get("faq", {}).get("reason_for_selling"))

        if not matched:
            return ""
        return "\n".join(matched)
