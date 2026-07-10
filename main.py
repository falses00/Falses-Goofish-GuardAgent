import base64
import json
import asyncio
import time
import os
import re
import websockets
from loguru import logger
from dotenv import load_dotenv, set_key
from XianyuApis import XianyuApis
import sys
import random


from utils.xianyu_utils import generate_mid, generate_uuid, trans_cookies, generate_device_id, decrypt
from XianyuAgent import XianyuReplyBot
from context_manager import ChatContextManager
from core.message_aggregation import MessageAggregator
from core.model_provider import has_model_api_key
from core.reply_outbox import ReplyOutbox


class XianyuLive:
    def __init__(self, cookies_str):
        self.xianyu = XianyuApis()
        self.base_url = 'wss://wss-goofish.dingtalk.com/'
        self.cookies_str = cookies_str
        self.cookies = trans_cookies(cookies_str)
        self.xianyu.session.cookies.update(self.cookies)  # 直接使用 session.cookies.update
        self.myid = self.cookies['unb']
        self.device_id = generate_device_id(self.myid)
        self.context_manager = ChatContextManager()

        # 心跳相关配置
        self.heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL", "15"))  # 心跳间隔，默认15秒
        self.heartbeat_timeout = int(os.getenv("HEARTBEAT_TIMEOUT", "5"))     # 心跳超时，默认5秒
        self.last_heartbeat_time = 0
        self.last_heartbeat_response = 0
        self.heartbeat_task = None
        self.ws = None

        # Token刷新相关配置
        self.token_refresh_interval = int(os.getenv("TOKEN_REFRESH_INTERVAL", "3600"))  # Token刷新间隔，默认1小时
        self.token_retry_interval = int(os.getenv("TOKEN_RETRY_INTERVAL", "300"))       # Token重试间隔，默认5分钟
        self.last_token_refresh_time = 0
        self.current_token = None
        self.token_refresh_task = None
        self.connection_restart_flag = False  # 连接重启标志

        # 人工接管相关配置
        self.manual_mode_conversations = set()  # 存储处于人工接管模式的会话ID
        self.manual_mode_timeout = int(os.getenv("MANUAL_MODE_TIMEOUT", "3600"))  # 人工接管超时时间，默认1小时
        self.manual_mode_timestamps = {}  # 记录进入人工模式的时间

        # 消息过期时间配置
        self.message_expire_time = int(os.getenv("MESSAGE_EXPIRE_TIME", "300000"))  # 消息过期时间，默认5分钟
        self.message_aggregation_enabled = os.getenv("MESSAGE_AGGREGATION_ENABLED", "true").lower() == "true"
        self.message_aggregator = MessageAggregator(
            debounce_seconds=float(os.getenv("MESSAGE_AGGREGATION_WINDOW_SECONDS", "1.2")),
            max_messages=int(os.getenv("MESSAGE_AGGREGATION_MAX_MESSAGES", "5")),
            max_chars=int(os.getenv("MESSAGE_AGGREGATION_MAX_CHARS", "1200")),
        )
        self.message_flush_tasks = {}
        self.reply_outbox = ReplyOutbox()
        self.reply_send_dry_run = os.getenv("REPLY_SEND_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"}

        # 人工接管关键词，从环境变量读取
        self.toggle_keywords = os.getenv("TOGGLE_KEYWORDS", "。")

        # 模拟人工输入配置
        self.simulate_human_typing = os.getenv("SIMULATE_HUMAN_TYPING", "False").lower() == "true"

    async def refresh_token(self):
        """刷新token"""
        try:
            logger.info("开始刷新token...")

            # 获取新token（如果Cookie失效，get_token会直接退出程序）
            token_result = self.xianyu.get_token(self.device_id)
            if 'data' in token_result and 'accessToken' in token_result['data']:
                new_token = token_result['data']['accessToken']
                self.current_token = new_token
                self.last_token_refresh_time = time.time()
                logger.info("Token刷新成功")
                return new_token
            else:
                logger.error(f"Token刷新失败: {token_result}")
                return None

        except Exception as e:
            logger.error(f"Token刷新异常: {str(e)}")
            return None

    async def token_refresh_loop(self):
        """Token刷新循环"""
        while True:
            try:
                current_time = time.time()

                # 检查是否需要刷新token
                if current_time - self.last_token_refresh_time >= self.token_refresh_interval:
                    logger.info("Token即将过期，准备刷新...")

                    new_token = await self.refresh_token()
                    if new_token:
                        logger.info("Token刷新成功，准备重新建立连接...")
                        # 设置连接重启标志
                        self.connection_restart_flag = True
                        # 关闭当前WebSocket连接，触发重连
                        if self.ws:
                            await self.ws.close()
                        break
                    else:
                        logger.error("Token刷新失败，将在{}分钟后重试".format(self.token_retry_interval // 60))
                        await asyncio.sleep(self.token_retry_interval)  # 使用配置的重试间隔
                        continue

                # 每分钟检查一次
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Token刷新循环出错: {e}")
                await asyncio.sleep(60)

    async def send_msg(self, ws, cid, toid, text):
        text = {
            "contentType": 1,
            "text": {
                "text": text
            }
        }
        text_base64 = str(base64.b64encode(json.dumps(text).encode('utf-8')), 'utf-8')
        msg = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {
                "mid": generate_mid()
            },
            "body": [
                {
                    "uuid": generate_uuid(),
                    "cid": f"{cid}@goofish",
                    "conversationType": 1,
                    "content": {
                        "contentType": 101,
                        "custom": {
                            "type": 1,
                            "data": text_base64
                        }
                    },
                    "redPointPolicy": 0,
                    "extension": {
                        "extJson": "{}"
                    },
                    "ctx": {
                        "appVersion": "1.0",
                        "platform": "web"
                    },
                    "mtags": {},
                    "msgReadStatusSetting": 1
                },
                {
                    "actualReceivers": [
                        f"{toid}@goofish",
                        f"{self.myid}@goofish"
                    ]
                }
            ]
        }
        await ws.send(json.dumps(msg))

    async def init(self, ws):
        # 如果没有token或者token过期，获取新token
        if not self.current_token or (time.time() - self.last_token_refresh_time) >= self.token_refresh_interval:
            logger.info("获取初始token...")
            await self.refresh_token()

        if not self.current_token:
            logger.error("无法获取有效token，初始化失败")
            raise Exception("Token获取失败")

        msg = {
            "lwp": "/reg",
            "headers": {
                "cache-header": "app-key token ua wv",
                "app-key": "444e9908a51d1cb236a27862abc769c9",
                "token": self.current_token,
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) DingWeb/2.1.5 IMPaaS DingWeb/2.1.5",
                "dt": "j",
                "wv": "im:3,au:3,sy:6",
                "sync": "0,0;0;0;",
                "did": self.device_id,
                "mid": generate_mid()
            }
        }
        await ws.send(json.dumps(msg))
        # 等待一段时间，确保连接注册完成
        await asyncio.sleep(1)
        msg = {"lwp": "/r/SyncStatus/ackDiff", "headers": {"mid": "5701741704675979 0"}, "body": [
            {"pipeline": "sync", "tooLong2Tag": "PNM,1", "channel": "sync", "topic": "sync", "highPts": 0,
             "pts": int(time.time() * 1000) * 1000, "seq": 0, "timestamp": int(time.time() * 1000)}]}
        await ws.send(json.dumps(msg))
        logger.info('连接注册完成')

    def is_chat_message(self, message):
        """判断是否为用户聊天消息"""
        try:
            return (
                isinstance(message, dict)
                and "1" in message
                and isinstance(message["1"], dict)  # 确保是字典类型
                and "10" in message["1"]
                and isinstance(message["1"]["10"], dict)  # 确保是字典类型
                and "reminderContent" in message["1"]["10"]
            )
        except Exception:
            return False

    def is_sync_package(self, message_data):
        """判断是否为同步包消息"""
        try:
            return (
                isinstance(message_data, dict)
                and "body" in message_data
                and "syncPushPackage" in message_data["body"]
                and "data" in message_data["body"]["syncPushPackage"]
                and len(message_data["body"]["syncPushPackage"]["data"]) > 0
            )
        except Exception:
            return False

    def is_typing_status(self, message):
        """判断是否为用户正在输入状态消息"""
        try:
            return (
                isinstance(message, dict)
                and "1" in message
                and isinstance(message["1"], list)
                and len(message["1"]) > 0
                and isinstance(message["1"][0], dict)
                and "1" in message["1"][0]
                and isinstance(message["1"][0]["1"], str)
                and "@goofish" in message["1"][0]["1"]
            )
        except Exception:
            return False

    def is_system_message(self, message):
        """判断是否为系统消息"""
        try:
            return (
                isinstance(message, dict)
                and "3" in message
                and isinstance(message["3"], dict)
                and "needPush" in message["3"]
                and message["3"]["needPush"] == "false"
            )
        except Exception:
            return False

    def is_bracket_system_message(self, message):
        """检查是否为带中括号的系统消息"""
        try:
            if not message or not isinstance(message, str):
                return False

            clean_message = message.strip()
            # 检查是否以 [ 开头，以 ] 结尾
            if clean_message.startswith('[') and clean_message.endswith(']'):
                logger.debug(f"检测到系统消息: {clean_message}")
                return True
            return False
        except Exception as e:
            logger.error(f"检查系统消息失败: {e}")
            return False

    def check_toggle_keywords(self, message):
        """检查消息是否包含切换关键词"""
        message_stripped = message.strip()
        return message_stripped in self.toggle_keywords

    def is_manual_mode(self, chat_id):
        """检查特定会话是否处于人工接管模式"""
        if chat_id not in self.manual_mode_conversations:
            return False

        # 检查是否超时
        current_time = time.time()
        if chat_id in self.manual_mode_timestamps:
            if current_time - self.manual_mode_timestamps[chat_id] > self.manual_mode_timeout:
                # 超时，自动退出人工模式
                self.exit_manual_mode(chat_id)
                return False

        return True

    def enter_manual_mode(self, chat_id):
        """进入人工接管模式"""
        self.manual_mode_conversations.add(chat_id)
        self.manual_mode_timestamps[chat_id] = time.time()

    def exit_manual_mode(self, chat_id):
        """退出人工接管模式"""
        self.manual_mode_conversations.discard(chat_id)
        if chat_id in self.manual_mode_timestamps:
            del self.manual_mode_timestamps[chat_id]

    def toggle_manual_mode(self, chat_id):
        """切换人工接管模式"""
        if self.is_manual_mode(chat_id):
            self.exit_manual_mode(chat_id)
            return "auto"
        else:
            self.enter_manual_mode(chat_id)
            return "manual"

    def format_price(self, price):
        """
        处理逻辑：标准化价格（分转元）
        """
        try:
            return round(float(price) / 100, 2)
        except (ValueError, TypeError):
            # 遇到 None 或脏数据，默认返回 0
            return 0.0

    def build_item_description(self, item_info):
        """构建商品描述"""

        # 处理 SKU 列表
        clean_skus = []
        raw_sku_list = item_info.get('skuList', [])

        for sku in raw_sku_list:
            # 提取规格文本
            specs = [p['valueText'] for p in sku.get('propertyList', []) if p.get('valueText')]
            spec_text = " ".join(specs) if specs else "默认规格"

            clean_skus.append({
                "spec": spec_text,
                "price": self.format_price(sku.get('price', 0)),
                "stock": sku.get('quantity', 0)
            })

        # 获取价格
        valid_prices = [s['price'] for s in clean_skus if s['price'] > 0]

        if valid_prices:
            min_price = min(valid_prices)
            max_price = max(valid_prices)
            if min_price == max_price:
                price_display = f"¥{min_price}"
            else:
                price_display = f"¥{min_price} - ¥{max_price}" # 价格区间
        else:
            # 如果没有SKU价格，回退使用商品主价格
            main_price = round(float(item_info.get('soldPrice', 0)), 2)
            price_display = f"¥{main_price}"

        summary = {
            "title": item_info.get('title', ''),
            "desc": item_info.get('desc', ''),
            "price_range": price_display,
            "total_stock": item_info.get('quantity', 0),
            "sku_details": clean_skus
        }

        return json.dumps(summary, ensure_ascii=False)

    async def _process_buyer_message(
        self,
        websocket,
        chat_id,
        send_user_id,
        item_id,
        send_message,
        send_user_name="买家",
        aggregation_count=1,
        source_message_id=None,
    ):
        source_message_id = source_message_id or ReplyOutbox.build_source_message_id(
            chat_id, item_id, send_user_id, send_message
        )
        dedupe_key = ReplyOutbox.build_dedupe_key(chat_id, item_id, send_user_id, source_message_id)
        existing_record = self.reply_outbox.get(dedupe_key)
        if existing_record and existing_record.status in {"pending", "sending", "sent", "skipped"}:
            logger.info(
                f"检测到重复买家消息事件，跳过重复 Agent 决策: chat_id={chat_id}, "
                f"item_id={item_id}, outbox_status={existing_record.status}"
            )
            return

        # 从数据库中获取商品信息，如果不存在则从API获取并保存
        item_info = self.context_manager.get_item_info(item_id)
        if not item_info:
            logger.info(f"从API获取商品信息: {item_id}")
            api_result = self.xianyu.get_item_info(item_id)
            if 'data' in api_result and 'itemDO' in api_result['data']:
                item_info = api_result['data']['itemDO']
                self.context_manager.save_item_info(item_id, item_info)
            else:
                logger.warning(f"获取商品信息失败: {api_result}")
                return
        else:
            logger.info(f"从数据库获取商品信息: {item_id}")

        item_description = f"当前商品的信息如下：{self.build_item_description(item_info)}"

        context = self.context_manager.get_context_by_chat(chat_id)
        bot_reply = bot.generate_reply(
            send_message,
            item_description,
            context=context,
            chat_id=chat_id,
            item_id=item_id,
        )

        if aggregation_count > 1:
            logger.info(f"已将 {aggregation_count} 条连续买家消息聚合为 1 次 Agent 决策: chat_id={chat_id}")

        # 检查是否需要回复
        if bot_reply == "-":
            logger.info(f"[无需回复] 用户 {send_user_name} 的消息被识别为无需回复类型")
            self.context_manager.append_turn(
                chat_id,
                send_user_id,
                item_id,
                send_message,
                self.myid,
                assistant_text=None,
                intent=bot.last_intent
            )
            no_reply_record = self.reply_outbox.enqueue(
                chat_id=chat_id,
                item_id=item_id,
                user_id=send_user_id,
                source_message_id=source_message_id,
                reply_text="-",
                trace=bot.last_trace.to_dict(),
            )
            self.reply_outbox.mark_skipped(no_reply_record.dedupe_key, "no_reply")
            return

        self.context_manager.append_turn(
            chat_id,
            send_user_id,
            item_id,
            send_message,
            self.myid,
            assistant_text=bot_reply,
            intent=bot.last_intent
        )
        if bot.last_intent == "price":
            bargain_count = self.context_manager.get_bargain_count_by_chat(chat_id)
            logger.info(f"用户 {send_user_name} 对商品 {item_id} 的议价次数: {bargain_count}")

        logger.info(f"机器人回复: {bot_reply}")
        trace = bot.last_trace.to_dict()
        outbox_record = self.reply_outbox.enqueue(
            chat_id=chat_id,
            item_id=item_id,
            user_id=send_user_id,
            source_message_id=source_message_id,
            reply_text=bot_reply,
            trace=trace,
        )
        claim = self.reply_outbox.claim_for_send(outbox_record.dedupe_key)
        if not claim.claimed:
            logger.info(
                f"回复发送跳过: chat_id={chat_id}, item_id={item_id}, "
                f"reason={claim.reason}, outbox_status={claim.record.status}"
            )
            return

        # 模拟人工输入延迟
        if self.simulate_human_typing:
            base_delay = random.uniform(0, 1)
            typing_delay = len(bot_reply) * random.uniform(0.1, 0.3)
            total_delay = min(base_delay + typing_delay, 10.0)
            logger.info(f"模拟人工输入，延迟发送 {total_delay:.2f} 秒...")
            await asyncio.sleep(total_delay)

        if self.reply_send_dry_run:
            self.reply_outbox.mark_skipped(outbox_record.dedupe_key, "dry_run")
            logger.info(f"REPLY_SEND_DRY_RUN=true，仅记录不真实发送: chat_id={chat_id}, item_id={item_id}")
            return

        try:
            await self.send_msg(websocket, chat_id, send_user_id, bot_reply)
            sent_record = self.reply_outbox.mark_sent(outbox_record.dedupe_key)
            logger.info(
                f"回复发送成功: chat_id={chat_id}, item_id={item_id}, "
                f"outbox_id={sent_record.id}, attempts={sent_record.attempt_count}"
            )
        except Exception as exc:
            failed_record = self.reply_outbox.mark_failed(outbox_record.dedupe_key, str(exc))
            logger.error(
                f"回复发送失败: chat_id={chat_id}, item_id={item_id}, "
                f"outbox_id={failed_record.id}, error={exc}"
            )
            raise

    async def _flush_aggregated_buyer_message_after_delay(self, key, websocket, send_user_name, delay_seconds):
        try:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            batch = self.message_aggregator.pop(key)
            if not batch:
                return
            await self._process_buyer_message(
                websocket,
                batch.chat_id,
                batch.user_id,
                batch.item_id,
                batch.combined_text(),
                send_user_name=send_user_name,
                aggregation_count=batch.count,
                source_message_id=ReplyOutbox.build_source_message_id(
                    batch.chat_id,
                    batch.item_id,
                    batch.user_id,
                    batch.combined_text(),
                    event_time_ms=batch.last_seen_ms,
                ),
            )
        except asyncio.CancelledError:
            raise
        finally:
            current_task = asyncio.current_task()
            if self.message_flush_tasks.get(key) is current_task:
                self.message_flush_tasks.pop(key, None)

    async def _enqueue_or_process_buyer_message(
        self,
        websocket,
        chat_id,
        send_user_id,
        item_id,
        send_message,
        send_user_name,
        create_time,
    ):
        if not self.message_aggregation_enabled:
            await self._process_buyer_message(
                websocket,
                chat_id,
                send_user_id,
                item_id,
                send_message,
                send_user_name=send_user_name,
                source_message_id=ReplyOutbox.build_source_message_id(
                    chat_id,
                    item_id,
                    send_user_id,
                    send_message,
                    event_time_ms=create_time,
                ),
            )
            return

        key, should_flush = self.message_aggregator.append(
            chat_id=chat_id,
            item_id=item_id,
            user_id=send_user_id,
            text=send_message,
            now_ms=create_time,
        )
        existing_task = self.message_flush_tasks.pop(key, None)
        if existing_task:
            existing_task.cancel()
        delay_seconds = 0 if should_flush else self.message_aggregator.debounce_seconds
        self.message_flush_tasks[key] = asyncio.create_task(
            self._flush_aggregated_buyer_message_after_delay(
                key,
                websocket,
                send_user_name,
                delay_seconds,
            )
        )
        logger.info(
            f"消息已进入聚合窗口: chat_id={chat_id}, item_id={item_id}, "
            f"delay={delay_seconds:.2f}s, force_flush={should_flush}"
        )

    async def handle_message(self, message_data, websocket):
        """处理所有类型的消息"""
        try:

            try:
                message = message_data
                ack = {
                    "code": 200,
                    "headers": {
                        "mid": message["headers"]["mid"] if "mid" in message["headers"] else generate_mid(),
                        "sid": message["headers"]["sid"] if "sid" in message["headers"] else '',
                    }
                }
                if 'app-key' in message["headers"]:
                    ack["headers"]["app-key"] = message["headers"]["app-key"]
                if 'ua' in message["headers"]:
                    ack["headers"]["ua"] = message["headers"]["ua"]
                if 'dt' in message["headers"]:
                    ack["headers"]["dt"] = message["headers"]["dt"]
                await websocket.send(json.dumps(ack))
            except Exception as e:
                pass

            # 如果不是同步包消息，直接返回
            if not self.is_sync_package(message_data):
                return

            # 获取并解密数据
            sync_data = message_data["body"]["syncPushPackage"]["data"][0]

            # 检查是否有必要的字段
            if "data" not in sync_data:
                logger.debug("同步包中无data字段")
                return

            # 解密数据
            try:
                data = sync_data["data"]
                try:
                    data = base64.b64decode(data).decode("utf-8")
                    data = json.loads(data)
                    # logger.info(f"无需解密 message: {data}")
                    return
                except Exception as e:
                    # logger.info(f'加密数据: {data}')
                    decrypted_data = decrypt(data)
                    message = json.loads(decrypted_data)
            except Exception as e:
                logger.error(f"消息解密失败: {e}")
                return

            try:
                # 判断是否为订单消息,需要自行编写付款后的逻辑
                if message['3']['redReminder'] == '等待买家付款':
                    user_id = message['1'].split('@')[0]
                    user_url = f'https://www.goofish.com/personal?userId={user_id}'
                    logger.info(f'等待买家 {user_url} 付款')
                    return
                elif message['3']['redReminder'] == '交易关闭':
                    user_id = message['1'].split('@')[0]
                    user_url = f'https://www.goofish.com/personal?userId={user_id}'
                    logger.info(f'买家 {user_url} 交易关闭')
                    return
                elif message['3']['redReminder'] == '等待卖家发货':
                    user_id = message['1'].split('@')[0]
                    user_url = f'https://www.goofish.com/personal?userId={user_id}'
                    logger.info(f'交易成功 {user_url} 等待卖家发货')
                    return

            except:
                pass

            # 判断消息类型
            if self.is_typing_status(message):
                logger.debug("用户正在输入")
                return
            elif not self.is_chat_message(message):
                logger.debug("其他非聊天消息")
                logger.debug(f"原始消息: {message}")
                return

            # 处理聊天消息
            create_time = int(message["1"]["5"])
            send_user_name = message["1"]["10"]["reminderTitle"]
            send_user_id = message["1"]["10"]["senderUserId"]
            send_message = message["1"]["10"]["reminderContent"]

            # 时效性验证（过滤5分钟前消息）
            if (time.time() * 1000 - create_time) > self.message_expire_time:
                logger.debug("过期消息丢弃")
                return

            # 获取商品ID和会话ID
            url_info = message["1"]["10"]["reminderUrl"]
            item_id = url_info.split("itemId=")[1].split("&")[0] if "itemId=" in url_info else None
            chat_id = message["1"]["2"].split('@')[0]

            if not item_id:
                logger.warning("无法获取商品ID")
                return

            # 检查是否为卖家（自己）发送的控制命令
            if send_user_id == self.myid:
                logger.debug("检测到卖家消息，检查是否为控制命令")

                # 检查切换命令
                if self.check_toggle_keywords(send_message):
                    mode = self.toggle_manual_mode(chat_id)
                    if mode == "manual":
                        logger.info(f"🔴 已接管会话 {chat_id} (商品: {item_id})")
                    else:
                        logger.info(f"🟢 已恢复会话 {chat_id} 的自动回复 (商品: {item_id})")
                    return

                # 记录卖家人工回复
                self.context_manager.add_message_by_chat(chat_id, self.myid, item_id, "assistant", send_message)
                logger.info(f"卖家人工回复 (会话: {chat_id}, 商品: {item_id}): {send_message}")
                return

            logger.info(f"用户: {send_user_name} (ID: {send_user_id}), 商品: {item_id}, 会话: {chat_id}, 消息: {send_message}")


            # 如果当前会话处于人工接管模式，不进行自动回复
            if self.is_manual_mode(chat_id):
                logger.info(f"🔴 会话 {chat_id} 处于人工接管模式，跳过自动回复")
                # 添加用户消息到上下文
                self.context_manager.add_message_by_chat(chat_id, send_user_id, item_id, "user", send_message)
                return
            # 检查是否为带中括号的系统消息
            if self.is_bracket_system_message(send_message):
                logger.info(f"检测到系统消息：'{send_message}'，跳过自动回复")
                return
            if self.is_system_message(message):
                logger.debug("系统消息，跳过处理")
                return
            await self._enqueue_or_process_buyer_message(
                websocket,
                chat_id,
                send_user_id,
                item_id,
                send_message,
                send_user_name,
                create_time,
            )

        except Exception as e:
            logger.error(f"处理消息时发生错误: {str(e)}")
            logger.debug(f"原始消息: {message_data}")

    async def send_heartbeat(self, ws):
        """发送心跳包并等待响应"""
        try:
            heartbeat_mid = generate_mid()
            heartbeat_msg = {
                "lwp": "/!",
                "headers": {
                    "mid": heartbeat_mid
                }
            }
            await ws.send(json.dumps(heartbeat_msg))
            self.last_heartbeat_time = time.time()
            logger.debug("心跳包已发送")
            return heartbeat_mid
        except Exception as e:
            logger.error(f"发送心跳包失败: {e}")
            raise

    async def heartbeat_loop(self, ws):
        """心跳维护循环"""
        while True:
            try:
                current_time = time.time()

                # 检查是否需要发送心跳
                if current_time - self.last_heartbeat_time >= self.heartbeat_interval:
                    await self.send_heartbeat(ws)

                # 检查上次心跳响应时间，如果超时则认为连接已断开
                if (current_time - self.last_heartbeat_response) > (self.heartbeat_interval + self.heartbeat_timeout):
                    logger.warning("心跳响应超时，可能连接已断开")
                    break

                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"心跳循环出错: {e}")
                break

    async def handle_heartbeat_response(self, message_data):
        """处理心跳响应"""
        try:
            if (
                isinstance(message_data, dict)
                and "headers" in message_data
                and "mid" in message_data["headers"]
                and "code" in message_data
                and message_data["code"] == 200
            ):
                self.last_heartbeat_response = time.time()
                logger.debug("收到心跳响应")
                return True
        except Exception as e:
            logger.error(f"处理心跳响应出错: {e}")
        return False

    async def main(self):
        while True:
            try:
                # 重置连接重启标志
                self.connection_restart_flag = False

                headers = {
                    "Cookie": self.cookies_str,
                    "Host": "wss-goofish.dingtalk.com",
                    "Connection": "Upgrade",
                    "Pragma": "no-cache",
                    "Cache-Control": "no-cache",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    "Origin": "https://www.goofish.com",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }

                async with websockets.connect(self.base_url, extra_headers=headers) as websocket:
                    self.ws = websocket
                    await self.init(websocket)

                    # 初始化心跳时间
                    self.last_heartbeat_time = time.time()
                    self.last_heartbeat_response = time.time()

                    # 启动心跳任务
                    self.heartbeat_task = asyncio.create_task(self.heartbeat_loop(websocket))

                    # 启动token刷新任务
                    self.token_refresh_task = asyncio.create_task(self.token_refresh_loop())

                    async for message in websocket:
                        try:
                            # 检查是否需要重启连接
                            if self.connection_restart_flag:
                                logger.info("检测到连接重启标志，准备重新建立连接...")
                                break

                            message_data = json.loads(message)

                            # 处理心跳响应
                            if await self.handle_heartbeat_response(message_data):
                                continue

                            # 发送通用ACK响应
                            if "headers" in message_data and "mid" in message_data["headers"]:
                                ack = {
                                    "code": 200,
                                    "headers": {
                                        "mid": message_data["headers"]["mid"],
                                        "sid": message_data["headers"].get("sid", "")
                                    }
                                }
                                # 复制其他可能的header字段
                                for key in ["app-key", "ua", "dt"]:
                                    if key in message_data["headers"]:
                                        ack["headers"][key] = message_data["headers"][key]
                                await websocket.send(json.dumps(ack))

                            # 处理其他消息
                            await self.handle_message(message_data, websocket)

                        except json.JSONDecodeError:
                            logger.error("消息解析失败")
                        except Exception as e:
                            logger.error(f"处理消息时发生错误: {str(e)}")
                            logger.debug(f"原始消息: {message}")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket连接已关闭")

            except Exception as e:
                logger.error(f"连接发生错误: {e}")

            finally:
                # 清理任务
                if self.heartbeat_task:
                    self.heartbeat_task.cancel()
                    try:
                        await self.heartbeat_task
                    except asyncio.CancelledError:
                        pass

                if self.token_refresh_task:
                    self.token_refresh_task.cancel()
                    try:
                        await self.token_refresh_task
                    except asyncio.CancelledError:
                        pass

                if self.message_flush_tasks:
                    pending_flush_tasks = list(self.message_flush_tasks.values())
                    for task in pending_flush_tasks:
                        task.cancel()
                    await asyncio.gather(*pending_flush_tasks, return_exceptions=True)
                    self.message_flush_tasks.clear()

                # 如果是主动重启，立即重连；否则等待5秒
                if self.connection_restart_flag:
                    logger.info("主动重启连接，立即重连...")
                else:
                    logger.info("等待5秒后重连...")
                    await asyncio.sleep(5)

async def run_cli_mode():
    """
    本地交互式 Mock 命令行调试终端。
    无需闲鱼 Cookie，直接通过本地终端与重构后的 Agent 开展议价博弈和详情咨询。
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.prompt import Prompt

    console = Console()
    console.print(Panel(
        "[bold green]Falses Goofish GuardAgent 本地模拟调试终端[/bold green]\n"
        "您现在扮演 [bold yellow]买家[/bold yellow]，可在下方输入框内对商品进行咨询或砍价。\n"
        "系统将使用您的 .env 配置自动调用大模型。无需闲鱼凭证，开箱即用。\n"
        "输入 [bold red]exit[/bold red] 或 [bold red]quit[/bold red] 退出系统。",
        title="⚙️ 二开本地 Mock 调试端",
        border_style="green"
    ))

    # 1. 实例化机器人并配置模拟商品上下文
    bot = XianyuReplyBot()
    chat_id = "mock_chat_001"

    # 清理此前的测试缓存，以防混淆
    bot.db.reset_chat_state(chat_id)

    # 2. 从本地 JSON 库加载测试商品信息
    item_info = {}
    info_path = "data/product_info.json"
    if os.path.exists(info_path):
        try:
            with open(info_path, "r", encoding="utf-8") as f:
                item_info = json.load(f)
        except Exception as e:
            logger.warning(f"无法读取商品配置 json: {e}")

    item_title = item_info.get("title", "二手 iPad Pro 11寸")
    original_price = item_info.get("original_price", 4299)
    min_price = item_info.get("min_price", 3800)

    # 构建与咸鱼接口格式一致的描述
    item_description = f"当前商品的信息如下：标题:{item_title} 价格:{original_price}元 详情: {json.dumps(item_info, ensure_ascii=False)}"

    # 打印商品名片
    console.print(Panel(
        f"[bold cyan]测试在售商品[/bold cyan]: {item_title}\n"
        f"[bold yellow]上架定价[/bold yellow]: {original_price} 元 | [bold red]最大折扣底线[/bold red]: {min_price} 元\n"
        f"[bold green]邮寄规则[/bold green]: {item_info.get('shipping_fee', '包邮')}",
        title="📦 示例商品卡片",
        border_style="cyan",
        expand=False
    ))

    # 3. 核心聊天交互循环
    while True:
        try:
            user_input = await asyncio.to_thread(
                Prompt.ask,
                Text("\n[买家] 请输入咨询内容", style="bold cyan")
            )

            if user_input.strip().lower() in ["exit", "quit"]:
                console.print("[bold red]已退出本地调试终端。[/bold red]")
                break

            if not user_input.strip():
                continue

            # 使用状态动画掩盖 API 调用延迟
            with console.status("[bold yellow]Agent 正在决策路由并生成回复...", spinner="dots"):
                # 获取 SQLite 对话历史
                context = bot.db.get_context_by_chat(chat_id)

                # 调用 Bot 生成回复
                bot_reply = bot.generate_reply(
                    user_input,
                    item_description,
                    context=context,
                    chat_id=chat_id,
                    item_id="mock_item_001",
                )

                bot.db.append_turn(
                    chat_id,
                    "buyer",
                    "mock_item_001",
                    user_input,
                    "seller",
                    assistant_text=None if bot_reply == "-" else bot_reply,
                    intent=bot.last_intent
                )

            # 读取持久化的决策细节并呈现
            snapshot = bot.db.get_memory_snapshot(chat_id)
            trace = bot.last_trace.to_dict()
            guardrails = "、".join(trace.get("guardrails") or []) or "无"
            price_decision = trace.get("price_decision") or {}
            knowledge = trace.get("knowledge") or {}

            console.print(Panel(
                f"[bold]识别意图[/bold]: {bot.last_intent}\n"
                f"[bold]议价次数[/bold]: {snapshot.bargain_count} 次\n"
                f"[bold]已启用护栏[/bold]: {guardrails}\n"
                f"[bold]价格承诺跟踪[/bold]: 我方承诺价格水位 [{snapshot.lowest_price_committed if snapshot.lowest_price_committed else '无'}] 元 | 买家最高出价 [{snapshot.buyer_highest_offer if snapshot.buyer_highest_offer else '无'}] 元\n"
                f"[bold]定价来源[/bold]: {price_decision.get('price_source', '无')} | [bold]知识命中[/bold]: {knowledge.get('matched', '无')}",
                title="⚙️ 决策状态监控 (二开新增)",
                border_style="yellow",
                expand=False
            ))

            # 打字机特效打印回复
            if bot_reply == "-":
                console.print("\n[AI 客服] [dim italic yellow](消息被判定为 no_reply，已跳过回复)[/dim italic yellow]")
            else:
                console.print(Text("\n[AI 客服] ", style="bold green"), end="")
                for char in bot_reply:
                    print(char, end="", flush=True)
                    await asyncio.sleep(0.015)
                print()

        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold red]程序已强行终止。[/bold red]")
            break


class SmokeCompletions:
    def create(self, model, messages, temperature=0.4, max_tokens=500, top_p=0.8):
        system_prompt = messages[0]["content"]
        user_msg = messages[-1]["content"]
        price_match = re.search(r"最终报价是: 【([0-9.]+)】", system_prompt)
        if price_match:
            price = price_match.group(1)
            content = f"这个价我认真算过了，最低只能到 {price} 元，再低就真的不合适了。"
        elif "商品知识库真实参数" in system_prompt:
            content = "这台我按实说：屏幕贴膜使用无划痕，电池健康 93%，配件和发货信息都按商品说明来。"
        else:
            content = f"收到，你问的是“{user_msg}”。我这边可以继续帮你确认商品细节。"
        return type("SmokeResponse", (), {
            "choices": [type("SmokeChoice", (), {
                "message": type("SmokeMessage", (), {"content": content})()
            })()]
        })()


class SmokeChat:
    def __init__(self):
        self.completions = SmokeCompletions()


class SmokeLLMClient:
    def __init__(self):
        self.chat = SmokeChat()


def run_smoke_mode():
    """
    Deterministic end-to-end runtime smoke test through router, agents, SQLite memory, and trace.
    """
    smoke_db_path = os.getenv("SMOKE_DB_PATH", "data/smoke_chat_history.db")
    bot = XianyuReplyBot(client=SmokeLLMClient(), db_path=smoke_db_path)
    chat_id = "smoke_chat_001"
    item_id = "smoke_item_001"
    bot.db.reset_chat_state(chat_id)

    with open("data/product_info.json", "r", encoding="utf-8") as f:
        item_info = json.load(f)

    item_description = (
        f"当前商品的信息如下：标题:{item_info.get('title')} "
        f"价格:{item_info.get('original_price')}元 详情: {json.dumps(item_info, ensure_ascii=False)}"
    )
    buyer_messages = [
        "这个屏幕有划痕吗，电池健康多少？",
        "128G 的话，3000 元能出吗？",
        "4100 可以的话我马上拍",
    ]

    print("SMOKE_START")
    for user_input in buyer_messages:
        context = bot.db.get_context_by_chat(chat_id)
        reply = bot.generate_reply(user_input, item_description, context=context, chat_id=chat_id, item_id=item_id)
        bot.db.append_turn(
            chat_id,
            "smoke_buyer",
            item_id,
            user_input,
            "smoke_seller",
            assistant_text=None if reply == "-" else reply,
            intent=bot.last_intent
        )
        trace = bot.last_trace.to_dict()
        print(json.dumps({
            "user": user_input,
            "reply": reply,
            "intent": bot.last_intent,
            "trace": trace,
        }, ensure_ascii=False))

    snapshot = bot.db.get_memory_snapshot(chat_id)
    print(json.dumps({
        "smoke_result": "ok",
        "messages": len(snapshot.messages),
        "bargain_count": snapshot.bargain_count,
        "lowest_price_committed": snapshot.lowest_price_committed,
        "buyer_highest_offer": snapshot.buyer_highest_offer,
    }, ensure_ascii=False))
    print("SMOKE_DONE")


def check_and_complete_env():
    """检查并补全关键环境变量"""
    placeholder_values = {
        "COOKIES_STR": {"your_cookies_here"},
    }

    env_path = ".env"
    updated = False

    for key, placeholders in placeholder_values.items():
        curr_val = os.getenv(key)
        if not curr_val or curr_val in placeholders:
            logger.warning(f"配置项 [{key}] 未设置，请输入")
            while True:
                val = input(f"请输入 {key}: ").strip()
                if val:
                    os.environ[key] = val
                    try:
                        if not os.path.exists(env_path):
                            with open(env_path, 'w', encoding='utf-8') as f:
                                pass
                        set_key(env_path, key, val)
                        updated = True
                    except Exception as e:
                        logger.warning(f"无法自动写入.env文件: {e}")
                    break
                else:
                    print(f"{key} 不能为空，请重新输入")

    if not has_model_api_key():
        logger.warning("未配置模型 API Key，请输入 Agnes API Key")
        while True:
            val = input("请输入 AGNES_API_KEY: ").strip()
            if val:
                os.environ["AGNES_API_KEY"] = val
                try:
                    if not os.path.exists(env_path):
                        with open(env_path, 'w', encoding='utf-8') as f:
                            pass
                    set_key(env_path, "AGNES_API_KEY", val)
                    updated = True
                except Exception as e:
                    logger.warning(f"无法自动写入.env文件: {e}")
                break
            else:
                print("AGNES_API_KEY 不能为空，请重新输入")
    if updated:
        logger.info("新的配置已保存/更新至 .env 文件中")


if __name__ == '__main__':
    import argparse
    import sys

    # 1. 解析启动命令行参数
    parser = argparse.ArgumentParser(description="Falses Goofish GuardAgent 深度二开版")
    parser.add_argument(
        "--mode",
        type=str,
        default="xianyu",
        choices=["xianyu", "cli", "smoke"],
        help="运行模式：xianyu (咸鱼 WebSocket 挂机模式，需 Cookie)；cli (本地命令行交互 Mock 调试)；smoke (离线端到端自检)"
    )
    args = parser.parse_args()

    # 2. 加载环境变量
    if os.path.exists(".env"):
        load_dotenv()
        logger.info("已加载 .env 配置")
    if os.path.exists(".env.example"):
        load_dotenv(".env.example")  # 不会覆盖已存在的变量
        logger.info("已加载 .env.example 默认配置")

    # 3. 配置日志级别
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    logger.info(f"日志级别设置为: {log_level} | 当前模式: {args.mode}")

    # 4. 根据模式分支执行
    if args.mode == "cli":
        # 本地调试模式下，如果未配模型 API Key，引导输入。默认会写入 AGNES_API_KEY。
        if not has_model_api_key():
            logger.warning("未配置模型 API Key，请先输入 Agnes API Key 以使用大模型进行交互：")
            api_key = input("AGNES_API_KEY: ").strip()
            if api_key:
                os.environ["AGNES_API_KEY"] = api_key
                if os.path.exists(".env"):
                    set_key(".env", "AGNES_API_KEY", api_key)
            else:
                logger.error("模型 API Key 不能为空，程序退出。")
                sys.exit(1)

        # 启动异步本地 CLI 对话终端
        asyncio.run(run_cli_mode())
    elif args.mode == "smoke":
        run_smoke_mode()
    else:
        # 挂机长连接模式下，交互式检查并补全 Cookie 和 API_KEY
        check_and_complete_env()
        cookies_str = os.getenv("COOKIES_STR")
        bot = XianyuReplyBot()
        xianyuLive = XianyuLive(cookies_str)
        asyncio.run(xianyuLive.main())
