# Big-Tech Agent Readiness

## What Big-Tech Agent Roles Tend To Ask For

Recent AI Agent / LLM application roles and production-agent engineering materials tend to probe beyond "called an LLM API":

- Agent evaluation systems and scenario-based regression sets.
- Agent harness design: routing, state, tool contracts, retries, guardrails, and approval boundaries.
- Traceability and observability across intermediate decisions, memory operations, and policy checks.
- Durable execution and idempotency for tool/action calls, so an Agent does not repeat risky side effects after retries.
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
- `core/message_aggregation.py`: input-boundary debounce layer that turns bursty platform events into one stable user turn before routing.
- `core/agent_registry.py`: extensible intent-to-handler registry with explicit fallback and runtime capability discovery.
- `core/runtime_config.py`: secret-free startup readiness checks for model credentials, Xianyu identity, prompts, and policy files.
- `core/product_rules.py`: structured product rule center for allowed promises, forbidden promises, refund boundaries, and auditable delivery decisions.
- `core/human_style.py`: configurable human-seller style guardrail that detects and rewrites robotic customer-service tone before replies reach buyers.
- `core/reply_outbox.py`: durable reply execution outbox with source-message dedupe, send claiming, sent/failed/skipped states, and retry semantics.
- `core/trace_store.py`: append-only JSONL trace store for replaying recent Agent decisions.
- `tests/test_message_aggregation.py`: deterministic state-machine tests for message batching, isolation, and force-flush behavior.
- `tests/test_product_rules.py`: rule-center tests for product matching, unpaid delivery blocking, digital auto-delivery decisions, physical manual review, and forbidden-promise interception.
- `tests/test_human_style.py`: adversarial tone test proving robotic LLM output is rewritten before being returned.
- `tests/test_reply_outbox.py`: execution tests for duplicate-send blocking and retry after failure.
- `tests/test_api.py`: API tests for health, tech routing, price guardrails, trace lookup, memory persistence, batched user input, and invalid request rejection.
- `tests/test_agent_runtime.py`: extension registration, prompt-reload persistence, model-outage fallback, cross-product fact isolation, and readiness diagnostics.
- `evals/agent_eval_cases.json`: curated golden scenarios covering product facts, lowball negotiation, serious offers, commitment consistency, and fallback chat.
- `core/evaluation.py`: deterministic offline evaluation harness with trace-aware assertions.
- `tools/run_agent_eval.py`: CLI runner that emits JSON and Markdown eval reports.
- `.github/workflows/ci.yml`: CI gate for unit tests, API tests, compile checks, readiness diagnostics, runtime smoke, agent eval pass rate, and Docker image build.

## How To Demo In An Interview

```bash
pytest tests/test_agents.py tests/test_api.py tests/test_human_style.py tests/test_reply_outbox.py -q
python main.py --mode smoke
python tools/run_agent_eval.py --min-score 1.0
$env:API_OFFLINE_MODE="true"; uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Then explain:

1. `smoke` proves the runtime path works from entrypoint to memory writes.
2. `run_agent_eval.py` proves multiple business scenarios are evaluated against expected traces and memory state.
3. `/api/reply` proves the Agent core is product-ready: typed input, trace output, memory snapshot, and deterministic testability.
4. `tests/test_reply_outbox.py` proves the side-effect path is idempotent rather than a naked send call.
5. CI makes the eval harness a quality gate rather than a one-off demo.

## Resume Upgrade Line

Built a service-oriented transaction Agent with deterministic guardrails, structured product rules, human-seller style enforcement, durable reply outbox execution, auditable delivery decisions, SQLite memory, typed FastAPI interfaces, JSONL trace replay, golden-scenario evals, and CI quality gates, measuring intent routing, RAG grounding, pricing decisions, invalid input handling, robotic-tone rewriting, duplicate-send prevention, forbidden-promise blocking, delivery readiness, and memory consistency across multi-turn workflows.
