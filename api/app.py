import json
import hashlib
import os
import re
import secrets
import uuid
from contextlib import nullcontext
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Path as ApiPath, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from core.api_request_replay import ApiRequestReplayStore, RequestReplayConflict
from core.evaluation import DeterministicLLMClient
from core.message_aggregation import MessageBatch
from core.model_provider import has_model_api_key
from core.runtime_status import build_runtime_status_report
from core.trace_store import JsonlTraceStore
from XianyuAgent import XianyuReplyBot


DEFAULT_PRODUCT_INFO_PATH = Path("data/product_info.json")
STATIC_DIR = Path(__file__).resolve().parent / "static"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class ReplyRequest(BaseModel):
    request_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    user_msg: str = Field(..., min_length=1, max_length=2000)
    additional_user_msgs: List[str] = Field(default_factory=list, max_length=10)
    chat_id: str = Field("api_chat_001", min_length=1, max_length=128)
    item_id: str = Field("api_item_001", min_length=1, max_length=128)
    user_id: str = Field("api_buyer", min_length=1, max_length=128)
    assistant_id: str = Field("api_seller", min_length=1, max_length=128)
    item_info: Optional[Dict[str, Any]] = None
    context: Optional[List[Dict[str, str]]] = Field(default=None, max_length=50)
    persist_turn: bool = True

    @field_validator("user_msg")
    @classmethod
    def validate_user_message(cls, message: str) -> str:
        normalized = message.strip()
        if not normalized:
            raise ValueError("user message must not be blank")
        return normalized

    @field_validator("chat_id", "item_id", "user_id", "assistant_id")
    @classmethod
    def validate_identifiers(cls, identifier: str) -> str:
        normalized = identifier.strip()
        if not normalized:
            raise ValueError("identifier must not be blank")
        return normalized

    @field_validator("additional_user_msgs")
    @classmethod
    def validate_additional_messages(cls, messages: List[str]) -> List[str]:
        normalized = [message.strip() for message in messages if message.strip()]
        if any(len(message) > 1000 for message in normalized):
            raise ValueError("additional messages must not exceed 1000 characters")
        return normalized


class MemorySnapshotResponse(BaseModel):
    chat_id: str
    messages: List[Dict[str, str]]
    bargain_count: int
    lowest_price_committed: Optional[float] = None
    buyer_highest_offer: Optional[float] = None


class ReplyResponse(BaseModel):
    request_id: Optional[str] = None
    idempotent_replay: bool = False
    reply: str
    intent: str
    trace: Dict[str, Any]
    memory: MemorySnapshotResponse


def _is_offline_mode() -> bool:
    explicit_value = os.getenv("API_OFFLINE_MODE")
    if explicit_value is not None:
        requested_offline = explicit_value.lower() in {"1", "true", "yes", "on"}
        return requested_offline or not has_model_api_key()
    return not has_model_api_key()


def _load_default_item_info() -> Dict[str, Any]:
    if not DEFAULT_PRODUCT_INFO_PATH.exists():
        return {}
    return json.loads(DEFAULT_PRODUCT_INFO_PATH.read_text(encoding="utf-8"))


def _build_item_description(item_info: Dict[str, Any]) -> str:
    title = item_info.get("title") or item_info.get("desc") or "未命名商品"
    price = item_info.get("original_price") or item_info.get("price") or item_info.get("soldPrice") or ""
    return f"当前商品的信息如下：标题:{title} 价格:{price}元 详情: {json.dumps(item_info, ensure_ascii=False)}"


def _build_user_message(request: ReplyRequest) -> str:
    messages = [request.user_msg.strip()]
    messages.extend(message.strip() for message in request.additional_user_msgs if message.strip())
    batch = MessageBatch(
        chat_id=request.chat_id,
        item_id=request.item_id,
        user_id=request.user_id,
        messages=messages,
    )
    return batch.combined_text()


def _snapshot_to_response(snapshot) -> MemorySnapshotResponse:
    return MemorySnapshotResponse(
        chat_id=snapshot.chat_id,
        messages=snapshot.messages,
        bargain_count=snapshot.bargain_count,
        lowest_price_committed=snapshot.lowest_price_committed,
        buyer_highest_offer=snapshot.buyer_highest_offer,
    )


def _request_hash(request: ReplyRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"request_id"})
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _contains_fallback(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("status") == "fallback":
            return True
        return any(_contains_fallback(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_fallback(child) for child in value)
    return False


def create_app(
    offline_mode: Optional[bool] = None,
    db_path: Optional[str] = None,
    trace_path: Optional[str] = None,
    request_replay_path: Optional[str] = None,
    access_token: Optional[str] = None,
    runtime_status_path: Optional[str] = None,
) -> FastAPI:
    docs_enabled = _env_flag("API_DOCS_ENABLED", True)
    app = FastAPI(
        title="Falses Goofish GuardAgent API",
        version="0.4.0",
        description="Service API for local-first Xianyu / Goofish AI customer-service agent.",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
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
    app.state.request_replays = ApiRequestReplayStore(request_replay_path)
    # XianyuReplyBot exposes mutable last_intent/last_trace for legacy callers.
    # Keep one explicit service boundary until the core returns immutable decisions.
    app.state.decision_lock = RLock()
    app.state.offline_mode = use_offline_client
    app.state.access_token = (
        access_token if access_token is not None else os.getenv("API_ACCESS_TOKEN", "")
    ).strip()
    app.state.runtime_status_path = runtime_status_path or os.getenv("RUNTIME_STATUS_PATH")
    app.state.docs_enabled = docs_enabled
    bearer = HTTPBearer(auto_error=False)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def require_access(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    ) -> None:
        expected = app.state.access_token
        if not expected:
            return
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not secrets.compare_digest(credentials.credentials, expected)
        ):
            raise HTTPException(
                status_code=401,
                detail="invalid_or_missing_access_token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.middleware("http")
    async def add_operational_headers(request: Request, call_next):
        incoming_request_id = request.headers.get("X-Request-ID", "")
        request_id = (
            incoming_request_id
            if REQUEST_ID_PATTERN.fullmatch(incoming_request_id)
            else uuid.uuid4().hex
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path in {"/", "/admin"} or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
        return response

    @app.get("/", include_in_schema=False)
    @app.get("/admin", include_in_schema=False)
    def operator_console():
        index_path = STATIC_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=503, detail="operator_console_not_built")
        return FileResponse(index_path, media_type="text/html")

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "offline_mode": app.state.offline_mode}

    @app.get("/health/live")
    def liveness() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness():
        storage_paths = [
            Path(app.state.bot.db.db_path).parent,
            app.state.trace_store.path.parent,
            Path(app.state.request_replays.path).parent,
        ]
        storage_checks = []
        for storage_path in storage_paths:
            try:
                storage_path.mkdir(parents=True, exist_ok=True)
                storage_checks.append(os.access(storage_path, os.W_OK))
            except OSError:
                storage_checks.append(False)
        checks = [
            {
                "name": "agent_runtime",
                "ok": bool(app.state.bot.available_intents()),
                "detail": "Agent registry initialized",
            },
            {
                "name": "storage",
                "ok": all(storage_checks),
                "detail": "State directories are writable",
            },
            {
                "name": "operator_console",
                "ok": (STATIC_DIR / "index.html").is_file(),
                "detail": "Operator console assets are present",
            },
        ]
        ready = all(check["ok"] for check in checks)
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "offline_mode": app.state.offline_mode,
                "checks": checks,
            },
        )

    @app.get("/api/capabilities")
    def capabilities() -> Dict[str, Any]:
        bot: XianyuReplyBot = app.state.bot
        return {
            "intents": bot.available_intents(),
            "offline_mode": app.state.offline_mode,
            "extension_contract": "register_agent",
        }

    @app.get("/api/access")
    def access_policy() -> Dict[str, Any]:
        return {
            "token_required": bool(app.state.access_token),
            "docs_enabled": app.state.docs_enabled,
        }

    @app.get("/api/runtime-status")
    def runtime_status() -> Dict[str, Any]:
        return build_runtime_status_report(path=app.state.runtime_status_path)

    @app.get("/api/overview")
    def overview() -> Dict[str, Any]:
        bot: XianyuReplyBot = app.state.bot
        records = app.state.trace_store.tail(50)
        traces = [record.get("trace", {}) for record in records]
        fallback_count = sum(_contains_fallback(trace.get("model", {})) for trace in traces)
        return {
            "api": {
                "healthy": True,
                "offline_mode": app.state.offline_mode,
                "token_required": bool(app.state.access_token),
            },
            "worker": build_runtime_status_report(path=app.state.runtime_status_path),
            "agent": {
                "intents": bot.available_intents(),
                "intent_count": len(bot.available_intents()),
            },
            "traces": {
                "sample_size": len(records),
                "fallback_count": fallback_count,
                "guardrail_count": sum(bool(trace.get("guardrails")) for trace in traces),
                "last_recorded_at": records[-1].get("timestamp") if records else None,
            },
        }

    @app.post("/api/reply", response_model=ReplyResponse)
    def reply(
        request: ReplyRequest,
        _: None = Depends(require_access),
    ) -> ReplyResponse:
        bot: XianyuReplyBot = app.state.bot
        request_hash = _request_hash(request) if request.request_id else None

        with app.state.decision_lock:
            claimed_replay = False
            claim_token = None
            if request.request_id:
                try:
                    claim = app.state.request_replays.claim(request.request_id, request_hash)
                except RequestReplayConflict as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                if not claim.execute:
                    if claim.reason == "completed":
                        replayed = ReplyResponse.model_validate(claim.response)
                        replayed.idempotent_replay = True
                        return replayed
                    raise HTTPException(status_code=409, detail="request_id_in_progress")
                claimed_replay = True
                claim_token = claim.claim_token

            try:
                lease_context = (
                    app.state.request_replays.maintain_claim(
                        request.request_id,
                        request_hash,
                        claim_token,
                    )
                    if claimed_replay
                    else nullcontext(None)
                )
                with lease_context as replay_lease:
                    item_info = request.item_info or _load_default_item_info()
                    item_description = _build_item_description(item_info)
                    user_message = _build_user_message(request)
                    context = (
                        request.context
                        if request.context is not None
                        else bot.db.get_context_by_chat(request.chat_id)
                    )

                    bot_reply = bot.generate_reply(
                        user_message,
                        item_description,
                        context=context,
                        chat_id=request.chat_id,
                        item_id=request.item_id,
                        persist_memory=request.persist_turn,
                    )

                    if replay_lease:
                        replay_lease.assert_held()
                    if request.persist_turn:
                        bot.db.append_turn(
                            chat_id=request.chat_id,
                            user_id=request.user_id,
                            item_id=request.item_id,
                            user_text=user_message,
                            assistant_id=request.assistant_id,
                            assistant_text=None if bot_reply == "-" else bot_reply,
                            intent=bot.last_intent,
                        )

                    if replay_lease:
                        replay_lease.assert_held()
                    trace = bot.last_trace.to_dict()
                    app.state.trace_store.append(trace)
                    snapshot = bot.db.get_memory_snapshot(request.chat_id)
                    response = ReplyResponse(
                        request_id=request.request_id,
                        reply=bot_reply,
                        intent=bot.last_intent,
                        trace=trace,
                        memory=_snapshot_to_response(snapshot),
                    )
                    if claimed_replay:
                        app.state.request_replays.complete(
                            request.request_id,
                            request_hash,
                            claim_token,
                            response.model_dump(mode="json"),
                        )
                    return response
            except Exception as exc:
                if claimed_replay:
                    app.state.request_replays.fail(
                        request.request_id,
                        request_hash,
                        claim_token,
                        type(exc).__name__,
                    )
                raise

    @app.get("/api/memory/{chat_id}", response_model=MemorySnapshotResponse)
    def memory_snapshot(
        chat_id: str = ApiPath(..., min_length=1, max_length=128),
        _: None = Depends(require_access),
    ) -> MemorySnapshotResponse:
        return _snapshot_to_response(app.state.bot.db.get_memory_snapshot(chat_id))

    @app.get("/api/traces")
    def traces(
        limit: int = Query(20, ge=1, le=100),
        chat_id: Optional[str] = Query(None, min_length=1, max_length=128),
        intent: Optional[str] = Query(None, min_length=1, max_length=64),
        _: None = Depends(require_access),
    ) -> Dict[str, Any]:
        scan_limit = 500 if chat_id or intent else limit
        records = app.state.trace_store.tail(scan_limit)
        if chat_id:
            records = [
                record for record in records if record.get("trace", {}).get("chat_id") == chat_id
            ]
        if intent:
            records = [
                record for record in records if record.get("trace", {}).get("intent") == intent
            ]
        records = records[-limit:]
        return {"count": len(records), "items": records}

    return app


app = create_app()
