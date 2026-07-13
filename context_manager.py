import sqlite3
import os
import json
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class ChatMemorySnapshot:
    """A consistent view of one chat's short-term and bargain memory."""

    chat_id: str
    messages: list
    bargain_count: int = 0
    lowest_price_committed: float = None
    buyer_highest_offer: float = None


class ChatContextManager:
    """
    聊天上下文管理器

    负责存储和检索用户与商品之间的对话历史，使用SQLite数据库进行持久化存储。
    支持按会话ID检索对话历史，以及议价次数统计。
    """

    def __init__(self, max_history=100, db_path=None):
        """
        初始化聊天上下文管理器

        Args:
            max_history: 每个对话保留的最大消息数
            db_path: SQLite数据库文件路径
        """
        self.max_history = max_history
        self.db_path = db_path or os.getenv("CHAT_DB_PATH", "data/chat_history.db")
        try:
            self.busy_timeout_ms = max(1000, int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "30000")))
        except ValueError:
            self.busy_timeout_ms = 30000
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=self.busy_timeout_ms / 1000)
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _trim_messages_by_chat(self, cursor, chat_id):
        """Keep only the latest max_history messages for one chat."""
        cursor.execute(
            """
            DELETE FROM messages
            WHERE chat_id = ?
              AND id NOT IN (
                SELECT id FROM messages
                WHERE chat_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
              )
            """,
            (chat_id, chat_id, self.max_history)
        )

    def _init_db(self):
        """初始化数据库表结构"""
        # 确保数据库目录存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)

        conn = self._connect()
        conn.execute("PRAGMA journal_mode = WAL")
        cursor = conn.cursor()

        # 创建消息表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            chat_id TEXT
        )
        ''')

        # 检查是否需要添加chat_id字段（兼容旧数据库）
        cursor.execute("PRAGMA table_info(messages)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'chat_id' not in columns:
            cursor.execute('ALTER TABLE messages ADD COLUMN chat_id TEXT')
            logger.info("已为messages表添加chat_id字段")

        # 创建索引以加速查询
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user_item ON messages (user_id, item_id)
        ''')

        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_id ON messages (chat_id)
        ''')

        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_timestamp ON messages (timestamp)
        ''')

        # 创建基于会话ID的议价次数表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_bargain_counts (
            chat_id TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            lowest_price_committed REAL,
            buyer_highest_offer REAL,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 检查是否需要添加 lowest_price_committed 和 buyer_highest_offer 字段（兼容旧数据库）
        cursor.execute("PRAGMA table_info(chat_bargain_counts)")
        bargain_columns = [column[1] for column in cursor.fetchall()]
        if 'lowest_price_committed' not in bargain_columns:
            cursor.execute('ALTER TABLE chat_bargain_counts ADD COLUMN lowest_price_committed REAL')
            logger.info("已为 chat_bargain_counts 表添加 lowest_price_committed 字段")
        if 'buyer_highest_offer' not in bargain_columns:
            cursor.execute('ALTER TABLE chat_bargain_counts ADD COLUMN buyer_highest_offer REAL')
            logger.info("已为 chat_bargain_counts 表添加 buyer_highest_offer 字段")

        # 创建商品信息表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            price REAL,
            description TEXT,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        conn.commit()
        conn.close()
        logger.info(f"聊天历史数据库初始化完成: {self.db_path}")



    def save_item_info(self, item_id, item_data):
        """
        保存商品信息到数据库

        Args:
            item_id: 商品ID
            item_data: 商品信息字典
        """
        conn = self._connect()
        cursor = conn.cursor()

        try:
            # 从商品数据中提取有用信息
            price = float(item_data.get('soldPrice', 0))
            description = item_data.get('desc', '')

            # 将整个商品数据转换为JSON字符串
            data_json = json.dumps(item_data, ensure_ascii=False)

            cursor.execute(
                """
                INSERT INTO items (item_id, data, price, description, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id)
                DO UPDATE SET data = ?, price = ?, description = ?, last_updated = ?
                """,
                (
                    item_id, data_json, price, description, datetime.now().isoformat(),
                    data_json, price, description, datetime.now().isoformat()
                )
            )

            conn.commit()
            logger.debug(f"商品信息已保存: {item_id}")
        except Exception as e:
            logger.error(f"保存商品信息时出错: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_item_info(self, item_id):
        """
        从数据库获取商品信息

        Args:
            item_id: 商品ID

        Returns:
            dict: 商品信息字典，如果不存在返回None
        """
        conn = self._connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT data FROM items WHERE item_id = ?",
                (item_id,)
            )

            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
        except Exception as e:
            logger.error(f"获取商品信息时出错: {e}")
            return None
        finally:
            conn.close()

    def add_message_by_chat(self, chat_id, user_id, item_id, role, content):
        """
        基于会话ID添加新消息到对话历史

        Args:
            chat_id: 会话ID
            user_id: 用户ID (用户消息存真实user_id，助手消息存卖家ID)
            item_id: 商品ID
            role: 消息角色 (user/assistant)
            content: 消息内容
        """
        conn = self._connect()
        cursor = conn.cursor()

        try:
            # 插入新消息，使用chat_id作为额外标识
            cursor.execute(
                "INSERT INTO messages (user_id, item_id, role, content, timestamp, chat_id) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, item_id, role, content, datetime.now().isoformat(), chat_id)
            )

            self._trim_messages_by_chat(cursor, chat_id)

            conn.commit()
        except Exception as e:
            logger.error(f"添加消息到数据库时出错: {e}")
            conn.rollback()
        finally:
            conn.close()

    def append_turn(self, chat_id, user_id, item_id, user_text, assistant_id, assistant_text=None, intent=None):
        """
        Atomically append one user turn, optional assistant reply, and bargain counter update.

        This avoids half-written memory such as a user message without its assistant reply,
        or a reply recorded without the matching bargain-count transition.
        """
        conn = self._connect()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            cursor.execute(
                "INSERT INTO messages (user_id, item_id, role, content, timestamp, chat_id) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, item_id, "user", user_text, now, chat_id)
            )

            if assistant_text and assistant_text != "-":
                cursor.execute(
                    "INSERT INTO messages (user_id, item_id, role, content, timestamp, chat_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (assistant_id, item_id, "assistant", assistant_text, datetime.now().isoformat(), chat_id)
                )

            if intent == "price":
                cursor.execute(
                    """
                    INSERT INTO chat_bargain_counts (chat_id, count, last_updated)
                    VALUES (?, 1, ?)
                    ON CONFLICT(chat_id)
                    DO UPDATE SET count = count + 1, last_updated = ?
                    """,
                    (chat_id, datetime.now().isoformat(), datetime.now().isoformat())
                )

            self._trim_messages_by_chat(cursor, chat_id)
            conn.commit()
            logger.debug(f"已原子追加会话轮次: chat_id={chat_id}, intent={intent}")
        except Exception as e:
            logger.error(f"追加会话轮次时出错: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_memory_snapshot(self, chat_id):
        """
        Return messages, bargain count, and price commitments in one consistent snapshot.
        """
        conn = self._connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT role, content FROM messages
                WHERE chat_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (chat_id, self.max_history)
            )
            messages = [{"role": role, "content": content} for role, content in cursor.fetchall()]

            cursor.execute(
                """
                SELECT count, lowest_price_committed, buyer_highest_offer
                FROM chat_bargain_counts
                WHERE chat_id = ?
                """,
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                bargain_count, lowest_price_committed, buyer_highest_offer = row
            else:
                bargain_count, lowest_price_committed, buyer_highest_offer = 0, None, None

            return ChatMemorySnapshot(
                chat_id=chat_id,
                messages=messages,
                bargain_count=bargain_count,
                lowest_price_committed=lowest_price_committed,
                buyer_highest_offer=buyer_highest_offer,
            )
        except Exception as e:
            logger.error(f"获取会话记忆快照时出错: {e}")
            return ChatMemorySnapshot(chat_id=chat_id, messages=[])
        finally:
            conn.close()

    def get_context_by_chat(self, chat_id):
        """
        基于会话ID获取对话历史

        Args:
            chat_id: 会话ID

        Returns:
            list: 包含对话历史的列表
        """
        snapshot = self.get_memory_snapshot(chat_id)
        messages = snapshot.messages
        if snapshot.bargain_count > 0:
            messages.append({
                "role": "system",
                "content": f"议价次数: {snapshot.bargain_count}"
            })

        return messages

    def increment_bargain_count_by_chat(self, chat_id):
        """
        基于会话ID增加议价次数

        Args:
            chat_id: 会话ID
        """
        conn = self._connect()
        cursor = conn.cursor()

        try:
            # 使用UPSERT语法直接基于chat_id增加议价次数
            cursor.execute(
                """
                INSERT INTO chat_bargain_counts (chat_id, count, last_updated)
                VALUES (?, 1, ?)
                ON CONFLICT(chat_id)
                DO UPDATE SET count = count + 1, last_updated = ?
                """,
                (chat_id, datetime.now().isoformat(), datetime.now().isoformat())
            )

            conn.commit()
            logger.debug(f"会话 {chat_id} 议价次数已增加")
        except Exception as e:
            logger.error(f"增加议价次数时出错: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_bargain_count_by_chat(self, chat_id):
        """
        基于会话ID获取议价次数

        Args:
            chat_id: 会话ID

        Returns:
            int: 议价次数
        """
        conn = self._connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT count FROM chat_bargain_counts WHERE chat_id = ?",
                (chat_id,)
            )

            result = cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"获取议价次数时出错: {e}")
            return 0
        finally:
            conn.close()

    def get_price_commitments(self, chat_id):
        """
        获取我们在该会话中向买家承诺的最低价，以及买家出的最高价
        """
        conn = self._connect()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT lowest_price_committed, buyer_highest_offer FROM chat_bargain_counts WHERE chat_id = ?",
                (chat_id,)
            )
            result = cursor.fetchone()
            if result:
                return result[0], result[1]
            return None, None
        except Exception as e:
            logger.error(f"获取价格承诺记忆出错: {e}")
            return None, None
        finally:
            conn.close()

    def update_price_commitments(self, chat_id, lowest_price_committed=None, buyer_highest_offer=None):
        """
        更新价格承诺历史与买家最高出价。

        lowest_price_committed 只记录我方承诺过的最低价格，避免后续回复涨回去；
        buyer_highest_offer 只记录买家历史最高出价，避免低出价覆盖高出价。
        """
        conn = self._connect()
        cursor = conn.cursor()
        try:
            # 确保行记录存在，使用 INSERT OR IGNORE 或 UPSERT
            cursor.execute(
                """
                INSERT INTO chat_bargain_counts (chat_id, count, last_updated)
                VALUES (?, 0, ?)
                ON CONFLICT(chat_id) DO NOTHING
                """,
                (chat_id, datetime.now().isoformat())
            )

            if lowest_price_committed is not None:
                cursor.execute(
                    """
                    UPDATE chat_bargain_counts
                    SET lowest_price_committed = CASE
                            WHEN lowest_price_committed IS NULL THEN ?
                            WHEN ? < lowest_price_committed THEN ?
                            ELSE lowest_price_committed
                        END,
                        last_updated = ?
                    WHERE chat_id = ?
                    """,
                    (
                        lowest_price_committed,
                        lowest_price_committed,
                        lowest_price_committed,
                        datetime.now().isoformat(),
                        chat_id,
                    )
                )
            if buyer_highest_offer is not None:
                cursor.execute(
                    """
                    UPDATE chat_bargain_counts
                    SET buyer_highest_offer = CASE
                            WHEN buyer_highest_offer IS NULL THEN ?
                            WHEN ? > buyer_highest_offer THEN ?
                            ELSE buyer_highest_offer
                        END,
                        last_updated = ?
                    WHERE chat_id = ?
                    """,
                    (
                        buyer_highest_offer,
                        buyer_highest_offer,
                        buyer_highest_offer,
                        datetime.now().isoformat(),
                        chat_id,
                    )
                )
            conn.commit()
            logger.debug(f"已更新会话 {chat_id} 的价格记忆：我方承诺={lowest_price_committed}，买家最高={buyer_highest_offer}")
        except Exception as e:
            logger.error(f"更新价格承诺记忆出错: {e}")
            conn.rollback()
        finally:
            conn.close()

    def reset_chat_state(self, chat_id):
        """
        清理指定会话的消息、议价次数和价格承诺。

        主要用于本地 CLI mock 演示，避免上一轮调试缓存影响下一轮演示。
        """
        conn = self._connect()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            cursor.execute("DELETE FROM chat_bargain_counts WHERE chat_id = ?", (chat_id,))
            conn.commit()
            logger.debug(f"已重置会话状态: {chat_id}")
        except Exception as e:
            logger.error(f"重置会话状态出错: {e}")
            conn.rollback()
        finally:
            conn.close()
