# Falses Goofish GuardAgent

> A local-first AI customer-service and bargain-guard agent for Xianyu / Goofish.

本项目由 **falses00** 基于 [shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent) 与 [cv-cat/XianYuApis](https://github.com/cv-cat/XianYuApis) 的开源思路继续二次开发，目标不是再做一个简单自动回复脚本，而是把闲鱼客服场景里最容易失控的三件事收住：

- 买家砍价时，LLM 不能被话术诱导突破底价。
- 商品详情咨询时，LLM 不能编造配件、成色、拆修、发货信息。
- 本地演示和迭代时，不必每次都依赖真实 Cookie 和真实买家消息。

当前版本保留原项目的闲鱼 WebSocket 长连接能力，并新增本地 Mock CLI、HTTP Agent API、SQLite 价格承诺记忆、硬规则议价护栏、JSON 商品知识库、JSONL trace 回放和针对核心策略的自动化测试 / Agent 评测门禁。

仓库地址：[https://github.com/falses00/Falses-Goofish-GuardAgent](https://github.com/falses00/Falses-Goofish-GuardAgent)

## 为什么叫 GuardAgent

传统 AI 客服很会聊天，但在交易场景里，“会聊天”不够。它还需要守住底价、守住事实、守住平台沟通边界。

`Falses Goofish GuardAgent` 的核心思路是：

- **LLM 负责表达**：把回复写得自然、像真人卖家。
- **规则负责底线**：价格、承诺、商品事实由确定性代码控制。
- **SQLite 负责记忆**：多轮会话中记录历史报价和买家最高出价。
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

服务化入口会复用同一套 `XianyuReplyBot` 决策核心，适合做后台管理台、移动端自动化桥接、外部评测器或 MCP server 的上游能力。

核心接口：

- `GET /health`：健康检查，并返回是否处于离线 deterministic LLM 模式。
- `POST /api/reply`：输入买家消息、商品信息和会话 ID，返回回复、意图、trace 和 memory snapshot。
- `GET /api/traces?limit=20`：读取最近的 JSONL trace，便于排查和回放。

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/reply ^
  -H "Content-Type: application/json" ^
  -d "{\"chat_id\":\"demo_api\",\"item_id\":\"ipad\",\"user_msg\":\"3000 元能出吗\"}"
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

## 项目结构

```text
Falses-Goofish-GuardAgent/
├── main.py                     # 启动入口：xianyu / cli 两种模式
├── XianyuAgent.py              # 意图路由、价格 Agent、详情 Agent、默认 Agent
├── XianyuApis.py               # 闲鱼 / Goofish API 与 WebSocket 封装
├── context_manager.py          # SQLite 会话历史、议价次数、价格承诺记忆
├── core/
│   ├── __init__.py
│   ├── experts.py              # BargainExpert 与 FAQExpert
│   ├── message_aggregation.py  # 连续买家消息 debounce 聚合
│   ├── model_provider.py       # Agnes / OpenAI-compatible 模型配置
│   ├── observability.py        # AgentTrace 可观测结构
│   ├── evaluation.py           # 离线 LLM stub 与 Agent 评测 harness
│   └── trace_store.py          # JSONL trace 持久化与回放
├── api/
│   ├── __init__.py
│   └── app.py                  # FastAPI Agent backend
├── data/
│   └── product_info.json       # 示例商品知识库
├── evals/
│   └── agent_eval_cases.json   # 交易场景黄金评测集
├── docs/
│   ├── AGENT_DESIGN_NOTES.md
│   ├── BIG_TECH_AGENT_READINESS.md
│   └── RESUME_PROJECT_EXPERIENCE.md
├── prompts/                    # 提示词模板，正式提示词默认不入库
├── tests/
│   ├── test_agents.py          # 核心策略单元测试
│   ├── test_message_aggregation.py # 消息聚合状态机测试
│   └── test_api.py             # HTTP API 与失败路径测试
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

### 4.2 启动 Agent API

```bash
$env:API_OFFLINE_MODE="true"
uvicorn api.app:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000/docs` 可以直接调试接口。离线模式适合演示和 CI；真实模型模式默认需要配置 `AGNES_API_KEY`，也可通过 `API_KEY`、`MODEL_BASE_URL` 和 `MODEL_NAME` 接入其它 OpenAI-compatible 服务。

### 5. 闲鱼挂机运行

在 `.env` 中补充自己的 Cookie：

```ini
COOKIES_STR=your_cookies_here
```

然后启动：

```bash
python main.py --mode xianyu
```

## 自动化测试

```bash
pytest tests/test_agents.py tests/test_message_aggregation.py tests/test_api.py -q
python main.py --mode smoke
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
- 规格数字不误判成买家报价。
- 原子写入一轮对话记忆，避免半轮上下文。
- 连续买家消息 debounce 聚合，避免多条短消息触发多次错误回复。
- FastAPI `/api/reply` 服务接口、memory snapshot、trace JSONL 回查。
- 空消息等非法输入返回 422，避免脏请求进入 Agent 决策链路。
- 离线 Agent 评测集，覆盖意图路由、RAG 命中、护栏触发、价格决策和最终记忆状态。
- 商品知识库关键词命中。

## Agent 评测体系

本项目新增了大厂 Agent 工程岗位更看重的离线评测 harness：

- `evals/agent_eval_cases.json`：真实业务对话黄金集。
- `core/evaluation.py`：确定性 LLM stub + trace-aware 断言。
- `tools/run_agent_eval.py`：输出 JSON / Markdown 评测报告。
- `api/app.py`：服务化接口复用同一套 Agent core，方便外部系统集成和自动化验证。
- `.github/workflows/ci.yml`：CI 自动跑单测、编译、runtime smoke 和 agent eval gate。

评测会检查 `intent`、`routed_agent`、`guardrails`、`knowledge.matched`、`price_decision.action`、`buyer_offer`、`calculated_price`、`bargain_count`、`lowest_price_committed` 和 `buyer_highest_offer`，避免项目退化成只看最终回复的 demo。

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
| `DEFAULT_DISCOUNT_LIMIT` | 最低折扣比例，例如 `0.85` 表示最多降到 8.5 折 |
| `MESSAGE_AGGREGATION_ENABLED` | 是否启用连续买家消息聚合，默认 `true` |
| `MESSAGE_AGGREGATION_WINDOW_SECONDS` | 聚合窗口秒数，默认 `1.2` |
| `MESSAGE_AGGREGATION_MAX_MESSAGES` | 单批最多聚合消息数，达到后立即触发 |
| `MESSAGE_AGGREGATION_MAX_CHARS` | 单批最多字符数，达到后立即触发 |
| `API_OFFLINE_MODE` | API 服务是否使用离线 deterministic LLM，演示 / CI 可设为 `true` |
| `API_CHAT_DB_PATH` | API 服务使用的 SQLite 会话数据库路径 |
| `AGENT_TRACE_PATH` | API 服务写入的 JSONL trace 文件路径 |
| `TOGGLE_KEYWORDS` | 人工接管切换关键词，默认 `。` |
| `SIMULATE_HUMAN_TYPING` | 是否模拟真人输入延迟 |
| `LOG_LEVEL` | 日志级别 |

## 二开参考方向

这次改造吸收了同类项目的几个方向，但保持当前仓库轻量：

- `xianyu-auto-reply` 类项目的多账号、自动发货、后台监控思路，后续可作为 Web 管理后台方向。
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
