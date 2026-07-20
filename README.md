# Falses Goofish GuardAgent

> A local-first AI customer-service and bargain-guard agent for Xianyu / Goofish.

本项目由 **falses00** 基于 [shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent) 与 [cv-cat/XianYuApis](https://github.com/cv-cat/XianYuApis) 的开源思路继续二次开发，目标不是再做一个简单自动回复脚本，而是把闲鱼客服场景里最容易失控的三件事收住：

- 买家砍价时，LLM 不能被话术诱导突破底价。
- 商品详情咨询时，LLM 不能编造配件、成色、拆修、发货信息。
- 本地演示和迭代时，不必每次都依赖真实 Cookie 和真实买家消息。

当前版本保留原项目的闲鱼 WebSocket 长连接能力，并新增本地 Mock CLI、HTTP Agent API、SQLite 价格承诺记忆、持久化人工接管、硬规则议价护栏、JSON 商品知识库、商品规则中心、真人化回复风格层、回复执行 Outbox、交付决策引擎、JSONL trace 回放和针对核心策略的自动化测试 / Agent 评测门禁。

仓库地址：[https://github.com/falses00/Falses-Goofish-GuardAgent](https://github.com/falses00/Falses-Goofish-GuardAgent)

## 为什么叫 GuardAgent

传统 AI 客服很会聊天，但在交易场景里，“会聊天”不够。它还需要守住底价、守住事实、守住平台沟通边界。

`Falses Goofish GuardAgent` 的核心思路是：

- **LLM 负责表达**：把回复写得自然、像真人卖家。
- **规则负责底线**：价格、承诺、商品事实由确定性代码控制。
- **SQLite 负责记忆**：多轮会话中记录历史报价和买家最高出价。
- **Style 负责人味**：拦截“作为 AI 客服”“感谢咨询”等机器腔，让回复更像真实个人卖家。
- **Outbox 负责执行**：真实发送前先登记并原子抢占发送权；失败重试复用原回复，避免重复调用模型和重复写记忆。
- **人工接管负责止损**：API 控制台与 Worker 共享 SQLite 接管状态，重启后仍生效；新决策和待发送回复都会被终止。
- **Trace 负责解释**：每轮回复记录路由、护栏、定价来源和知识命中。
- **本地模式负责调试**：不接入闲鱼也能复现议价和咨询链路。
- **服务接口负责集成**：通过 FastAPI 暴露 `/api/reply`，让 Agent 能接入 Web 管理台、移动端映射或后续 MCP 工具。

## 核心特性

### 1. 本地 Mock CLI 调试

```bash
python main.py --mode cli
```

无需配置闲鱼 Cookie，即可在终端模拟买家咨询和砍价。CLI 会展示意图识别、议价次数、我方历史承诺价、买家最高出价，适合演示、面试和本地策略调参。

### 2. 议价安全护栏

`core/experts.py` 中的 `BargainExpert` 会先根据原价、最低价、买家出价和历史承诺价计算安全报价，再把这个结果交给 LLM 润色。

已处理的关键边界：

- 买家没有给具体价格时，只做小幅让步。
- 买家出价低于底线时，拒绝并给出安全反报价。
- 买家出价接近我方底线时，可直接接受成交。
- 买家出价高于历史承诺价时，不再把报价抬高，避免前后矛盾。

### 3. SQLite 价格承诺记忆

`context_manager.py` 维护会话历史、议价次数、我方最低承诺价和买家最高出价。

价格记忆采用保守更新策略：

- `lowest_price_committed` 只会记录更低的我方承诺价。
- `buyer_highest_offer` 只会记录更高的买家出价。
- live 模式会按真实 `chat_id` 隔离会话，不再让不同买家共享 mock 会话状态。

### 4. JSON 商品知识库

`data/product_info.json` 保存商品标题、原价、最低价、成色、拆修、配件、发货、面交和常见问题。

当买家询问电池、成色、划痕、配件、拆修、快递、面交等问题时，`FAQExpert` 会提取相关事实并注入模型上下文，减少幻觉和售后争议。

### 5. 闲鱼 WebSocket 挂机模式

```bash
python main.py --mode xianyu
```

该模式需要 `COOKIES_STR`，用于连接闲鱼 / Goofish WebSocket 并自动处理消息。仍建议先用 CLI 模式验证商品数据、提示词和价格策略。

接入真实 Cookie 前，可先运行与 live 共用处理函数的离线回放：

```bash
python main.py --mode replay
```

`replay` 会让一条买家消息真实穿过商品上下文、Agent、SQLite 记忆和 Reply Outbox，再重复投递同一个源事件。它固定启用 dry-run，并断言只生成一轮记忆、只领取一次发送权且网络发送次数为 0。

使用真实 Agnes 模型做一轮无发送、多轮交易演示：

```bash
python main.py --mode demo
```

`demo` 使用隔离临时数据库依次运行商品疑虑、低价砍价和高风险承诺场景，输出延迟、路由 Agent、价格决策、知识来源、护栏和模型状态。它不连接闲鱼发送接口，但要求真实模型调用成功、议价不突破商品底价、记忆状态与三轮对话一致，否则以非零状态退出。

### 6. AgentTrace 可观测链路

每轮回复都会生成 `AgentTrace`，记录：

- `intent`：识别到的用户意图。
- `routed_agent`：实际处理的 Agent。
- `guardrails`：启用的护栏，例如价格底线、历史承诺不抬价、商品事实约束。
- `price_decision`：原价、底价、底价来源、买家报价、历史承诺和最终动作。
- `knowledge`：商品知识库是否命中，以及注入了哪些事实。

### 7. Agent HTTP API

```bash
$env:API_OFFLINE_MODE="true"
uvicorn api.app:app --host 127.0.0.1 --port 8000
```

服务化入口会复用同一套 `XianyuReplyBot` 决策核心，并在根路径提供本地卖家运营台。浏览器打开 `http://127.0.0.1:8000/`，可在“运营总览 / 回复试跑 / 人工接管 / 决策记录 / 运行状态”之间切换：总览聚合真实 Worker、Trace、护栏与实时活动；回复试跑安全模拟买家消息；人工接管按会话暂停自动决策并查看审计记录；决策记录按意图和状态筛选 Trace；运行状态提供心跳证据与恢复步骤。控制台的模拟回复不会调用闲鱼发送接口，默认也不会写入会话记忆。前端调研、Notion 范式与设计取舍见 [`docs/FRONTEND_RESEARCH_2026-07.md`](docs/FRONTEND_RESEARCH_2026-07.md)。

核心接口：

- `GET /health`：健康检查，并返回是否处于离线 deterministic LLM 模式。
- `GET /health/live`：进程存活探针；`GET /health/ready`：检查 Agent、存储目录和控制台资源。
- `GET /api/overview`：返回无敏感正文的 API、Worker、Agent 与 Trace 摘要。
- `GET /api/runtime-status`：返回 live worker 的原子运行快照。
- `GET /api/capabilities`：列出当前已注册的业务意图，便于管理台或 MCP 动态发现能力。
- `POST /api/reply`：输入买家消息、商品信息和会话 ID，返回回复、意图、trace 和 memory snapshot；可带 `request_id` 获得完成态请求回放保护。
- `GET /api/memory/{chat_id}`：查询指定会话的本地记忆与议价承诺。
- `GET /api/takeovers`、`GET /api/takeovers/events`：查询当前人工接管与不可变操作审计。
- `PUT /api/takeovers/{chat_id}`、`DELETE /api/takeovers/{chat_id}`：接管会话或恢复自动回复；接管最长 24 小时并自动过期。
- `GET /api/traces?limit=20&chat_id=...&intent=...`：过滤最近的 JSONL trace，便于排查和回放。

API 默认只建议绑定 `127.0.0.1`。设置 `API_ACCESS_TOKEN` 后，回复、记忆、人工接管和 Trace 接口要求 `Authorization: Bearer <token>`；控制台令牌只保存在当前标签页的 `sessionStorage`。生产环境可设置 `API_DOCS_ENABLED=false` 关闭 Swagger/ReDoc。由于决策核心仍包含兼容旧调用方的可变 Trace 状态，API 部署固定使用单 worker，由进程内锁保证请求隔离；横向扩展前应先把决策结果重构为不可变返回值。

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/reply ^
  -H "Content-Type: application/json" ^
  -d "{\"request_id\":\"demo-api-001\",\"chat_id\":\"demo_api\",\"item_id\":\"ipad\",\"user_msg\":\"3000 元能出吗\"}"
```

### 8. 连续消息聚合

真实买家经常连续发送多条短消息，例如：

```text
你好
128G 吗
3000 元能出吗
```

如果每条消息都立刻触发一次 LLM，Agent 容易答非所问、重复回复或先回答了“你好”再错过真正的报价。`core/message_aggregation.py` 会按 `chat_id + item_id + user_id` 建立聚合窗口，在短时间内把连续消息合并成一次 Agent 输入。

可配置项：

- `MESSAGE_AGGREGATION_ENABLED=true`
- `MESSAGE_AGGREGATION_WINDOW_SECONDS=1.2`
- `MESSAGE_AGGREGATION_MAX_MESSAGES=5`
- `MESSAGE_AGGREGATION_MAX_CHARS=1200`

### 9. 商品规则中心与交付决策

`data/product_rules.json` 把商品承诺边界、售后边界、禁止承诺、发货条件和交付话术结构化。LLM 可以负责自然表达，但不能绕过这些规则。

规则中心解决三类问题：

- **降低幻觉**：禁止承诺“百分百成功”“官方内部渠道”等未授权说法。
- **记住规矩**：每个商品有独立的退款、发货、允许/禁止承诺配置。
- **发货前置判断**：`delivery_decision()` 会先判断订单是否满足付款条件、是否需要人工确认，再决定能否自动交付。

### 10. 真人化回复风格层

`data/human_reply_style.json` 定义闲鱼个人卖家的回复风格：短句、口语、先回答问题、不要客服腔和机器腔。`core/human_style.py` 会在两处生效：

- 生成前：把“像真实个人卖家”的表达约束注入 system prompt。
- 生成后：确定性清洗“您好”“感谢咨询”“作为 AI 客服”“请问还有什么可以帮您”等不自然表达。

这层不是简单调高温度，而是可测试、可观测的风格护栏。每轮 `AgentTrace.style` 都会记录是否改写、触发了哪些风格问题、最终是否安全。

### 11. 回复执行 Outbox

真实闲鱼 WebSocket 同步可能因为重连、ACK、重复推送导致同一条买家消息被处理多次。`core/reply_outbox.py` 在真实发送前落库并抢占发送权：

- 同一个源消息事件同一时刻只允许一个 worker 持有发送权，已完成事件的重复投递会被抑制。
- `pending` 或 `failed` 事件恢复时直接发送已落库回复，不会再次调用 Agent；发送失败前不写助手记忆，终态恢复时按源事件幂等提交。
- SQLite 原子事务保证并发 worker 只有一个能取得发送权。
- 超时的 `sending` 记录可按 lease 重新领取，避免进程崩溃后永久卡住。
- 发送成功后标记 `sent`，重复事件直接跳过。
- 发送失败后标记 `failed`，允许后续重试。
- `REPLY_SEND_DRY_RUN=true` 时只记录不真实发送，适合接入真实 Cookie 前压测。
- Outbox 同时保存买家原文、意图和决策 Trace；`sent / dry_run` 提交完整 turn，`manual_takeover / no_reply` 只提交买家消息。
- `source_message_id` 驱动记忆幂等；极端情况下若远端发送与接管交错，用户态记忆可升级为完整已发送 turn，不会重复累计议价次数。

这里采用的是“持久化 Outbox + at-least-once 重试 + 进程内并发幂等”。闲鱼 WebSocket 发送接口没有暴露业务幂等键，因此如果消息已经到达平台、进程却在 `mark_sent` 前崩溃，恢复重试仍存在极小的重复发送窗口。生产上需要平台 ACK/幂等键或人工审计来进一步收敛，项目不会把这一点包装成不存在的 exactly-once 保证。

### 11.1 持久化人工接管

`core/manual_takeover.py` 将人工接管从 Worker 内存集合升级为 SQLite 状态机。控制台和 Worker 只要共享 `MANUAL_TAKEOVER_DB_PATH`，即可跨进程读写同一事实源：

- 控制台可按 `chat_id` 设置 15 分钟到 24 小时的接管时限、商品 ID 和原因。
- Worker 在 Agent 决策前、模型返回后、Outbox 领取前和网络发送前重复检查接管状态。
- 接管期间的新买家消息只写入用户上下文，不调用模型；待发送或失败待重试记录转为 `skipped/manual_takeover`。
- live 价格 Agent 生成阶段不写状态；完整 turn、议价次数和单调价格承诺只在 Outbox 确认 `sent` 或 dry-run 终态后由同一 SQLite 事务提交。
- 开始、延长、手动恢复和 TTL 到期都会写入审计事件；进程重启不会丢失状态。

真实发送前最后一次状态检查与远端 WebSocket 调用之间仍有极窄竞态窗口。平台没有事务式“接管 + 撤回发送”接口，因此已经进入远端调用的消息无法保证撤回；项目明确保留这一工程边界。

### 12. 可扩展 Agent 注册表与模型降级

新增业务 Agent 不需要修改 `generate_reply()` 主循环，只需实现统一的 `generate(**kwargs)` 契约并注册：

```python
shipping_agent = ShippingAgent()
bot.register_agent(
    "shipping",
    shipping_agent,
    keywords=["多久发货", "什么时候发"],
    priority=5,
)
```

注册信息会在 Prompt 热重载后保留，`GET /api/capabilities` 可发现新增意图。模型超时、空响应或调用异常时，Agent 不会让整条 WebSocket 消息处理链崩溃：默认咨询返回谨慎话术，详情咨询只引用当前商品上下文，议价回复继续使用 `BargainExpert` 算出的安全价格；`AgentTrace.model.router / responder` 会分别记录路由来源、`ok / fallback` 和错误类型。

`TechAgent` 现在严格以当前 `item_id` 对应的消息商品上下文为事实源，只有调用方没有提供结构化商品数据时才读取演示 JSON，防止不同商品之间串用 iPad 等示例参数。

### 13. API 并发边界与请求回放

FastAPI 会在工作线程中并发执行同步端点，而兼容旧调用方式的 `XianyuReplyBot` 暴露了可变的 `last_intent / last_trace`。服务层使用显式决策锁把“读取上下文 -> Agent 决策 -> 写入完整 turn -> 固化 trace”收束成一个边界，避免并发请求互相串用意图或 trace。

调用方可提供 1-128 字符的 `request_id`：

- 首次请求原子领取带 owner token 的处理租约，慢模型调用期间自动续租；完成、失败和副作用前都校验所有权，旧 owner 会被 fencing token 拒绝。
- 相同 `request_id` 和相同载荷重试时直接回放完成态响应，`idempotent_replay=true`，不会再次调用 Agent、追加记忆或写 trace。
- 相同 `request_id` 携带不同载荷返回 HTTP `409 request_id_payload_mismatch`。
- 仍在处理且持续续租的重复请求返回 HTTP `409 request_id_in_progress`；进程失败或租约真正超时后才允许新 owner 重新领取。

该机制解决正常网关重试和多 worker 同时收到重复请求的问题，但不会伪装成跨数据库 exactly-once：会话 turn 与回放记录不在同一 SQLite 事务中，进程若恰好在写入记忆后、固化完成态响应前崩溃，租约恢复仍可能重复执行。进一步收敛需要统一事务存储、上游业务幂等键或事务消息。

## 项目结构

```text
Falses-Goofish-GuardAgent/
├── PRODUCT.md                  # 操作台用户、任务、产品气质与反例
├── DESIGN.md                   # 可复用视觉 token、组件和响应式规则
├── main.py                     # 启动入口：xianyu / cli / smoke / demo / replay / doctor / status
├── XianyuAgent.py              # 意图路由、价格 Agent、详情 Agent、默认 Agent
├── XianyuApis.py               # 闲鱼 / Goofish API 与 WebSocket 封装
├── context_manager.py          # SQLite 会话历史、议价次数、价格承诺记忆
├── core/
│   ├── __init__.py
│   ├── agent_registry.py       # 可插拔 Agent 注册、解析与回退契约
│   ├── api_request_replay.py   # API 请求领取、冲突检测与完成态响应回放
│   ├── experts.py              # BargainExpert 与 FAQExpert
│   ├── human_style.py          # 真人卖家回复风格约束与机器腔清洗
│   ├── manual_takeover.py      # 跨进程人工接管状态、TTL 与审计日志
│   ├── message_aggregation.py  # 连续买家消息 debounce 聚合
│   ├── model_provider.py       # Agnes / OpenAI-compatible 模型配置
│   ├── observability.py        # AgentTrace 可观测结构
│   ├── product_rules.py        # 商品规则中心与交付决策
│   ├── reply_outbox.py         # 自动回复执行 Outbox 与重复发送防护
│   ├── runtime_config.py       # 无密钥泄露的启动就绪诊断
│   ├── evaluation.py           # 离线 LLM stub 与 Agent 评测 harness
│   └── trace_store.py          # JSONL trace 持久化与回放
├── api/
│   ├── __init__.py
│   ├── app.py                  # FastAPI Agent backend、认证与健康探针
│   └── static/                 # 本地卖家操作台 HTML / CSS / JavaScript
├── data/
│   ├── product_info.json       # 示例商品知识库
│   ├── product_rules.json      # 商品承诺、售后和发货规则
│   └── human_reply_style.json  # 真人化回复风格配置
├── evals/
│   └── agent_eval_cases.json   # 交易场景黄金评测集
├── docs/
│   ├── AGENT_DESIGN_NOTES.md
│   ├── BIG_TECH_AGENT_READINESS.md
│   └── RESUME_PROJECT_EXPERIENCE.md
├── prompts/                    # 提示词模板，正式提示词默认不入库
├── tests/
│   ├── test_agents.py          # 核心策略单元测试
│   ├── test_agent_runtime.py   # 扩展注册、模型降级与配置诊断测试
│   ├── test_message_aggregation.py # 消息聚合状态机测试
│   ├── test_manual_takeover.py # 接管持久化、跨实例可见性与 TTL 测试
│   ├── test_product_rules.py   # 规则中心与交付决策测试
│   ├── test_human_style.py     # 真人化回复风格测试
│   ├── test_reply_outbox.py    # 回复执行 Outbox 去重与重试测试
│   ├── test_api_request_replay.py # 请求回放状态机、冲突与租约测试
│   ├── test_api.py             # HTTP API、控制台、认证与失败路径测试
│   └── test_storage_hardening.py # WAL、busy timeout、跨进程 Trace 滚动与损坏恢复
├── .env.example                # 配置模板
├── requirements.txt
└── docker-compose.yml
```

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/falses00/Falses-Goofish-GuardAgent.git
cd Falses-Goofish-GuardAgent
```

### 2. 安装依赖

建议 Python 3.10+。

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
copy .env.example .env
```

最少需要填写：

```ini
MODEL_PROVIDER=agnes
AGNES_API_KEY=your_agnes_api_key_here
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
AGNES_MODEL_NAME=agnes-2.0-flash
DEFAULT_DISCOUNT_LIMIT=0.85
```

Agnes 官方文档说明其 API 兼容 OpenAI 风格接口，请求使用 `Authorization: Bearer YOUR_API_KEY`，Base URL 为 `https://apihub.agnes-ai.com/v1`，文本模型可使用 `agnes-2.0-flash`。

如果使用 Ollama、DeepSeek 或其他 OpenAI-compatible 模型，可改成：

```ini
MODEL_PROVIDER=custom
API_KEY=ollama
MODEL_BASE_URL=http://127.0.0.1:11434/v1
MODEL_NAME=qwen2.5:7b-instruct
```

### 4. 本地模拟运行

```bash
python main.py --mode cli
```

可以尝试输入：

- `在吗`
- `这个屏幕有划痕吗，电池怎么样`
- `能少点吗`
- `3000 卖不卖，我学生`
- `4100 可以我马上拍`

### 4.1 离线端到端自检

```bash
python main.py --mode smoke
```

`smoke` 模式不需要真实 Cookie 或外部 LLM API，会使用内置离线 LLM stub 真实穿过入口、意图路由、Agent、SQLite 记忆、议价护栏、商品知识库和 `AgentTrace`。它适合在提交前快速确认项目能跑通一轮完整买家咨询/砍价流程。

### 4.2 实时执行链离线回放

```bash
python main.py --mode replay
```

`replay` 不需要 Cookie 或外部 LLM API，但会调用与闲鱼挂机模式相同的 `_process_buyer_message -> ReplyOutbox -> send` 执行链。它验证 dry-run 零网络发送、同一事件重复投递不重复生成回复，并输出 Outbox 状态、领取次数和记忆条数。

### 4.3 真实 Agnes 多轮演示

```bash
python main.py --mode demo
```

`demo` 会真实调用 Agnes，但使用隔离临时会话且不连接闲鱼发送接口。它依次验证商品事实问答、低于底价的砍价和高风险承诺场景，并断言模型调用成功、价格底线未突破、SQLite 多轮记忆一致。

### 4.4 启动 Agent API

```bash
$env:API_OFFLINE_MODE="true"
uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

浏览器打开 `http://127.0.0.1:8000/` 使用卖家操作台，打开 `/docs` 调试 API。页面默认不写入本地记忆，生成的回复也不会发送到闲鱼；勾选“写入本地对话记忆”只影响 API 演示数据库。离线模式适合演示和 CI；真实模型模式默认需要配置 `AGNES_API_KEY`，也可通过 `API_KEY`、`MODEL_BASE_URL` 和 `MODEL_NAME` 接入其它 OpenAI-compatible 服务。

启动 Worker 后，在控制台打开“人工接管”，填写真实 `chat_id` 并确认即可暂停该会话。控制台与 Worker 必须使用相同的 `MANUAL_TAKEOVER_DB_PATH`；仓库默认值和 Docker Compose 的共享 `./data:/app/data` 已满足这一条件。恢复自动回复是显式高风险操作，页面会二次确认。

### 5. 闲鱼挂机运行

在 `.env` 中补充自己的 Cookie：

```ini
COOKIES_STR=your_cookies_here
```

然后启动：

```bash
python main.py --mode doctor
python main.py --mode xianyu
```

`doctor` 不调用外部网络，也不会打印密钥；它会检查模型配置、Cookie 中的 `unb`、提示词以及商品规则/风格配置。容器中默认 `NON_INTERACTIVE=true`，配置不完整时直接退出并报告缺失项，不会无限等待终端输入。

运行中若 Cookie 失效或触发滑块风控，API 层会抛出明确的认证异常。DNS、连接超时等暂态故障会进入有限重试和延迟恢复，不会被误判为 Cookie 失效；成功刷新 Token 后会清理陈旧认证错误。交互终端仍可现场更新 Cookie，非交互容器遇到确定的认证失败时停止连接，避免在风控状态下无限递归请求。

另开终端可查看实时运行状态：

```bash
python main.py --mode status
```

`status` 读取 `logs/runtime_status.json` 的原子快照，报告 `connecting / registered / reconnecting / heartbeat_timeout / auth_failed` 等状态、快照新鲜度、最近 Token/注册/心跳时间和重连退避；文件不写入 Cookie、API Key 或消息正文。状态超过 `RUNTIME_STATUS_STALE_SECONDS` 未更新时返回非零退出码，可接入进程守护和监控。

### 6. Docker 部署

```bash
docker compose build
docker compose up -d
docker compose ps
```

Compose 构建当前仓库镜像，并以非 root 用户运行两个独立服务：`guardagent` 负责真实闲鱼 WebSocket，`console` 负责单 worker FastAPI 与卖家操作台。控制台只映射到宿主机 `127.0.0.1:8000`，端口冲突时可设置 `CONSOLE_BIND_PORT`；worker 使用 `status` 检查连接与心跳，控制台使用 `/health/ready` 检查 Agent、存储和静态资源。健康检查由 Compose 按实际进程分别配置，直接覆盖镜像启动命令时应同步传入对应探针。首次部署可先从 `.env.example` 创建自己的 `.env`，Linux bind mount 需确保容器 UID `10001` 对 `data/` 与 `logs/` 有写权限。

## 自动化测试

```bash
pytest -q
python main.py --mode smoke
python main.py --mode replay
python tools/run_agent_eval.py --min-score 1.0
```

当前测试覆盖：

- 泛议价微降策略。
- 低于底线的拒绝与反报价。
- 合理区间出价的折中策略。
- 接近底线时直接成交。
- 历史承诺价不被抬高。
- 商品级 `min_price` 优先于环境折扣。
- 无效折扣配置自动回退。
- API 共享 Agent 的并发决策隔离。
- `request_id` 完成态回放、载荷冲突、owner fencing、慢请求续租、失败恢复与租约回收。
- `websockets 13.1 / 15.x` 客户端参数和重连路径兼容性。
- 规格数字不误判成买家报价。
- 原子写入一轮对话记忆，避免半轮上下文。
- 连续买家消息 debounce 聚合，避免多条短消息触发多次错误回复。
- 商品规则中心，拦截违规承诺并按订单状态判断是否可自动交付。
- 真人化回复风格层，拦截和改写机器腔、客服腔、长段落和列表式回复。
- 回复执行 Outbox，防止同一条买家事件因重连或重复同步被重复发送。
- FastAPI `/api/reply` 服务接口、memory snapshot、trace JSONL 回查与决策阶段耗时。
- 空消息等非法输入返回 422，避免脏请求进入 Agent 决策链路。
- 8 个场景 11 轮离线 Agent 评测集，覆盖意图路由、商品事实命中、混合规格与报价、护栏触发、价格决策和最终记忆状态。
- 商品知识库关键词命中。
- 当前商品事实优先，禁止跨商品串用演示知识库。
- 动态 Agent 注册、优先级路由与 Prompt 重载保留。
- 模型超时/空响应时的安全降级，以及价格护栏不失效。
- `doctor` 配置诊断和 Docker Compose 语法/镜像构建门禁。

## Agent 评测体系

本项目新增了大厂 Agent 工程岗位更看重的离线评测 harness：

- `evals/agent_eval_cases.json`：真实业务对话黄金集。
- `core/evaluation.py`：确定性 LLM stub + trace-aware 断言。
- `tools/run_agent_eval.py`：输出 JSON / Markdown 评测报告。
- `api/app.py`：服务化接口复用同一套 Agent core，方便外部系统集成和自动化验证。
- `.github/workflows/ci.yml`：CI 自动跑单测、编译、doctor、runtime smoke、agent eval gate 和当前仓库镜像构建。

评测会检查 `intent`、`routed_agent`、`guardrails`、`knowledge.matched`、`price_decision.action`、`buyer_offer`、`calculated_price`、回复包含/排除词、规则安全状态、`bargain_count`、`lowest_price_committed` 和 `buyer_highest_offer`，避免项目退化成只看最终回复的 demo。当前 golden set 为 8 个场景 11 轮；它是确定性回归门禁，不替代线上模型质量评估。

## 简历项目经历

可直接参考 [docs/RESUME_PROJECT_EXPERIENCE.md](docs/RESUME_PROJECT_EXPERIENCE.md) 和 [docs/BIG_TECH_AGENT_READINESS.md](docs/BIG_TECH_AGENT_READINESS.md)，里面包含项目描述、技术栈、简历 bullet、面试讲述版本、评测体系和大厂岗位能力映射。

如果想把本项目当成 Agent 最佳实践教学项目来学习，可以从 [docs/AGENT_BEST_PRACTICES_TUTORIAL.md](docs/AGENT_BEST_PRACTICES_TUTORIAL.md) 开始。每一课都会对应真实业务问题、代码文件、测试命令和面试讲法。

## 配置项

| 变量 | 说明 |
| --- | --- |
| `MODEL_PROVIDER` | 模型提供商，默认 `agnes`；其它 OpenAI-compatible 服务可设为 `custom` |
| `AGNES_API_KEY` | Agnes API 密钥，默认优先读取此变量 |
| `AGNES_BASE_URL` | Agnes API base URL，默认 `https://apihub.agnes-ai.com/v1` |
| `AGNES_MODEL_NAME` | Agnes 文本模型名称，默认 `agnes-2.0-flash` |
| `API_KEY` | 通用 OpenAI-compatible 模型服务密钥，兼容旧配置 |
| `MODEL_BASE_URL` | 通用模型 API base URL，兼容旧配置 |
| `MODEL_NAME` | 通用模型名称，兼容旧配置 |
| `COOKIES_STR` | 闲鱼 / Goofish 网页端 Cookie，仅 xianyu 模式需要 |
| `NON_INTERACTIVE` | 非交互启动开关；容器中为 `true`，配置缺失时 fail-fast |
| `DEFAULT_DISCOUNT_LIMIT` | 最低折扣比例，例如 `0.85` 表示最多降到 8.5 折 |
| `PRODUCT_RULES_PATH` | 商品规则中心路径，默认 `data/product_rules.json` |
| `HUMAN_REPLY_STYLE_PATH` | 真人卖家回复风格配置路径，默认 `data/human_reply_style.json` |
| `REPLY_OUTBOX_DB_PATH` | 自动回复执行 Outbox SQLite 路径，默认 `data/reply_outbox.db` |
| `REPLY_SEND_DRY_RUN` | 是否只记录 Outbox 而不真实发送，接真实 Cookie 前可设为 `true` |
| `REPLY_SEND_CLAIM_TIMEOUT_SECONDS` | `sending` 状态的租约超时，默认 300 秒；超时后允许恢复发送 |
| `MESSAGE_AGGREGATION_ENABLED` | 是否启用连续买家消息聚合，默认 `true` |
| `MESSAGE_AGGREGATION_WINDOW_SECONDS` | 聚合窗口秒数，默认 `1.2` |
| `MESSAGE_AGGREGATION_MAX_MESSAGES` | 单批最多聚合消息数，达到后立即触发 |
| `MESSAGE_AGGREGATION_MAX_CHARS` | 单批最多字符数，达到后立即触发 |
| `API_OFFLINE_MODE` | API 服务是否使用离线 deterministic LLM，演示 / CI 可设为 `true` |
| `API_CHAT_DB_PATH` | API 服务使用的 SQLite 会话数据库路径 |
| `API_ACCESS_TOKEN` | 可选 Bearer 访问令牌；设置后保护回复、记忆和 Trace 接口 |
| `API_DOCS_ENABLED` | 是否开放 Swagger/ReDoc，默认 `true` |
| `AGENT_TRACE_PATH` | API 服务写入的 JSONL trace 文件路径 |
| `AGENT_TRACE_MAX_BYTES` | 单个 Trace 文件上限，默认 10 MiB |
| `AGENT_TRACE_BACKUP_COUNT` | Trace 滚动副本数量，默认 3 |
| `SQLITE_BUSY_TIMEOUT_MS` | SQLite 锁等待时间，默认 30000 毫秒 |
| `API_REQUEST_REPLAY_DB_PATH` | API 完成态响应回放数据库，默认 `data/api_request_replay.db` |
| `API_REQUEST_REPLAY_LEASE_SECONDS` | 请求处理中租约秒数，默认 `60`；失败或超时后允许恢复 |
| `MANUAL_TAKEOVER_DB_PATH` | API 控制台与 Worker 共享的接管 SQLite，默认 `data/manual_takeovers.db` |
| `MANUAL_MODE_TIMEOUT` | 卖家消息命令触发接管时的默认 TTL，默认 `3600` 秒 |
| `RUNTIME_STATUS_PATH` | live worker 无密钥状态快照路径，默认 `logs/runtime_status.json` |
| `RUNTIME_STATUS_STALE_SECONDS` | 状态快照陈旧阈值，默认 `45` 秒 |
| `TOGGLE_KEYWORDS` | 人工接管精确切换命令，多个命令用逗号分隔，默认 `。` |
| `SIMULATE_HUMAN_TYPING` | 是否模拟真人输入延迟 |
| `LOG_LEVEL` | 日志级别 |

## 二开参考方向

这次改造吸收了同类项目的几个方向，但保持当前仓库轻量：

- `xianyu-auto-reply` 类项目的多账号、自动发货和人工接管队列思路，可作为现有卖家操作台的后续扩展方向。
- 本地控制台类项目的商品专属策略、Ollama 兼容、本地长期托管思路。
- `XianyuBot` 类项目的分层架构、多专家协同和 RAG 规划。
- `XianYuApis` 的闲鱼 API / WebSocket 底座思路。

本仓库当前优先把“报价安全、事实准确、本地可调试”做稳，再逐步扩展 UI、自动发货、多账号和统计分析。

## 合规与风险

- 本项目不是闲鱼 / Goofish 官方项目，也不是官方 API。
- 仅用于学习、研究和自有账号的自动化辅助。
- Cookie、API Key、聊天数据库和私有提示词不要提交到公开仓库。
- 自动回复可能造成交易承诺，请在真实运行前充分测试并保留人工接管能力。
- 请遵守平台规则、法律法规和所在地区的合规要求。

## 致谢

- [shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent)：原始 AI 闲鱼客服项目与多专家思路。
- [cv-cat/XianYuApis](https://github.com/cv-cat/XianYuApis)：闲鱼接口和 WebSocket 技术参考。
- Python、OpenAI SDK、websockets、loguru、python-dotenv、rich、pytest 等开源生态。

## License

本项目沿用上游仓库的 GPL-3.0 协议。详见 [LICENSE](./LICENSE)。
