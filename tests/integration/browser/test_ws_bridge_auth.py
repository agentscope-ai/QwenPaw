# -*- coding: utf-8 -*-
"""Authentication coverage for the Native Messaging bridge endpoint."""

# pylint: disable=protected-access,redefined-outer-name

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from qwenpaw.browser.control_link.chrome import ws_handler
from qwenpaw.browser.control_link.chrome.bridge import NMBridge


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
