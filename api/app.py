import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from core.evaluation import DeterministicLLMClient
from core.trace_store import JsonlTraceStore
from XianyuAgent import XianyuReplyBot


DEFAULT_PRODUCT_INFO_PATH = Path("data/product_info.json")


class ReplyRequest(BaseModel):
    user_msg: str = Field(..., min_length=1)
    chat_id: str = Field("api_chat_001", min_length=1)
    item_id: str = Field("api_item_001", min_length=1)
    user_id: str = Field("api_buyer", min_length=1)
    assistant_id: str = Field("api_seller", min_length=1)
    item_info: Optional[Dict[str, Any]] = None
    context: Optional[List[Dict[str, str]]] = None
    persist_turn: bool = True


class MemorySnapshotResponse(BaseModel):
    chat_id: str
    messages: List[Dict[str, str]]
    bargain_count: int
    lowest_price_committed: Optional[float] = None
    buyer_highest_offer: Optional[float] = None


class ReplyResponse(BaseModel):
    reply: str
    intent: str
    trace: Dict[str, Any]
    memory: MemorySnapshotResponse


def _is_offline_mode() -> bool:
    explicit_value = os.getenv("API_OFFLINE_MODE")
    if explicit_value is not None:
        return explicit_value.lower() in {"1", "true", "yes", "on"}
    return not bool(os.getenv("API_KEY"))


def _load_default_item_info() -> Dict[str, Any]:
    if not DEFAULT_PRODUCT_INFO_PATH.exists():
        return {}
    return json.loads(DEFAULT_PRODUCT_INFO_PATH.read_text(encoding="utf-8"))


def _build_item_description(item_info: Dict[str, Any]) -> str:
    title = item_info.get("title") or item_info.get("desc") or "未命名商品"
    price = item_info.get("original_price") or item_info.get("price") or item_info.get("soldPrice") or ""
    return f"当前商品的信息如下：标题:{title} 价格:{price}元 详情: {json.dumps(item_info, ensure_ascii=False)}"


def _snapshot_to_response(snapshot) -> MemorySnapshotResponse:
    return MemorySnapshotResponse(
        chat_id=snapshot.chat_id,
        messages=snapshot.messages,
        bargain_count=snapshot.bargain_count,
        lowest_price_committed=snapshot.lowest_price_committed,
        buyer_highest_offer=snapshot.buyer_highest_offer,
    )


def create_app(
    offline_mode: Optional[bool] = None,
    db_path: Optional[str] = None,
    trace_path: Optional[str] = None,
) -> FastAPI:
    app = FastAPI(
        title="Falses Goofish GuardAgent API",
        version="0.2.0",
        description="Service API for local-first Xianyu / Goofish AI customer-service agent.",
    )
    use_offline_client = _is_offline_mode() if offline_mode is None else offline_mode
    client = DeterministicLLMClient() if use_offline_client else None
    app.state.bot = XianyuReplyBot(
        client=client,
        db_path=db_path or os.getenv("API_CHAT_DB_PATH", "data/api_chat_history.db"),
    )
    app.state.trace_store = JsonlTraceStore(
        trace_path or os.getenv("AGENT_TRACE_PATH", "logs/agent_traces.jsonl")
    )
    app.state.offline_mode = use_offline_client

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "offline_mode": app.state.offline_mode}

    @app.post("/api/reply", response_model=ReplyResponse)
    def reply(request: ReplyRequest) -> ReplyResponse:
        bot: XianyuReplyBot = app.state.bot
        item_info = request.item_info or _load_default_item_info()
        item_description = _build_item_description(item_info)
        context = request.context if request.context is not None else bot.db.get_context_by_chat(request.chat_id)

        bot_reply = bot.generate_reply(
            request.user_msg,
            item_description,
            context=context,
            chat_id=request.chat_id,
        )

        if request.persist_turn:
            bot.db.append_turn(
                chat_id=request.chat_id,
                user_id=request.user_id,
                item_id=request.item_id,
                user_text=request.user_msg,
                assistant_id=request.assistant_id,
                assistant_text=None if bot_reply == "-" else bot_reply,
                intent=bot.last_intent,
            )

        trace = bot.last_trace.to_dict()
        app.state.trace_store.append(trace)
        snapshot = bot.db.get_memory_snapshot(request.chat_id)
        return ReplyResponse(
            reply=bot_reply,
            intent=bot.last_intent,
            trace=trace,
            memory=_snapshot_to_response(snapshot),
        )

    @app.get("/api/traces")
    def traces(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
        records = app.state.trace_store.tail(limit)
        return {"count": len(records), "items": records}

    return app


app = create_app()
