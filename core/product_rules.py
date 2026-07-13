import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional


PAID_ORDER_STATUSES = {"paid", "waiting_seller_ship", "waiting_seller_delivery", "等待卖家发货"}


@dataclass
class DeliveryPolicy:
    type: str = "manual_review"
    after: str = "paid"
    requires_manual_confirm: bool = True
    content_ref: str = ""
    message_template: str = ""


@dataclass
class ProductRule:
    rule_id: str
    title: str
    item_ids: List[str] = field(default_factory=list)
    match_titles: List[str] = field(default_factory=list)
    refund_policy: str = ""
    allowed_promises: List[str] = field(default_factory=list)
    forbidden_promises: List[str] = field(default_factory=list)
    uncertainty_reply: str = ""
    delivery: DeliveryPolicy = field(default_factory=DeliveryPolicy)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProductRule":
        payload = dict(data)
        payload["delivery"] = DeliveryPolicy(**payload.get("delivery", {}))
        return cls(**payload)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RuleValidationResult:
    safe: bool
    violations: List[str] = field(default_factory=list)
    guardrails: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DeliveryDecision:
    ready: bool
    action: str
    reason: str
    message: str = ""
    rule_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ProductRuleStore:
    """Structured product, promise, refund, and delivery rules."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.getenv("PRODUCT_RULES_PATH", "data/product_rules.json"))
        self._loaded = False
        self.version = 1
        self.rules: List[ProductRule] = []
        self.fallback_rule = ProductRule.from_dict({
            "rule_id": "fallback",
            "title": "Fallback Rule",
            "uncertainty_reply": "这个我不能乱承诺，需要按商品说明和平台订单状态来处理。",
            "forbidden_promises": ["百分百成功", "100%成功", "官方内部渠道", "绕过平台规则", "平台外交易"],
        })

    def load(self) -> None:
        if self._loaded:
            return
        if not self.path.exists():
            self._loaded = True
            return

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.version = payload.get("version", 1)
        self.fallback_rule = ProductRule.from_dict(payload.get("fallback_rule", self.fallback_rule.to_dict()))
        self.rules = [ProductRule.from_dict(rule) for rule in payload.get("rules", [])]
        self._loaded = True

    def resolve(
        self,
        item_id: Optional[str] = None,
        item_info: Optional[Dict[str, Any]] = None,
        item_desc: str = "",
    ) -> ProductRule:
        self.load()
        item_info = item_info or self.extract_item_info(item_desc)
        title = str(item_info.get("title") or item_info.get("desc") or "")

        if item_id:
            for rule in self.rules:
                if item_id in rule.item_ids:
                    return self._with_global_forbidden_promises(rule)

        title_lower = title.lower()
        for rule in self.rules:
            if any(match_title.lower() in title_lower for match_title in rule.match_titles):
                return self._with_global_forbidden_promises(rule)

        return self.fallback_rule

    def _with_global_forbidden_promises(self, rule: ProductRule) -> ProductRule:
        forbidden = list(dict.fromkeys(
            self.fallback_rule.forbidden_promises + rule.forbidden_promises
        ))
        return replace(rule, forbidden_promises=forbidden)

    @staticmethod
    def extract_item_info(item_desc: str) -> Dict[str, Any]:
        start = item_desc.find("{")
        if start == -1:
            return {}
        try:
            payload, _ = json.JSONDecoder().raw_decode(item_desc[start:])
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}

    def build_prompt_context(self, rule: ProductRule) -> str:
        allowed = "；".join(rule.allowed_promises) or "只能基于商品详情和平台订单状态说明"
        forbidden = "；".join(rule.forbidden_promises) or "不得承诺未配置事项"
        return (
            "\n▲【商品交易规则中心】:\n"
            f"规则ID: {rule.rule_id}\n"
            f"售后/退款边界: {rule.refund_policy}\n"
            f"允许承诺: {allowed}\n"
            f"禁止承诺: {forbidden}\n"
            f"不确定时回复原则: {rule.uncertainty_reply}\n"
            f"发货规则: 类型={rule.delivery.type}, 触发条件={rule.delivery.after}, 需要人工确认={rule.delivery.requires_manual_confirm}\n"
            "回复必须遵守以上规则；没有写在规则里的成功率、资格、售后和平台外流程，一律不要承诺。"
        )

    def validate_reply(self, reply: str, rule: ProductRule) -> RuleValidationResult:
        violations = [phrase for phrase in rule.forbidden_promises if phrase and phrase in reply]
        guardrails = ["product_rule_contract"]
        if violations:
            guardrails.append("rule_forbidden_promise")
        return RuleValidationResult(safe=not violations, violations=violations, guardrails=guardrails)

    def build_safe_reply(self, rule: ProductRule, validation: RuleValidationResult) -> str:
        return (
            f"这点我按商品规则跟你说清楚：{rule.uncertainty_reply}"
            " 我不能承诺超出商品规则或平台流程的内容，能保证的是按商品说明和平台订单流程处理。"
        )

    def delivery_decision(self, item_id: str, order_status: str, item_info: Optional[Dict[str, Any]] = None) -> DeliveryDecision:
        rule = self.resolve(item_id=item_id, item_info=item_info)
        policy = rule.delivery
        if policy.after == "paid" and order_status not in PAID_ORDER_STATUSES:
            return DeliveryDecision(
                ready=False,
                action="wait_for_payment",
                reason=f"订单状态 {order_status} 未满足发货条件 {policy.after}",
                rule_id=rule.rule_id,
            )

        if policy.requires_manual_confirm:
            return DeliveryDecision(
                ready=False,
                action="manual_review",
                reason="该商品规则要求人工确认后再发货",
                message=policy.message_template,
                rule_id=rule.rule_id,
            )

        if policy.type == "digital_link":
            return DeliveryDecision(
                ready=True,
                action="auto_deliver",
                reason="订单已满足付款条件，虚拟教程商品可自动发送交付话术",
                message=policy.message_template,
                rule_id=rule.rule_id,
            )

        return DeliveryDecision(
            ready=False,
            action="unsupported_delivery_type",
            reason=f"当前发货类型 {policy.type} 暂不支持自动发货",
            rule_id=rule.rule_id,
        )
