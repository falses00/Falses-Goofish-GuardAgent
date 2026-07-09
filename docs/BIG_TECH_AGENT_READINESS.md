# Big-Tech Agent Readiness

## What Big-Tech Agent Roles Tend To Ask For

Recent AI Agent / LLM application roles and production-agent engineering materials tend to probe beyond "called an LLM API":

- Agent evaluation systems and scenario-based regression sets.
- Agent harness design: routing, state, tool contracts, retries, guardrails, and approval boundaries.
- Traceability and observability across intermediate decisions, memory operations, and policy checks.
- Service interfaces with typed request / response contracts, so the Agent can be integrated into real products rather than only run as a script.
- Backend fundamentals: Python/Go, database state, CI, tests, service design, and operational thinking.
- Domain abstraction: turning real business workflows into reliable eval cases and measurable metrics.

The July 2026 source check maps to this direction:

- OpenAI Agents SDK docs describe agents as apps that plan, call tools, collaborate across specialists, keep state, and use traces before evaluation loops: https://developers.openai.com/api/docs/guides/agents
- MCP tool specifications emphasize explicit tool schemas and human-in-the-loop confirmation for risky tool calls: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- LangGraph positions production agents around durable execution, human-in-the-loop, memory, persistence, debugging, and deployment: https://github.com/langchain-ai/langgraph
- FastAPI's `TestClient` supports API tests without opening a real socket, which is useful for deterministic CI: https://fastapi.tiangolo.com/reference/testclient/

## Project Gap Before This Upgrade

The project already had routing, SQLite memory, trace logging, smoke mode, deterministic pricing guardrails, and an evaluation harness. The remaining gap was productization:

- The Agent core could only be reached through CLI or live Xianyu WebSocket.
- Trace data was logged but not exposed as a reusable replay surface.
- There was no typed service contract for Web UI, mobile automation bridge, MCP server, or external evaluator integration.
- API-level invalid input behavior was not tested.

## Added To Reach Interview-Grade Engineering Depth

- `api/app.py`: FastAPI service wrapper around the same `XianyuReplyBot` core with typed request / response models.
- `core/trace_store.py`: append-only JSONL trace store for replaying recent Agent decisions.
- `tests/test_api.py`: API tests for health, tech routing, price guardrails, trace lookup, memory persistence, and invalid request rejection.
- `evals/agent_eval_cases.json`: curated golden scenarios covering product facts, lowball negotiation, serious offers, commitment consistency, and fallback chat.
- `core/evaluation.py`: deterministic offline evaluation harness with trace-aware assertions.
- `tools/run_agent_eval.py`: CLI runner that emits JSON and Markdown eval reports.
- `.github/workflows/ci.yml`: CI gate for unit tests, API tests, compile checks, runtime smoke, and agent eval pass rate.

## How To Demo In An Interview

```bash
pytest tests/test_agents.py tests/test_api.py -q
python main.py --mode smoke
python tools/run_agent_eval.py --min-score 1.0
$env:API_OFFLINE_MODE="true"; uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Then explain:

1. `smoke` proves the runtime path works from entrypoint to memory writes.
2. `run_agent_eval.py` proves multiple business scenarios are evaluated against expected traces and memory state.
3. `/api/reply` proves the Agent core is product-ready: typed input, trace output, memory snapshot, and deterministic testability.
4. CI makes the eval harness a quality gate rather than a one-off demo.

## Resume Upgrade Line

Built a service-oriented transaction Agent with deterministic guardrails, SQLite memory, typed FastAPI interfaces, JSONL trace replay, golden-scenario evals, and CI quality gates, measuring intent routing, RAG grounding, pricing decisions, invalid input handling, and memory consistency across multi-turn workflows.
