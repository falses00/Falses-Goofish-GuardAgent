# Falses Goofish GuardAgent 简历项目经历

## 一页简历精简版（推荐直接使用）

### Falses Goofish GuardAgent｜闲鱼交易客服与议价安全 Agent

**技术栈：** Python、FastAPI、WebSocket、SQLite、Agnes AI、OpenAI SDK、pytest、Docker、GitHub Actions

**项目描述：** 基于闲鱼真实 WebSocket 消息链路构建本地优先交易 Agent，将商品咨询、议价、承诺校验和回复执行拆分为可观测、可回放的决策链路；LLM 负责自然语言表达，价格、商品事实、会话承诺和发送幂等由确定性模块控制。

- 重构 `IntentRouter -> TechAgent / PriceAgent / DefaultAgent -> Guardrails -> LLM` 多 Agent 架构，通过可插拔注册表、商品事实检索和真人化表达层支持咨询、砍价与交易疑虑场景；真实 Agnes 三轮演示全部正常返回，Trace 可解释路由、知识来源与护栏。
- 将议价底线从 Prompt 剥离为确定性 `BargainExpert`，结合商品级 `min_price`、历史最低承诺价与买家最高报价生成单调价格决策；实测对 3500 元报价拒绝并反报价 4149 元，严格高于 3800 元底线。
- 设计 SQLite 会话记忆与 Reply Outbox，原子记录用户/助手完整 turn，基于源事件哈希、事务 claim、状态机和超时租约抑制重连重复发送；离线 replay 验证重复事件只写入一轮记忆且网络发送为 0。
- 完成真实闲鱼 Token 获取、WebSocket 注册、小时级 Token 刷新与断线重连验证；根据约 5.5 小时运行日志定位 DNS 暂态故障误判与陈旧认证错误问题，引入 typed transient error、HTTP 超时、有限重试及成功后状态清理，避免无人值守进程错误退出或放大平台请求。
- 建立 `doctor / smoke / demo / replay / golden eval` 分层验证体系和 CI 门禁，覆盖模型故障降级、跨商品事实隔离、价格底线、规则承诺、Outbox 并发与认证失败路径；当前 pytest 回归用例 56 项全部通过，并完成 `websockets 13.1 / 15.x` 兼容验证。

**项目链接：** https://github.com/falses00/Falses-Goofish-GuardAgent

## 真实反思

上一轮优化已经完成了品牌化、README 重写、基础议价护栏、SQLite 价格记忆和测试，但还不足以称为“最佳 Agent 设计实践”。主要不足是：

- **可观测性不足**：只能看到最终回复，不能稳定解释一次 Agent 决策经过了哪些路由、护栏和知识命中。
- **策略来源不清晰**：底价主要依赖环境变量折扣，没有优先使用商品级 `min_price`。
- **失败路径覆盖不够**：没有测试错误折扣配置、商品规格数字误判报价、知识库未命中等边界。
- **简历表达偏包装**：项目亮点还没有转译成面试官能快速理解的工程贡献。

本轮继续补齐服务化与可回放能力，让项目从“能展示的二开 Demo”进一步变成“可解释、可测试、有工程边界、能被外部系统集成的 Agent 项目”。

## 项目一句话

基于闲鱼 / Goofish WebSocket 消息链路二次开发的本地优先 AI 客服 Agent，通过规则路由、价格护栏、商品知识库、真人化回复风格层、回复执行 Outbox、SQLite 状态记忆、FastAPI 服务接口和 trace/eval 体系，将 LLM 回复从“生成式聊天”升级为可控、可解释、可测试、可集成的交易辅助系统。

## 推荐简历写法

### 项目名称

Falses Goofish GuardAgent：闲鱼二手交易 AI 客服与议价安全 Agent

### 项目描述

基于 Python、Agnes AI / OpenAI-compatible LLM、FastAPI、WebSocket、SQLite 与 Rich CLI 构建闲鱼 / Goofish AI 客服 Agent，在原有自动回复项目基础上重构决策链路，引入多 Agent 路由、确定性议价护栏、商品事实 RAG、真人化表达约束、回复执行 Outbox、会话状态记忆、可观测 Trace 和离线评测体系，支持本地 Mock 调试、HTTP 服务化集成与真实闲鱼长连接挂机。

### 技术栈

Python、FastAPI、Agnes AI、OpenAI SDK、WebSocket、SQLite、pytest、Rich CLI、Prompt Engineering、Agent Routing、Guardrails、RAG-lite、Agent Evaluation、Observability

### 简历 Bullet

- 二次开发闲鱼 AI 客服系统，重构为 `IntentRouter -> PriceAgent / TechAgent / DefaultAgent -> Guardrails -> LLM` 的多 Agent 决策链路，实现咨询、议价、闲聊等场景的可控分发。
- 设计可插拔 `AgentRegistry` 与统一 handler 契约，支持按意图动态注册 Agent、配置关键词/正则优先级、Prompt 热重载后保留扩展，并通过 capabilities API 暴露运行时能力，新增业务无需修改中心 Agent loop。
- 抽象 `model_provider` 配置层，默认接入 Agnes AI 的 OpenAI-compatible Chat Completions API，同时保留 `API_KEY / MODEL_BASE_URL / MODEL_NAME` 兼容路径，降低后续模型切换成本。
- 设计连续消息聚合模块，在 Agent loop 前按 `chat_id + item_id + user_id` 对买家短时间多条消息进行 debounce 合并，将平台事件流稳定为业务 turn，减少重复回复、半截上下文污染和无效 LLM 调用。
- 设计商品规则中心，将允许承诺、禁止承诺、售后边界和发货条件从 Prompt 中抽离为结构化 JSON 规则；回复前注入规则上下文，回复后做禁止承诺校验，避免模型编造成功率、内部渠道、平台外交易等高风险话术。
- 设计真人化回复风格层，将“像真实闲鱼个人卖家”从 prompt 口号落成可配置护栏；生成前注入口语化约束，生成后确定性清洗“作为 AI 客服”“感谢咨询”等机器腔表达，并将改写结果写入 Trace。
- 设计回复执行 Outbox，在真实 WebSocket 发送前持久化回复，基于 SQLite 原子事务实现并发安全 claim 与 `pending / sending / sent / failed / skipped` 状态流转；失败恢复复用原回复、避免二次 LLM 调用和重复记忆写入，并通过超时 lease 恢复进程崩溃造成的卡单，同时明确远端无幂等键时的 ACK 重复窗口。
- 实现交付决策引擎，根据商品类型、订单状态和是否需要人工确认输出 `wait_for_payment / manual_review / auto_deliver` 等可审计动作，为后续自动发货执行层提供安全前置判断。
- 设计 `BargainExpert` 确定性议价策略，将价格底线、历史承诺价、买家最高出价从 LLM Prompt 中剥离为代码级约束，避免模型被诱导突破底价或前后报价不一致。
- 基于 SQLite 实现会话级状态记忆，持久化聊天历史、议价次数、我方最低承诺价和买家最高出价；通过事务化 `append_turn` 原子写入用户消息、助手回复和议价次数，避免半轮上下文污染，并采用单调更新策略保证价格承诺只降不升、买家报价只取最高。
- 引入 JSON 商品知识库与 `FAQExpert`，针对成色、拆修、配件、物流、面交等高风险问题注入事实上下文，降低 LLM 编造商品信息导致售后纠纷的风险。
- 修复跨商品事实污染：`TechAgent` 强制优先使用当前消息携带的商品上下文，仅在缺失结构化数据时使用演示知识库，并用对抗测试证明阿里云教程不会混入 iPad 屏幕/电池信息。
- 建立模型故障隔离层，将超时、空响应和 provider 异常降级为可发送的确定性安全回复；议价降级仍引用代码计算价格，Trace 记录 `model_fallback` 与错误类型，避免 LLM 故障拖垮 WebSocket 消费循环。
- 新增 `AgentTrace` 可观测机制，记录每轮决策的意图、路由 Agent、议价次数、启用护栏、定价来源、价格决策和知识命中结果，支持 CLI 面板展示与日志排查。
- 将 Agent core 服务化为 FastAPI backend，提供 `/api/reply`、`/api/traces` 与 `/health` 接口，返回结构化回复、意图、trace 和 memory snapshot，支持 Web 管理台、移动端自动化桥接或 MCP server 复用同一套决策能力。
- 设计 `JsonlTraceStore` 追加式 trace 存储，保存每轮 Agent 决策快照，支持最近 trace 回查、离线 replay 和线上问题定位。
- 构建本地 Mock CLI 调试模式，无需真实闲鱼 Cookie 即可模拟买家咨询和砍价，提升项目演示、策略调参和回归验证效率。
- 使用 pytest 覆盖议价边界、历史承诺不抬价、商品级底价优先、无效折扣回退、规格数字误判报价、RAG 命中/未命中、SQLite 单调记忆、API 结构化响应和空消息 422 失败路径等核心路径。
- 新增 `python main.py --mode smoke` 离线端到端自检，使用内置 LLM stub 真实穿过入口、路由、Agent、SQLite 记忆、Trace 和回复生成链路，降低回归验证对真实 Cookie/API Key 的依赖。
- 新增 `python main.py --mode replay` 实时执行链离线回放，复用挂机模式的消息处理与 Outbox 代码，验证 dry-run 零网络副作用、重复事件抑制、发送失败重试和记忆一致性。
- 构建离线 Agent 评测 harness，将真实交易对话抽象为黄金评测集，基于 trace-level 断言评估意图路由、RAG 命中、护栏触发、价格决策和最终记忆状态，并接入 GitHub Actions 作为 CI 质量门禁。
- 修复容器交付链路，Compose 改为构建当前仓库镜像并完整打包 `core / api / prompts / data`；新增无密钥泄露的 doctor fail-fast 检查，并在 CI 中加入 Docker image build，避免部署继续运行上游旧代码。
- 将 Cookie 过期与平台风控从 `input / sys.exit / 递归重试` 改为 typed authentication error；非交互容器停止 WebSocket/token 任务并快速退出，避免无人值守部署挂死或持续请求放大风控。

## 面试讲述版本

这个项目不是简单接一个大模型自动回复，而是把交易场景里最危险的决策从 LLM 中剥离出来。LLM 只负责表达，价格、商品事实和会话承诺由确定性代码与 SQLite 控制。

我把系统拆成四层：

1. **路由层**：先通过关键词和正则判断咨询、议价、闲聊，规则兜不住再交给分类 Agent。
2. **策略层**：议价由 `BargainExpert` 计算安全价格，商品咨询由 `FAQExpert` 从本地 JSON 知识库抽取事实，商品规则中心控制承诺边界。
3. **表达层**：把策略结果注入 Prompt，让 LLM 生成自然话术，再由 `HumanReplyStyler` 清洗机器腔和客服腔。
4. **执行层**：真实发送前进入 Reply Outbox，按源消息去重并原子抢占发送权；发送失败只重试已落库回复，租约超时后可恢复中断任务。
5. **服务与评测层**：FastAPI 暴露 typed contract，JSONL trace 支持回放，golden eval 和 pytest 在 CI 中阻断回归。

为了让系统可调试，我加了 `AgentTrace`，每次回复都会记录意图、路由、价格决策、知识命中和护栏。这样出了问题不是猜 Prompt，而是能直接看到决策链路。

## 可量化表达

如果需要放在简历里更偏结果，可以写：

- 将原项目从单一自动回复改造为 4 类 Agent 协同链路，补齐价格护栏、商品事实约束、会话记忆、服务接口、trace 回放和本地调试能力。
- 为核心决策路径补充 50+ 个单元 / API 测试，覆盖正常路径、边界值、错误配置、对抗输入、动态 Agent 注册、模型超时降级、跨商品事实隔离、消息聚合状态机、真人化回复、Outbox 并发 claim / 失败恢复 / 租约回收、规则护栏、交付决策和 HTTP 失败路径。
- 将真实闲鱼挂机链路与本地 Mock 演示链路统一到同一套 Agent 决策核心，降低调试和演示对平台 Cookie 的依赖。
- 基于黄金交易场景构建离线 Agent eval gate，检查 intent、routed agent、guardrails、RAG grounding、price decision 和 memory consistency，避免只用最终自然语言回复判断质量。

## GitHub 项目简介

Falses Goofish GuardAgent is a local-first AI customer-service and bargain-guard agent for Xianyu / Goofish. It combines deterministic pricing guardrails, SQLite conversation memory, lightweight product-fact retrieval, FastAPI service contracts, JSONL traces, and OpenAI-compatible LLM responses to make second-hand trading automation more controllable, explainable, testable, and product-ready.
