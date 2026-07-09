import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.evaluation import AgentEvaluator, write_markdown_report


def main():
    parser = argparse.ArgumentParser(description="Run deterministic agent evaluation cases.")
    parser.add_argument("--cases", default="evals/agent_eval_cases.json")
    parser.add_argument("--db-path", default="data/eval_chat_history.db")
    parser.add_argument("--output-json", default="output/agent_eval_report.json")
    parser.add_argument("--output-md", default="output/agent_eval_report.md")
    parser.add_argument("--min-score", type=float, default=1.0)
    args = parser.parse_args()

    evaluator = AgentEvaluator(cases_path=args.cases, db_path=args.db_path)
    summary = evaluator.run()

    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_markdown_report(summary, args.output_md)

    print(json.dumps({
        "case_pass_rate": summary.case_pass_rate,
        "turn_pass_rate": summary.turn_pass_rate,
        "passed_cases": summary.passed_cases,
        "total_cases": summary.total_cases,
        "passed_turns": summary.passed_turns,
        "total_turns": summary.total_turns,
        "output_json": args.output_json,
        "output_md": args.output_md,
    }, ensure_ascii=False))

    if summary.case_pass_rate < args.min_score or summary.turn_pass_rate < args.min_score:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
