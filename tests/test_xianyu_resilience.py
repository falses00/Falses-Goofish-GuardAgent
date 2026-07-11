import asyncio

import pytest
import requests

from XianyuApis import XianyuApis, XianyuAuthenticationError, XianyuTransientError
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

    token = asyncio.run(live.refresh_token())

    assert token == "fresh-token"
    assert live.authentication_error is None
