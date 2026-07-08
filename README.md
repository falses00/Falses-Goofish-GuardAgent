# Falses Goofish GuardAgent

> A local-first AI customer-service and bargain-guard agent for Xianyu / Goofish.

本项目由 **falses00** 基于 [shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent) 与 [cv-cat/XianYuApis](https://github.com/cv-cat/XianYuApis) 的开源思路继续二次开发，目标不是再做一个简单自动回复脚本，而是把闲鱼客服场景里最容易失控的三件事收住：

- 买家砍价时，LLM 不能被话术诱导突破底价。
- 商品详情咨询时，LLM 不能编造配件、成色、拆修、发货信息。
- 本地演示和迭代时，不必每次都依赖真实 Cookie 和真实买家消息。

当前版本保留原项目的闲鱼 WebSocket 长连接能力，并新增本地 Mock CLI、SQLite 价格承诺记忆、硬规则议价护栏、JSON 商品知识库和针对核心策略的自动化测试。

仓库地址：[https://github.com/falses00/XianyuAutoAgent](https://github.com/falses00/XianyuAutoAgent)

## 为什么叫 GuardAgent

传统 AI 客服很会聊天，但在交易场景里，“会聊天”不够。它还需要守住底价、守住事实、守住平台沟通边界。

`Falses Goofish GuardAgent` 的核心思路是：

- **LLM 负责表达**：把回复写得自然、像真人卖家。
- **规则负责底线**：价格、承诺、商品事实由确定性代码控制。
- **SQLite 负责记忆**：多轮会话中记录历史报价和买家最高出价。
- **Trace 负责解释**：每轮回复记录路由、护栏、定价来源和知识命中。
- **本地模式负责调试**：不接入闲鱼也能复现议价和咨询链路。

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

## 项目结构

```text
XianyuAutoAgent/
├── main.py                     # 启动入口：xianyu / cli 两种模式
├── XianyuAgent.py              # 意图路由、价格 Agent、详情 Agent、默认 Agent
├── XianyuApis.py               # 闲鱼 / Goofish API 与 WebSocket 封装
├── context_manager.py          # SQLite 会话历史、议价次数、价格承诺记忆
├── core/
│   ├── __init__.py
│   ├── experts.py              # BargainExpert 与 FAQExpert
│   └── observability.py        # AgentTrace 可观测结构
├── data/
│   └── product_info.json       # 示例商品知识库
├── docs/
│   ├── AGENT_DESIGN_NOTES.md
│   └── RESUME_PROJECT_EXPERIENCE.md
├── prompts/                    # 提示词模板，正式提示词默认不入库
├── tests/
│   └── test_agents.py          # 核心策略单元测试
├── .env.example                # 配置模板
├── requirements.txt
└── docker-compose.yml
```

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/falses00/XianyuAutoAgent.git
cd XianyuAutoAgent
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
API_KEY=your_api_key_here
MODEL_BASE_URL=https://api.deepseek.com/v1
MODEL_NAME=deepseek-chat
DEFAULT_DISCOUNT_LIMIT=0.85
```

如果使用 Ollama 或其他 OpenAI-compatible 本地模型，可改成：

```ini
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
pytest tests/test_agents.py -q
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
- 商品知识库关键词命中。

## 简历项目经历

可直接参考 [docs/RESUME_PROJECT_EXPERIENCE.md](docs/RESUME_PROJECT_EXPERIENCE.md)，里面包含项目描述、技术栈、简历 bullet、面试讲述版本和可量化表达。

## 配置项

| 变量 | 说明 |
| --- | --- |
| `API_KEY` | OpenAI-compatible 模型服务密钥 |
| `MODEL_BASE_URL` | 模型 API base URL |
| `MODEL_NAME` | 模型名称 |
| `COOKIES_STR` | 闲鱼 / Goofish 网页端 Cookie，仅 xianyu 模式需要 |
| `DEFAULT_DISCOUNT_LIMIT` | 最低折扣比例，例如 `0.85` 表示最多降到 8.5 折 |
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
