from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient

from copaw.app._app import BaseURLPrefixMiddleware, _normalize_base_url


def test_normalize_base_url_supports_path_and_full_url() -> None:
    assert _normalize_base_url("") == ""
    assert _normalize_base_url("   ") == ""
    assert _normalize_base_url("copaw/user1") == "/copaw/user1"
    assert _normalize_base_url("/copaw/user1/") == "/copaw/user1"
    assert _normalize_base_url("https://a.c.com/copaw/user1/") == "/copaw/user1"


def test_http_request_under_prefix_is_rewritten_with_root_path() -> None:
    app = FastAPI()
    app.add_middleware(BaseURLPrefixMiddleware, prefix="/copaw/u1")

    @app.get("/api/version")
    def version(request: Request) -> dict:
        return {
            "path": request.scope.get("path"),
            "root_path": request.scope.get("root_path"),
        }

    client = TestClient(app)
    response = client.get("/copaw/u1/api/version")

    assert response.status_code == 200
    assert response.json() == {"path": "/api/version", "root_path": "/copaw/u1"}


def test_http_request_outside_prefix_returns_404() -> None:
    app = FastAPI()
    app.add_middleware(BaseURLPrefixMiddleware, prefix="/copaw/u1")

    @app.get("/api/version")
    def version() -> dict:
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/api/version")

    assert response.status_code == 404


def test_websocket_request_under_prefix_is_rewritten() -> None:
    app = FastAPI()
    app.add_middleware(BaseURLPrefixMiddleware, prefix="/copaw/u1")

    @app.websocket("/voice/ws")
    async def voice_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("ok")
        await websocket.close()

    client = TestClient(app)
    with client.websocket_connect("/copaw/u1/voice/ws") as websocket:
        assert websocket.receive_text() == "ok"
