# -*- coding: utf-8 -*-
"""Tests for the managed-runtime network authentication boundary."""

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from qwenpaw.app.auth import RuntimeBoundaryMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RuntimeBoundaryMiddleware)

    @app.get("/api/value")
    async def value() -> dict[str, bool]:
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("ok")

    return app


def test_runtime_token_protects_all_http_paths(monkeypatch) -> None:
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "runtime-secret")
    with TestClient(_app()) as client:
        assert client.get("/api/value").status_code == 401
        allowed = client.get(
            "/api/value",
            headers={
                "X-QwenPaw-Runtime-Token": "runtime-secret",
            },
        )
        assert allowed.json() == {"ok": True}


def test_runtime_token_protects_websockets(monkeypatch) -> None:
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "runtime-secret")
    with TestClient(_app()) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass
        with client.websocket_connect(
            "/ws",
            headers={
                "X-QwenPaw-Runtime-Token": "runtime-secret",
            },
        ) as websocket:
            assert websocket.receive_text() == "ok"
