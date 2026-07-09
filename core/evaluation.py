import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from XianyuAgent import XianyuReplyBot


class DeterministicCompletions:
    """Offline LLM stub for reproducible agent evaluation."""

    def create(self, model, messages, temperature=0.4, max_tokens=500, top_p=0.8):
        system_prompt = messages[0]["content"]
        user_msg = messages[-1]["content"]

        if self._is_classifier_prompt(system_prompt):
            content = self._classify(user_msg)
        else:
            price_match = re.search(r"最终报价是: 【([0-9.]+)】", system_prompt)
            if price_match:
                price = price_match.group(1)
                content = f"这个价我认真算过了，最低只能到 {price} 元，再低就真的不合适了。"
            elif "商品知识库真实参数" in system_prompt:
                content = "这台我按实说：屏幕贴膜使用无划痕，电池健康 93%，配件和发货信息都按商品说明来。"
            else:
                content = f"收到，你问的是“{user_msg}”。我这边可以继续帮你确认商品细节。"

        return type("EvalResponse", (), {
            "choices": [type("EvalChoice", (), {
                "message": type("EvalMessage", (), {"content": content})()
            })()]
        })()

    @staticmethod
    def _is_classifier_prompt(system_prompt: str) -> bool:
        return "classify" in system_prompt.lower() or ("意图" in system_prompt and "分类" in system_prompt)

    @staticmethod
    def _classify(user_msg: str) -> str:
        if any(word in user_msg for word in ["价格", "便宜", "少点", "元", "可以", "拍"]):
            return "price"
        if any(word in user_msg for word in ["电池", "划痕", "成色", "配件", "拆修"]):
            return "tech"
        return "default"


class DeterministicChat:
    def __init__(self):
        self.completions = DeterministicCompletions()


class DeterministicLLMClient:
    def __init__(self):
        self.chat = DeterministicChat()


@dataclass
class TurnEvalResult:
    case_id: str
    turn_index: int
    user: str
    passed: bool
    failures: List[str] = field(default_factory=list)
    reply: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseEvalResult:
    case_id: str
    passed: bool
    failures: List[str] = field(default_factory=list)
    turns: List[TurnEvalResult] = field(default_factory=list)
    final_snapshot: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalSummary:
    total_cases: int
    passed_cases: int
    total_turns: int
    passed_turns: int
    case_pass_rate: float
    turn_pass_rate: float
    cases: List[CaseEvalResult]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AgentEvaluator:
    def __init__(self, cases_path: str, db_path: str, product_info_path: str = "data/product_info.json"):
        self.cases_path = Path(cases_path)
        self.db_path = db_path
        self.product_info_path = Path(product_info_path)
        self.cases = json.loads(self.cases_path.read_text(encoding="utf-8"))

    def run(self) -> EvalSummary:
        case_results = [self._run_case(case) for case in self.cases]
        total_cases = len(case_results)
        passed_cases = sum(1 for case in case_results if case.passed)
        all_turns = [turn for case in case_results for turn in case.turns]
        total_turns = len(all_turns)
        passed_turns = sum(1 for turn in all_turns if turn.passed)
        return EvalSummary(
            total_cases=total_cases,
            passed_cases=passed_cases,
            total_turns=total_turns,
            passed_turns=passed_turns,
            case_pass_rate=passed_cases / total_cases if total_cases else 0.0,
            turn_pass_rate=passed_turns / total_turns if total_turns else 0.0,
            cases=case_results,
        )

    def _run_case(self, case: Dict[str, Any]) -> CaseEvalResult:
        case_id = case["id"]
        chat_id = f"eval_{case_id}"
        item_id = case.get("item_id", "eval_item")
        bot = XianyuReplyBot(client=DeterministicLLMClient(), db_path=self.db_path)
        bot.db.reset_chat_state(chat_id)
        item_description = self._build_item_description()

        turn_results = []
        for index, turn in enumerate(case["turns"]):
            context = bot.db.get_context_by_chat(chat_id)
            reply = bot.generate_reply(turn["user"], item_description, context=context, chat_id=chat_id)
            bot.db.append_turn(
                chat_id=chat_id,
                user_id="eval_buyer",
                item_id=item_id,
                user_text=turn["user"],
                assistant_id="eval_seller",
                assistant_text=None if reply == "-" else reply,
                intent=bot.last_intent,
            )
            trace = bot.last_trace.to_dict()
            turn_results.append(self._evaluate_turn(case_id, index, turn, reply, trace))

        snapshot = bot.db.get_memory_snapshot(chat_id)
        final_snapshot = {
            "messages": len(snapshot.messages),
            "bargain_count": snapshot.bargain_count,
            "lowest_price_committed": snapshot.lowest_price_committed,
            "buyer_highest_offer": snapshot.buyer_highest_offer,
        }
        failures = self._evaluate_final(case.get("final_expect", {}), final_snapshot)
        return CaseEvalResult(
            case_id=case_id,
            passed=all(turn.passed for turn in turn_results) and not failures,
            failures=failures,
            turns=turn_results,
            final_snapshot=final_snapshot,
        )

    def _build_item_description(self) -> str:
        product_info = json.loads(self.product_info_path.read_text(encoding="utf-8"))
        return (
            f"当前商品的信息如下：标题:{product_info.get('title')} "
            f"价格:{product_info.get('original_price')}元 详情: {json.dumps(product_info, ensure_ascii=False)}"
        )

    @staticmethod
    def _evaluate_turn(case_id: str, index: int, turn: Dict[str, Any], reply: str, trace: Dict[str, Any]) -> TurnEvalResult:
        failures = []
        expect = turn.get("expect", {})

        expected_intent = expect.get("intent")
        if expected_intent and trace.get("intent") != expected_intent:
            failures.append(f"intent expected {expected_intent}, got {trace.get('intent')}")

        expected_agent = expect.get("routed_agent")
        if expected_agent and trace.get("routed_agent") != expected_agent:
            failures.append(f"routed_agent expected {expected_agent}, got {trace.get('routed_agent')}")

        for guardrail in expect.get("guardrails_contains", []):
            if guardrail not in trace.get("guardrails", []):
                failures.append(f"missing guardrail {guardrail}")

        knowledge = trace.get("knowledge", {})
        if "knowledge_matched" in expect and knowledge.get("matched") is not expect["knowledge_matched"]:
            failures.append(f"knowledge matched expected {expect['knowledge_matched']}, got {knowledge.get('matched')}")

        price_decision = trace.get("price_decision", {})
        expected_action = expect.get("price_action")
        if expected_action and price_decision.get("action") != expected_action:
            failures.append(f"price action expected {expected_action}, got {price_decision.get('action')}")

        if "buyer_offer" in expect and price_decision.get("buyer_offer") != expect["buyer_offer"]:
            failures.append(f"buyer_offer expected {expect['buyer_offer']}, got {price_decision.get('buyer_offer')}")

        if "calculated_price" in expect and price_decision.get("calculated_price") != expect["calculated_price"]:
            failures.append(
                f"calculated_price expected {expect['calculated_price']}, got {price_decision.get('calculated_price')}"
            )

        if expect.get("never_below_min_price"):
            calculated_price = price_decision.get("calculated_price")
            min_price = price_decision.get("min_price")
            if calculated_price is not None and min_price is not None and calculated_price < min_price:
                failures.append(f"calculated_price {calculated_price} below min_price {min_price}")

        return TurnEvalResult(
            case_id=case_id,
            turn_index=index,
            user=turn["user"],
            passed=not failures,
            failures=failures,
            reply=reply,
            trace=trace,
        )

    @staticmethod
    def _evaluate_final(expect: Dict[str, Any], snapshot: Dict[str, Any]) -> List[str]:
        failures = []
        for field_name, expected in expect.items():
            actual = snapshot.get(field_name)
            if actual != expected:
                failures.append(f"final {field_name} expected {expected}, got {actual}")
        return failures


def write_markdown_report(summary: EvalSummary, output_path: str) -> None:
    lines = [
        "# Agent Eval Report",
        "",
        f"- Case pass rate: {summary.case_pass_rate:.2%} ({summary.passed_cases}/{summary.total_cases})",
        f"- Turn pass rate: {summary.turn_pass_rate:.2%} ({summary.passed_turns}/{summary.total_turns})",
        "",
        "| Case | Passed | Final Snapshot | Failures |",
        "| --- | --- | --- | --- |",
    ]
    for case in summary.cases:
        failures = "; ".join(case.failures) if case.failures else ""
        lines.append(
            f"| {case.case_id} | {case.passed} | `{json.dumps(case.final_snapshot, ensure_ascii=False)}` | {failures} |"
        )
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
