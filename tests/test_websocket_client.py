import main as main_module
from main import XianyuLive


def test_websocket_connection_uses_modern_header_argument(monkeypatch):
    captured = {}
    expected_connection = object()

    def fake_connect(uri, **kwargs):
        captured["uri"] = uri
        captured["kwargs"] = kwargs
        return expected_connection

    monkeypatch.setattr(main_module, "websocket_connect", fake_connect)
    live = object.__new__(XianyuLive)
    live.base_url = "wss://example.test/"
    live.websocket_open_timeout = 7
    headers = {"Cookie": "unb=test"}

    connection = live.create_websocket_connection(headers)

    assert connection is expected_connection
    assert captured == {
        "uri": "wss://example.test/",
        "kwargs": {
            "additional_headers": headers,
            "open_timeout": 7,
            "ping_interval": None,
        },
    }
