import json
import os
import re
from typing import Any, Dict, List, Tuple
from openai import OpenAI
from loguru import logger

# 引入二开新增专家模块与上下文数据库
from core.experts import BargainExpert, FAQExpert
from core.observability import AgentTrace
from context_manager import ChatContextManager


class XianyuReplyBot:
    """
    重构升级后的闲鱼智能回复 Bot。
    保持原有外部调用接口不变，内部注入多智能体专家协同、议价安全护栏 (Guardrails) 与 SQLite 持久化会话记忆。
    """
    def __init__(self):
        # 初始化 OpenAI 客户端
        self.client = OpenAI(
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("MODEL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
        # 初始化持久化数据库管理器，用于跟踪报价承诺
        self.db = ChatContextManager()

        self._init_system_prompts()
        self._init_agents()
        self.router = IntentRouter(self.agents['classify'])
        self.last_intent = None  # 记录最后一次意图
        self.last_trace = AgentTrace()

    def _init_agents(self):
        """初始化各领域 Agent (注入了数据库实例 self.db)"""
        self.agents = {
            'classify': ClassifyAgent(self.client, self.classify_prompt, self._safe_filter, self.db),
            'price': PriceAgent(self.client, self.price_prompt, self._safe_filter, self.db),
            'tech': TechAgent(self.client, self.tech_prompt, self._safe_filter, self.db),
            'default': DefaultAgent(self.client, self.default_prompt, self._safe_filter, self.db),
        }

    def _init_system_prompts(self):
        """初始化各 Agent 专用提示词，优先加载用户自定义文件，否则使用 Example 默认文件"""
        prompt_dir = "prompts"

        def load_prompt_content(name: str) -> str:
            target_path = os.path.join(prompt_dir, f"{name}.txt")
            if os.path.exists(target_path):
                file_path = target_path
            else:
                file_path = os.path.join(prompt_dir, f"{name}_example.txt")

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                logger.debug(f"已加载 {name} 提示词，路径: {file_path}, 长度: {len(content)} 字符")
                return content

        try:
            self.classify_prompt = load_prompt_content("classify_prompt")
            self.price_prompt = load_prompt_content("price_prompt")
            self.tech_prompt = load_prompt_content("tech_prompt")
            self.default_prompt = load_prompt_content("default_prompt")
            logger.info("成功加载所有提示词模板")
        except Exception as e:
            logger.error(f"加载提示词时出错: {e}")
            raise

    def _safe_filter(self, text: str) -> str:
        """安全过滤模块，防导流风控"""
        blocked_phrases = ["微信", "QQ", "支付宝", "银行卡", "线下"]
        return "[安全提醒] 建议通过闲鱼平台沟通并完成交易，保障双方资金安全。" if any(p in text for p in blocked_phrases) else text

    def format_history(self, context: List[Dict]) -> str:
        """格式化对话历史，返回完整的对话记录"""
        user_assistant_msgs = [msg for msg in context if msg['role'] in ['user', 'assistant']]
        return "\n".join([f"{msg['role']}: {msg['content']}" for msg in user_assistant_msgs])

    def generate_reply(self, user_msg: str, item_desc: str, context: List[Dict], chat_id: str = "mock_chat_001") -> str:
        """
        生成回复主流程（扩展了 chat_id 参数以支持会话级报价跟踪）
        """
        formatted_context = self.format_history(context)
        self.last_trace = AgentTrace(chat_id=chat_id, user_msg=user_msg)

        # 1. 三级意图分类路由决策
        detected_intent = self.router.detect(user_msg, item_desc, formatted_context)

        internal_intents = {'classify'}  # 定义不对外开放的 Agent

        if detected_intent == 'no_reply':
            logger.info(f"意图识别完成: no_reply - 无需回复")
            self.last_intent = 'no_reply'
            self.last_trace.intent = 'no_reply'
            self.last_trace.routed_agent = 'none'
            self.last_trace.no_reply = True
            logger.info(f"[AgentTrace] {json.dumps(self.last_trace.to_dict(), ensure_ascii=False)}")
            return "-"  # 返回特殊标记，表示无需回复

        elif detected_intent in self.agents and detected_intent not in internal_intents:
            agent = self.agents[detected_intent]
            logger.info(f"意图识别完成: 转发至 [{detected_intent}Agent]")
            self.last_intent = detected_intent  # 保存当前意图
        else:
            agent = self.agents['default']
            logger.info(f"意图识别完成: 转发至 [defaultAgent]")
            self.last_intent = 'default'  # 保存当前意图

        # 2. 获取议价次数 (从 SQLite 缓存中检索)
        bargain_count = self.db.get_bargain_count_by_chat(chat_id)
        logger.info(f"会话 {chat_id} 历史议价次数: {bargain_count}")

        # 3. 驱动对应 Agent 生成最终润色回复
        reply = agent.generate(
            user_msg=user_msg,
            item_desc=item_desc,
            context=formatted_context,
            bargain_count=bargain_count,
            chat_id=chat_id
        )
        self.last_trace.intent = self.last_intent
        self.last_trace.routed_agent = agent.__class__.__name__
        self.last_trace.bargain_count = bargain_count
        agent_trace = getattr(agent, "last_trace", {})
        self.last_trace.guardrails = agent_trace.get("guardrails", [])
        self.last_trace.price_decision = agent_trace.get("price_decision", {})
        self.last_trace.knowledge = agent_trace.get("knowledge", {})
        logger.info(f"[AgentTrace] {json.dumps(self.last_trace.to_dict(), ensure_ascii=False)}")
        return reply

    def reload_prompts(self):
        """重新加载所有提示词"""
        logger.info("正在重新加载提示词...")
        self._init_system_prompts()
        self._init_agents()
        logger.info("提示词重新加载完成")


class IntentRouter:
    """意图路由决策器"""
    def __init__(self, classify_agent):
        self.rules = {
            'tech': {  # 技术细节与商品状况问询优先判定
                'keywords': ['参数', '规格', '型号', '连接', '对比', '电池', '健康', '成色', '配件', '划痕', '磕碰', '发票', '哪里买', '顺丰', '邮费'],
                'patterns': [
                    r'和.+比', r'几成新', r'坏', r'拆', r'修', r'保修'
                ]
            },
            'price': { # 砍价意图判定
                'keywords': ['便宜', '价', '砍价', '少点', '大刀', '抹零', '邮费', '少个邮费'],
                'patterns': [r'\d+元', r'能少\d+', r'包邮']
            }
        }
        self.classify_agent = classify_agent

    def detect(self, user_msg: str, item_desc, context) -> str:
        """三级路由策略"""
        text_clean = re.sub(r'[^\w\u4e00-\u9fa5]', '', user_msg)

        # 1. 技术类关键词优先检查
        if any(kw in text_clean for kw in self.rules['tech']['keywords']):
            return 'tech'

        # 2. 技术类正则优先检查
        for pattern in self.rules['tech']['patterns']:
            if re.search(pattern, text_clean):
                return 'tech'

        # 3. 价格类检查
        for intent in ['price']:
            if any(kw in text_clean for kw in self.rules[intent]['keywords']):
                return intent
            for pattern in self.rules[intent]['patterns']:
                if re.search(pattern, text_clean):
                    return intent

        # 4. 规则无法匹配时，由大模型分类 Agent 进行兜底
        logger.debug("规则无法精确匹配意图，交由大模型分类 Agent 决策...")
        return self.classify_agent.generate(
            user_msg=user_msg,
            item_desc=item_desc,
            context=context
        )


class BaseAgent:
    """Agent 基类"""
    def __init__(self, client, system_prompt, safety_filter, db: ChatContextManager):
        self.client = client
        self.system_prompt = system_prompt
        self.safety_filter = safety_filter
        self.db = db
        self.last_trace = {}

    def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0, chat_id: str = None) -> str:
        """生成回复的模板方法"""
        messages = self._build_messages(user_msg, item_desc, context)
        response = self._call_llm(messages)
        return self.safety_filter(response)

    def _build_messages(self, user_msg: str, item_desc: str, context: str) -> List[Dict]:
        """构建标准消息链路"""
        return [
            {"role": "system", "content": f"【商品信息】{item_desc}\n【你与客户对话历史】{context}\n{self.system_prompt}"},
            {"role": "user", "content": user_msg}
        ]

    def _call_llm(self, messages: List[Dict], temperature: float = 0.4) -> str:
        """调用大模型"""
        response = self.client.chat.completions.create(
            model=os.getenv("MODEL_NAME", "deepseek-chat"),
            messages=messages,
            temperature=temperature,
            max_tokens=500,
            top_p=0.8
        )
        return response.choices[0].message.content


class PriceAgent(BaseAgent):
    """
    二开重构后的议价处理 Agent。
    不再只是调整大模型温度，而是强制集成“议价卫士”数值安全护栏和 SQLite 价格记忆。
    """
    def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0, chat_id: str = None) -> str:
        # 1. 尝试从商品详情中动态提取当前定价与底价策略
        original_price, min_price, price_source = self._extract_price_profile(item_desc)

        # 2. 实例化议价专家决策内核
        expert = BargainExpert(original_price, min_price)

        # 3. 从 SQLite 读取历史承诺
        last_committed, buyer_highest = self.db.get_price_commitments(chat_id)

        # 4. 从用户输入中提取买家具体出价数字
        buyer_offer = self._extract_buyer_offer(user_msg, original_price)

        # 5. 运行算法，计算出我方的出价决策
        decision = expert.calculate_next_price(buyer_offer, last_committed)
        calculated_price = decision["price"]
        action = decision["action"]
        reason = decision["reason"]

        self.last_trace = {
            "guardrails": ["pricing_floor", "no_price_raise_after_commitment"],
            "price_decision": {
                "original_price": original_price,
                "min_price": min_price,
                "price_source": price_source,
                "buyer_offer": buyer_offer,
                "last_committed": last_committed,
                "buyer_highest": buyer_highest,
                "calculated_price": calculated_price,
                "action": action,
                "reason": reason,
            },
        }
        logger.info(f"[议价卫士决策] 动作: {action} | 建议报价: {calculated_price} | 推理原因: {reason}")

        # 6. 更新持久化数据库中的报价承诺
        self.db.update_price_commitments(
            chat_id,
            lowest_price_committed=calculated_price,
            buyer_highest_offer=buyer_offer
        )

        # 8. 大模型话术润色 (注入算法决策结果，保证人设的生动性与价格的准确性)
        messages = self._build_messages(user_msg, item_desc, context)

        # 覆写或增强 system prompt，强制约束大模型回复价格
        guideline = (
            f"\n▲【绝对核心业务规则】:\n"
            f"1. 针对买家的出价，你经过深思熟虑做出的决策是: {action}。\n"
            f"2. 你本次的最终报价是: 【{calculated_price}】元。在回复中，有且仅能提供这个价格，绝对不允许说出任何低于此价格的数字！\n"
            f"3. 请用个人卖家接地气、口语化的文风包装该报价，可以委婉诉苦、讲明邮费或者爽快同意。不要显得像个死板的计算器。"
        )
        messages[0]['content'] += guideline
        messages[0]['content'] += f"\n▲当前议价轮次：{bargain_count}"

        dynamic_temp = self._calc_temperature(bargain_count)
        response_text = self._call_llm(messages, temperature=dynamic_temp)
        return self.safety_filter(response_text)

    @staticmethod
    def _extract_json_payload(item_desc: str) -> Dict[str, Any]:
        """Extract the embedded JSON object from item descriptions when present."""
        start = item_desc.find("{")
        if start == -1:
            return {}
        try:
            return json.loads(item_desc[start:])
        except json.JSONDecodeError:
            logger.warning("商品描述中包含 JSON 起始符，但解析失败，降级使用文本价格提取")
            return {}

    @classmethod
    def _extract_price_profile(cls, item_desc: str) -> Tuple[float, float, str]:
        """Return original price, minimum acceptable price, and source label."""
        payload = cls._extract_json_payload(item_desc)
        original_price = cls._coerce_float(payload.get("original_price") or payload.get("price"))
        min_price = cls._coerce_float(payload.get("min_price"))
        source = "json"

        if original_price is None:
            price_range = payload.get("price_range") if payload else None
            original_price = cls._extract_first_price(str(price_range or ""))
            source = "json_price_range"

        if original_price is None:
            price_match = re.search(r'价格[:：]\s*(\d+(?:\.\d+)?)', item_desc)
            if price_match:
                original_price = float(price_match.group(1))
                source = "text_price"

        if original_price is None:
            original_price = cls._extract_first_price(item_desc) or 100.0
            source = "text_fallback"

        discount_limit = cls._load_discount_limit()
        if min_price is None or min_price <= 0 or min_price > original_price:
            min_price = original_price * discount_limit
            source = f"{source}+discount_limit"

        return float(original_price), float(min_price), source

    @staticmethod
    def _coerce_float(value: Any) -> float:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_first_price(text: str) -> float:
        match = re.search(r'(?:￥|¥)?\s*(\d+(?:\.\d+)?)\s*(?:元|块|rmb)?', text.lower())
        if not match:
            return None
        return float(match.group(1))

    @staticmethod
    def _load_discount_limit() -> float:
        raw_limit = os.getenv("DEFAULT_DISCOUNT_LIMIT", "0.85")
        try:
            discount_limit = float(raw_limit)
        except ValueError:
            logger.warning(f"DEFAULT_DISCOUNT_LIMIT={raw_limit} 无效，已回退为 0.85")
            return 0.85
        if not 0 < discount_limit <= 1:
            logger.warning(f"DEFAULT_DISCOUNT_LIMIT={raw_limit} 越界，已回退为 0.85")
            return 0.85
        return discount_limit

    @staticmethod
    def _extract_buyer_offer(user_msg: str, original_price: float) -> float:
        explicit_price = re.search(r'(?:￥|¥)?\s*(\d+(?:\.\d+)?)\s*(?:元|块|rmb)', user_msg.lower())
        if explicit_price:
            value = float(explicit_price.group(1))
            if 100 < value < original_price * 1.5:
                return value

        for match in re.finditer(r'\b(\d+(?:\.\d+)?)\b', user_msg):
            value = float(match.group(1))
            if max(300, original_price * 0.2) < value < original_price * 1.5:
                if 1900 <= value <= 2100:
                    continue
                return value
        return None

    def _calc_temperature(self, bargain_count: int) -> float:
        """动态温度策略，控制多轮拉锯时的语义多样性"""
        return min(0.3 + bargain_count * 0.15, 0.9)


class TechAgent(BaseAgent):
    """
    二开重构后的技术/详情咨询 Agent。
    引入 RAG FAQ 思想，从本地商品知识库提取精准的规格参数并动态注入提示词，防止 LLM 满口跑火车。
    """
    def generate(self, user_msg: str, item_desc: str, context: str, bargain_count: int = 0, chat_id: str = None) -> str:
        # 1. 尝试加载本地的商品知识库库 product_info.json
        product_info = {}
        info_path = "data/product_info.json"
        if os.path.exists(info_path):
            try:
                with open(info_path, "r", encoding="utf-8") as f:
                    product_info = json.load(f)
            except Exception as e:
                logger.warning(f"读取本地商品知识库失败: {e}")

        # 2. 引入 FAQ 专家过滤并提取相关知识
        kb_context = ""
        if product_info:
            faq_expert = FAQExpert(product_info)
            kb_context = faq_expert.extract_related_kb(user_msg)
            if kb_context:
                logger.info(f"[RAG FAQ 匹配成功] 命中属性: {kb_context}")
            else:
                logger.info("[RAG FAQ 未命中] 使用商品描述和通用提示词兜底")

        self.last_trace = {
            "guardrails": ["truthful_product_facts"] if kb_context else [],
            "knowledge": {
                "source": info_path if product_info else None,
                "matched": bool(kb_context),
                "context": kb_context,
            },
        }

        messages = self._build_messages(user_msg, item_desc, context)

        # 3. 将命中参数动态注入 System Prompt 顶部，提供可靠的事实底座
        if kb_context:
            rag_instruction = (
                f"\n▲【商品知识库真实参数（请严格基于此信息回答，严禁幻觉或编造）】:\n"
                f"{kb_context}\n"
                f"如果知识库中未提及相关信息，请诚实告知买家，绝对不要虚构任何参数以免发生退货纠纷。"
            )
            messages[0]['content'] += rag_instruction

        response_text = self._call_llm(messages, temperature=0.3)
        return self.safety_filter(response_text)


class ClassifyAgent(BaseAgent):
    """意图识别 Agent (保持与基类逻辑一致，并在需要时可独立重构)"""
    def generate(self, **args) -> str:
        response = super().generate(**args)
        return response.strip().lower()


class DefaultAgent(BaseAgent):
    """默认处理 Agent (提供高情商闲聊回复并兜底)"""
    def _call_llm(self, messages: List[Dict], *args) -> str:
        # 闲聊时提高温度以展现更多灵活性
        response = super()._call_llm(messages, temperature=0.7)
        return response
