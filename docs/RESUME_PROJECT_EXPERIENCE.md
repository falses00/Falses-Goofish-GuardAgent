# Falses Goofish GuardAgent 简历项目经历

## 真实反思

上一轮优化已经完成了品牌化、README 重写、基础议价护栏、SQLite 价格记忆和测试，但还不足以称为“最佳 Agent 设计实践”。主要不足是：

- **可观测性不足**：只能看到最终回复，不能稳定解释一次 Agent 决策经过了哪些路由、护栏和知识命中。
- **策略来源不清晰**：底价主要依赖环境变量折扣，没有优先使用商品级 `min_price`。
- **失败路径覆盖不够**：没有测试错误折扣配置、商品规格数字误判报价、知识库未命中等边界。
- **简历表达偏包装**：项目亮点还没有转译成面试官能快速理解的工程贡献。

本轮优化补齐了这些问题，让项目从“能展示的二开 Demo”进一步变成“可解释、可测试、有工程边界的 Agent 项目”。

## 项目一句话

基于闲鱼 / Goofish WebSocket 消息链路二次开发的本地优先 AI 客服 Agent，通过规则路由、价格护栏、商品知识库和 SQLite 状态记忆，将 LLM 回复从“生成式聊天”升级为可控、可解释、可测试的交易辅助系统。

## 推荐简历写法

### 项目名称

Falses Goofish GuardAgent：闲鱼二手交易 AI 客服与议价安全 Agent

### 项目描述

基于 Python、OpenAI-compatible LLM、WebSocket、SQLite 与 Rich CLI 构建闲鱼 / Goofish AI 客服 Agent，在原有自动回复项目基础上重构决策链路，引入多 Agent 路由、确定性议价护栏、商品事实 RAG、会话状态记忆和可观测 Trace，支持本地 Mock 调试与真实闲鱼长连接挂机。

### 技术栈

Python、OpenAI SDK、WebSocket、SQLite、pytest、Rich CLI、Prompt Engineering、Agent Routing、Guardrails、RAG-lite

### 简历 Bullet

- 二次开发闲鱼 AI 客服系统，重构为 `IntentRouter -> PriceAgent / TechAgent / DefaultAgent -> Guardrails -> LLM` 的多 Agent 决策链路，实现咨询、议价、闲聊等场景的可控分发。
- 设计 `BargainExpert` 确定性议价策略，将价格底线、历史承诺价、买家最高出价从 LLM Prompt 中剥离为代码级约束，避免模型被诱导突破底价或前后报价不一致。
- 基于 SQLite 实现会话级状态记忆，持久化聊天历史、议价次数、我方最低承诺价和买家最高出价；通过事务化 `append_turn` 原子写入用户消息、助手回复和议价次数，避免半轮上下文污染，并采用单调更新策略保证价格承诺只降不升、买家报价只取最高。
- 引入 JSON 商品知识库与 `FAQExpert`，针对成色、拆修、配件、物流、面交等高风险问题注入事实上下文，降低 LLM 编造商品信息导致售后纠纷的风险。
- 新增 `AgentTrace` 可观测机制，记录每轮决策的意图、路由 Agent、议价次数、启用护栏、定价来源、价格决策和知识命中结果，支持 CLI 面板展示与日志排查。
- 构建本地 Mock CLI 调试模式，无需真实闲鱼 Cookie 即可模拟买家咨询和砍价，提升项目演示、策略调参和回归验证效率。
- 使用 pytest 覆盖议价边界、历史承诺不抬价、商品级底价优先、无效折扣回退、规格数字误判报价、RAG 命中/未命中和 SQLite 单调记忆等核心路径。
- 新增 `python main.py --mode smoke` 离线端到端自检，使用内置 LLM stub 真实穿过入口、路由、Agent、SQLite 记忆、Trace 和回复生成链路，降低回归验证对真实 Cookie/API Key 的依赖。

## 面试讲述版本

这个项目不是简单接一个大模型自动回复，而是把交易场景里最危险的决策从 LLM 中剥离出来。LLM 只负责表达，价格、商品事实和会话承诺由确定性代码与 SQLite 控制。

我把系统拆成三层：

1. **路由层**：先通过关键词和正则判断咨询、议价、闲聊，规则兜不住再交给分类 Agent。
2. **策略层**：议价由 `BargainExpert` 计算安全价格，商品咨询由 `FAQExpert` 从本地 JSON 知识库抽取事实。
3. **表达层**：把策略结果注入 Prompt，让 LLM 生成自然话术，但不能改写底价和商品事实。

为了让系统可调试，我加了 `AgentTrace`，每次回复都会记录意图、路由、价格决策、知识命中和护栏。这样出了问题不是猜 Prompt，而是能直接看到决策链路。

## 可量化表达

如果需要放在简历里更偏结果，可以写：

- 将原项目从单一自动回复改造为 4 类 Agent 协同链路，补齐价格护栏、商品事实约束、会话记忆和本地调试能力。
- 为核心决策路径补充 10+ 个单元测试，覆盖正常路径、边界值、错误配置和对抗输入。
- 将真实闲鱼挂机链路与本地 Mock 演示链路统一到同一套 Agent 决策核心，降低调试和演示对平台 Cookie 的依赖。

## GitHub 项目简介

Falses Goofish GuardAgent is a local-first AI customer-service and bargain-guard agent for Xianyu / Goofish. It combines deterministic pricing guardrails, SQLite conversation memory, lightweight product-fact retrieval, and OpenAI-compatible LLM responses to make second-hand trading automation more controllable and explainable.
