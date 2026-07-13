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

- ByteDance's current AI Search role asks for planning, memory, tool use, multi-turn understanding, RAG pipeline optimization, Python/C++, and end-to-end production delivery: https://joinbytedance.com/search/7611471155291343109
- DeepSeek's current careers page separately recruits for Agent Backend, Agent Harness, and Agent Infra, reinforcing that production Agent work is evaluated as systems engineering rather than prompt writing alone: https://talent.deepseek.com/
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
- `api/static/`: dependency-free seller console for runtime health, safe simulation, explainable decisions, memory inspection, and trace drill-down across desktop and mobile layouts.
- `core/message_aggregation.py`: input-boundary debounce layer that turns bursty platform events into one stable user turn before routing.
- `core/agent_registry.py`: extensible intent-to-handler registry with explicit fallback and runtime capability discovery.
- `core/api_request_replay.py`: durable request claims, owner-token fencing, lease keepalive for slow model calls, payload-conflict detection, failure recovery, and completed-response replay.
- `core/runtime_config.py`: secret-free startup readiness checks for model credentials, Xianyu identity, prompts, and policy files.
- `core/runtime_status.py`: atomic secret-free live-worker status snapshots with stale-process detection for operators and supervisors.
- `core/product_rules.py`: structured product rule center for allowed promises, forbidden promises, refund boundaries, and auditable delivery decisions.
- `core/human_style.py`: configurable human-seller style guardrail that detects and rewrites robotic customer-service tone before replies reach buyers.
- `core/reply_outbox.py`: durable reply execution outbox with source-message dedupe, send claiming, sent/failed/skipped states, and retry semantics.
- `core/trace_store.py`: append-only JSONL trace store for replaying recent Agent decisions.
- `context_manager.py` and `core/trace_store.py`: SQLite WAL/busy-timeout hardening plus bounded cross-process-locked trace rotation for long-running operation.
- `tests/test_message_aggregation.py`: deterministic state-machine tests for message batching, isolation, and force-flush behavior.
- `tests/test_product_rules.py`: rule-center tests for product matching, unpaid delivery blocking, digital auto-delivery decisions, physical manual review, and forbidden-promise interception.
- `tests/test_human_style.py`: adversarial tone test proving robotic LLM output is rewritten before being returned.
- `tests/test_reply_outbox.py`: execution tests for duplicate-send blocking and retry after failure.
- `tests/test_api.py`: API tests for health, routing, price guardrails, trace lookup, memory persistence, batched input, concurrent trace isolation, completed-response replay, request conflicts, and invalid input.
- `tests/test_api_request_replay.py`: state-machine tests for completed replay, payload conflicts, in-progress blocking, stale-owner fencing, lease reclaim, and failed-request recovery.
- `tests/test_agent_runtime.py`: extension registration, prompt-reload persistence, model-outage fallback, cross-product fact isolation, and readiness diagnostics.
- `tests/test_storage_hardening.py`: concurrent SQLite writes, trace rotation, malformed-tail recovery, and invalid retention configuration.
- `evals/agent_eval_cases.json`: eight curated golden scenarios / eleven turns covering product facts, mixed specification-and-offer routing, lowball negotiation, commitment consistency, off-platform contact, and forbidden-promise rewriting.
- `core/evaluation.py`: deterministic offline evaluation harness with trace-aware assertions.
- `tools/run_agent_eval.py`: CLI runner that emits JSON and Markdown eval reports.
- `.github/workflows/ci.yml`: CI gate for unit tests, API tests, compile checks, readiness diagnostics, runtime smoke, agent eval pass rate, and Docker image build.
- Live WebSocket recovery uses business-heartbeat-triggered close plus bounded exponential backoff and jitter, avoiding half-open connections and retry storms after sleep or network loss.
- Blocking requests/OpenAI-compatible SDK calls run via `asyncio.to_thread`; separate async locks preserve Session and mutable Agent trace consistency without starving heartbeat or message-consumer tasks.
- FastAPI serializes access to the legacy mutable decision object and supports durable `request_id` replay with lease renewal and owner fencing, preventing gateway retries or slow-call lease expiry from repeating Agent calls, trace writes, or memory turns.
- Agent traces expose policy-context, routing, generation, guardrail/style, and total latency so interview demos can diagnose slow stages instead of showing only final text.
- Optional Bearer authentication, request IDs, strict input limits, security headers, live/ready probes, and loopback-only Compose exposure make the operator surface safe by default for a local deployment.
- Docker liveness reads the worker's atomic `status` snapshot instead of launching an unrelated configuration check that could pass while the live loop is stale; the image runs as UID `10001` and CI performs a real container HTTP smoke test.
- The current gate is 92 pytest cases plus an 8-scenario / 11-turn deterministic golden set; adversarial checks include a 2.2-second request crossing a 1-second lease and two-process trace rotation, while browser checks cover a full reply flow, 401 recovery, no-persist semantics, responsive overflow, touch targets, and contrast.

## How To Demo In An Interview

```bash
pytest tests/test_agents.py tests/test_api.py tests/test_api_request_replay.py tests/test_human_style.py tests/test_reply_outbox.py -q
python main.py --mode smoke
python tools/run_agent_eval.py --min-score 1.0
$env:API_OFFLINE_MODE="true"; uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` to demonstrate the operator console. Keep `persist_turn` disabled for the first walkthrough so the demo proves that simulation does not mutate chat or price memory; decision Trace is still retained for audit.

Then explain:

1. `smoke` proves the runtime path works from entrypoint to memory writes.
2. `run_agent_eval.py` proves multiple business scenarios are evaluated against expected traces and memory state.
3. `/api/reply` proves the Agent core is product-ready: typed input, trace output, memory snapshot, and deterministic testability.
4. `tests/test_reply_outbox.py` proves the side-effect path is idempotent rather than a naked send call.
5. CI makes the eval harness a quality gate rather than a one-off demo.
6. Repeating `/api/reply` with the same `request_id` proves completed-response replay without duplicate memory; changing the payload proves conflict detection.

## Explicit Boundaries

- The service lock protects one Python process because the legacy Agent exposes mutable `last_trace / last_intent`; horizontal workers rely on SQLite request claims to reject duplicate in-flight IDs.
- API response replay and chat-memory persistence are separate SQLite transactions. A crash in the narrow window after memory commit and before replay completion can still lead to re-execution after lease expiry. The project documents this instead of claiming cross-database exactly-once.
- Deterministic CI evals prove routing, policy, state, and regression behavior. They do not substitute for online model-quality evaluation, so `demo` remains an optional real-provider gate.
- The product-fact lookup is structured keyword retrieval, not an embedding/vector/reranking pipeline. This project supports Agent application/backend roles; a RAG-specific application should pair it with the separate Hybrid RAG project rather than relabeling this module.

## Resume Upgrade Line

Built a service-oriented transaction Agent with deterministic guardrails, structured product rules, human-seller style enforcement, durable reply outbox execution, auditable delivery decisions, SQLite memory, typed FastAPI interfaces, JSONL trace replay, golden-scenario evals, and CI quality gates, measuring intent routing, RAG grounding, pricing decisions, invalid input handling, robotic-tone rewriting, duplicate-send prevention, forbidden-promise blocking, delivery readiness, and memory consistency across multi-turn workflows.
