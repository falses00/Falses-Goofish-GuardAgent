import asyncio
import time

import pytest
import requests

from XianyuApis import XianyuApis, XianyuAuthenticationError, XianyuTransientError
from core.runtime_status import NullRuntimeStatusStore
from main import XianyuLive


def test_login_network_failure_is_transient_and_bounded(monkeypatch):
    api = XianyuApis()
    api.retry_delay_seconds = 0
    calls = 0

    def fail_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise requests.ConnectionError("dns unavailable")

    monkeypatch.setattr(api.session, "post", fail_request)

    with pytest.raises(XianyuTransientError, match="暂态网络错误"):
        api.hasLogin()

    assert calls == api.login_check_max_attempts


def test_token_network_failure_does_not_probe_or_invalidate_login(monkeypatch):
    api = XianyuApis()
    api.retry_delay_seconds = 0
    calls = 0

    def fail_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise requests.ConnectTimeout("upstream timeout")

    def unexpected_login_probe(*args, **kwargs):
        pytest.fail("transient token failures must not be treated as expired cookies")

    monkeypatch.setattr(api.session, "post", fail_request)
    monkeypatch.setattr(api, "hasLogin", unexpected_login_probe)

    with pytest.raises(XianyuTransientError, match="连续网络请求失败"):
        api.get_token("device")

    assert calls == api.token_request_max_attempts


def test_relogin_cycle_is_bounded(monkeypatch):
    class ExpiredResponse:
        headers = {}

        @staticmethod
        def json():
            return {"ret": ["FAIL_SYS_SESSION_EXPIRED::Session过期"]}

    api = XianyuApis()
    api.retry_delay_seconds = 0
    request_calls = 0
    login_calls = 0

    def expired_request(*args, **kwargs):
        nonlocal request_calls
        request_calls += 1
        return ExpiredResponse()

    def successful_login_probe(*args, **kwargs):
        nonlocal login_calls
        login_calls += 1
        return True

    monkeypatch.setattr(api.session, "post", expired_request)
    monkeypatch.setattr(api, "hasLogin", successful_login_probe)

    with pytest.raises(XianyuAuthenticationError, match="重新登录后"):
        api.get_token("device")

    assert login_calls == 1
    assert request_calls == api.token_request_max_attempts * 2


def test_successful_refresh_clears_stale_authentication_error():
    class SuccessfulTokenApi:
        @staticmethod
        def get_token(device_id):
            return {"data": {"accessToken": "fresh-token"}}

    live = object.__new__(XianyuLive)
    live.xianyu = SuccessfulTokenApi()
    live.device_id = "device"
    live.current_token = None
    live.last_token_refresh_time = 0
    live.authentication_error = XianyuAuthenticationError("stale")
    live.runtime_status = NullRuntimeStatusStore()
    live.xianyu_api_lock = asyncio.Lock()

    token = asyncio.run(live.refresh_token())

    assert token == "fresh-token"
    assert live.authentication_error is None


def test_token_refresh_does_not_block_event_loop():
    class SlowTokenApi:
        @staticmethod
        def get_token(device_id):
            time.sleep(0.1)
            return {"data": {"accessToken": "fresh-token"}}

    async def scenario():
        live = object.__new__(XianyuLive)
        live.xianyu = SlowTokenApi()
        live.device_id = "device"
        live.current_token = None
        live.last_token_refresh_time = 0
        live.authentication_error = None
        live.runtime_status = NullRuntimeStatusStore()
        live.xianyu_api_lock = asyncio.Lock()

        refresh_task = asyncio.create_task(live.refresh_token())
        await asyncio.sleep(0.01)
        event_loop_remained_responsive = not refresh_task.done()
        token = await refresh_task
        return event_loop_remained_responsive, token

    responsive, token = asyncio.run(scenario())

    assert responsive is True
    assert token == "fresh-token"


def test_connection_retry_uses_bounded_exponential_backoff():
    live = object.__new__(XianyuLive)
    live.connection_retry_base_seconds = 2
    live.connection_retry_max_seconds = 10
    live.connection_retry_jitter_ratio = 0

    assert [live.calculate_connection_retry_delay(attempt) for attempt in range(1, 6)] == [
        2,
        4,
        8,
        10,
        10,
    ]


def test_heartbeat_timeout_closes_connection_and_marks_status():
    class RecordingStatus:
        def __init__(self):
            self.updates = []

        def update(self, state=None, **fields):
            self.updates.append((state, fields))
            return {}

    class FakeWebSocket:
        def __init__(self):
            self.closed = None

        async def close(self, **kwargs):
            self.closed = kwargs

    live = object.__new__(XianyuLive)
    live.heartbeat_interval = 15
    live.heartbeat_timeout = 5
    now = time.time()
    live.last_heartbeat_time = now
    live.last_heartbeat_response = now - 21
    live.runtime_status = RecordingStatus()
    websocket = FakeWebSocket()

    asyncio.run(live.heartbeat_loop(websocket))

    assert websocket.closed == {"code": 1011, "reason": "heartbeat timeout"}
    assert live.runtime_status.updates[-1] == (
        "heartbeat_timeout",
        {"last_error_type": "heartbeat_timeout"},
    )
