# -*- coding: utf-8 -*-
"""Authentication coverage for the Native Messaging bridge endpoint."""

# pylint: disable=protected-access,redefined-outer-name

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from qwenpaw.app.base_path import BasePathMiddleware
from qwenpaw.browser.control_link.chrome import ws_handler
from qwenpaw.browser.control_link.chrome.bridge import NMBridge


@pytest.mark.parametrize(
    ("base_path", "expected_path"),
    [("/app", "/app"), ("/my console", "/my%20console")],
)
def test_standalone_ws_url_uses_configured_base_path(
    monkeypatch,
    base_path: str,
    expected_path: str,
) -> None:
    monkeypatch.setattr("qwenpaw.app.base_path._server_base_path", None)
    monkeypatch.setattr(
        "qwenpaw.config.utils.read_last_api",
        lambda: ("127.0.0.1", 8088),
    )
    monkeypatch.setenv("QWENPAW_BASE_PATH", base_path)

    assert ws_handler.resolve_default_ws_url() == (
        f"ws://127.0.0.1:8088{expected_path}/api/ws/chrome"
    )


@pytest.fixture
def websocket_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(ws_handler.ws_router)
    monkeypatch.setattr(
        ws_handler,
        "_expected_token",
        lambda: "expected-token",
    )
    monkeypatch.setattr(ws_handler, "_default_bridge", lambda: None)
    monkeypatch.setattr(ws_handler, "get_nm_bridge", NMBridge)
    return TestClient(app)


@pytest.mark.p1
def test_nm_bridge_denies_wrong_token(websocket_client: TestClient) -> None:
    with pytest.raises(WebSocketDenialResponse) as denied:
        with websocket_client.websocket_connect(
            "/ws/chrome?token=wrong-token",
        ):
            pass

    assert denied.value.status_code == 401


@pytest.mark.p1
def test_nm_bridge_accepts_correct_token(websocket_client: TestClient) -> None:
    with websocket_client.websocket_connect("/ws/chrome?token=expected-token"):
        pass


@pytest.mark.p1
@pytest.mark.parametrize("base_path", ["/app", "/my console"])
def test_nm_bridge_accepts_correct_token_below_base_path(
    monkeypatch,
    base_path: str,
) -> None:
    app = FastAPI()
    app.add_middleware(BasePathMiddleware, base_path=base_path)
    app.include_router(ws_handler.ws_router, prefix="/api")
    monkeypatch.setattr("qwenpaw.app.base_path._server_base_path", base_path)
    monkeypatch.setattr(
        "qwenpaw.config.utils.read_last_api",
        lambda: ("127.0.0.1", 8088),
    )
    monkeypatch.setattr(
        ws_handler,
        "_expected_token",
        lambda: "expected-token",
    )
    monkeypatch.setattr(ws_handler, "_default_bridge", lambda: None)
    monkeypatch.setattr(ws_handler, "get_nm_bridge", NMBridge)

    ws_url = ws_handler.resolve_default_ws_url()
    with TestClient(app).websocket_connect(
        f"{ws_url}?token=expected-token",
    ):
        pass
