# -*- coding: utf-8 -*-
"""Token rotation recovery coverage for the Native Messaging bridge."""

# pylint: disable=protected-access,redefined-outer-name

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from qwenpaw.browser.control_link.chrome import ws_handler
from qwenpaw.browser.control_link.chrome.bridge import NMBridge


def _write_config(config_path: Path, token: str) -> None:
    config_path.write_text(
        json.dumps(
            {"ws_url": "ws://127.0.0.1:8088/api/ws/chrome", "token": token},
        ),
        encoding="utf-8",
    )


@pytest.fixture
def bridge_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    config_path = tmp_path / "nm-bridge.json"
    monkeypatch.setattr(ws_handler, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(ws_handler._bridge_state, "token", None)
    monkeypatch.setattr(ws_handler._bridge_state, "config_path", config_path)
    return config_path


@pytest.mark.p1
def test_rotation_recovers(bridge_config: Path) -> None:
    _write_config(bridge_config, "token-a")
    assert ws_handler._expected_token() == "token-a"
    _write_config(bridge_config, "token-b")  # plugin repair(reset) rotates
    assert ws_handler._expected_token() == "token-b"


@pytest.mark.p1
def test_missing_file_falls_back_to_cache(bridge_config: Path) -> None:
    _write_config(bridge_config, "token-a")
    assert ws_handler._expected_token() == "token-a"
    bridge_config.unlink()
    assert ws_handler._expected_token() == "token-a"
    assert not bridge_config.exists()  # fallback must not rewrite or rotate


@pytest.mark.p1
def test_bootstrap_generates_once(bridge_config: Path) -> None:
    token = ws_handler._expected_token()
    assert token
    stored = json.loads(bridge_config.read_text(encoding="utf-8"))
    assert stored["token"] == token
    assert ws_handler._expected_token() == token


@pytest.fixture
def websocket_client(
    monkeypatch: pytest.MonkeyPatch,
    bridge_config: Path,
) -> TestClient:
    del bridge_config  # ensure the bridge-config fixture is initialized
    app = FastAPI()
    app.include_router(ws_handler.ws_router)
    monkeypatch.setattr(ws_handler, "_default_bridge", lambda: None)
    monkeypatch.setattr(ws_handler, "get_nm_bridge", NMBridge)
    return TestClient(app)


@pytest.mark.p1
def test_ws_handshake_after_rotation(
    websocket_client: TestClient,
    bridge_config: Path,
) -> None:
    _write_config(bridge_config, "token-a")
    with websocket_client.websocket_connect("/ws/chrome?token=token-a"):
        pass  # first handshake caches token-a in _bridge_state
    _write_config(bridge_config, "token-b")
    with pytest.raises(WebSocketDenialResponse) as denied:
        with websocket_client.websocket_connect("/ws/chrome?token=token-a"):
            pass
    assert denied.value.status_code == 401
    with websocket_client.websocket_connect("/ws/chrome?token=token-b"):
        pass
