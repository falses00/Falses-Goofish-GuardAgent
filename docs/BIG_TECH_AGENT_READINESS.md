# Big-Tech Agent Readiness

## What Big-Tech Agent Roles Tend To Ask For

Recent AI Agent / LLM application roles and production-agent engineering materials tend to probe beyond "called an LLM API":

- Agent evaluation systems and scenario-based regression sets.
- Agent harness design: routing, state, tool contracts, retries, guardrails, and approval boundaries.
- Traceability and observability across intermediate decisions, memory operations, and policy checks.
- Backend fundamentals: Python/Go, database state, CI, tests, service design, and operational thinking.
- Domain abstraction: turning real business workflows into reliable eval cases and measurable metrics.

## Project Gap Before This Upgrade

The project already had routing, SQLite memory, trace logging, smoke mode, and deterministic pricing guardrails. The missing piece was a formal evaluation harness:

- No golden dataset for business scenarios.
- No numeric pass-rate metric.
- No CI gate proving regression safety.
- No report artifact explaining which scenario failed and why.

## Added To Reach Interview-Grade Engineering Depth

- `evals/agent_eval_cases.json`: curated golden scenarios covering product facts, lowball negotiation, serious offers, commitment consistency, and fallback chat.
- `core/evaluation.py`: deterministic offline evaluation harness with trace-aware assertions.
- `tools/run_agent_eval.py`: CLI runner that emits JSON and Markdown eval reports.
- `.github/workflows/ci.yml`: CI gate for unit tests, compile checks, runtime smoke, and agent eval pass rate.

## How To Demo In An Interview

```bash
pytest tests/test_agents.py -q
python main.py --mode smoke
python tools/run_agent_eval.py --min-score 1.0
```

Then explain:

1. `smoke` proves the runtime path works from entrypoint to memory writes.
2. `run_agent_eval.py` proves multiple business scenarios are evaluated against expected traces and memory state.
3. CI makes the eval harness a quality gate rather than a one-off demo.

## Resume Upgrade Line

Built a deterministic Agent evaluation harness with golden business scenarios, trace-level assertions, and CI quality gates, measuring intent routing, guardrail activation, RAG grounding, pricing decisions, and memory consistency across multi-turn transaction workflows.
