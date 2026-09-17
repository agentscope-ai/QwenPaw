# -*- coding: utf-8 -*-
"""Browser grants must follow runtime route ownership, not URL spelling."""

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.auth import RuntimeBoundaryMiddleware
from qwenpaw.plugins.browser_access import PAWAPP_SCOPE_HEADER
from qwenpaw.plugins.registry import PluginRegistry


def test_scoped_cookie_cannot_read_core_or_another_app(monkeypatch):
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "boundary")
    app = FastAPI()
    app.add_middleware(RuntimeBoundaryMiddleware)
    registry = PluginRegistry()
    registry.set_plugin_http_app(app)
    app.state.plugin_registry = registry

    @app.get("/api/agents/core")
    def core():
        return {"core": True}

    router = APIRouter()

    @router.get("/value")
    def value():
        return {"value": True}

    @router.post("/value")
    def write_value():
        return {"write": True}

    registry.register_plugin_manifest(
        "my_app",
        {"meta": {"pawapp": {"name": "App"}}},
    )
    registry.register_http_router("my_app", router, prefix="/agents")
    registry.register_http_router("other_app", router, prefix="/other")
    headers = {
        "X-QwenPaw-Runtime-Token": "boundary",
        PAWAPP_SCOPE_HEADER: "my_app",
    }
    with TestClient(app) as client:
        assert (
            client.get("/api/agents/value", headers=headers).status_code == 200
        )
        assert (
            client.get("/api/agents/core", headers=headers).status_code == 401
        )
        assert (
            client.get("/api/other/value", headers=headers).status_code == 401
        )
        assert (
            client.post("/api/agents/value", headers=headers).status_code
            == 401
        )
        registry.unregister_plugin("my_app")
        assert (
            client.get("/api/agents/value", headers=headers).status_code == 401
        )


def test_core_route_collision_is_not_owned_by_plugin(monkeypatch):
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "boundary")
    app = FastAPI()
    app.add_middleware(RuntimeBoundaryMiddleware)
    registry = PluginRegistry()
    registry.set_plugin_http_app(app)
    app.state.plugin_registry = registry

    @app.get("/api/agents/value")
    def core():
        return {"core": True}

    router = APIRouter()
    router.add_api_route("/value", lambda: {"app": True})
    registry.register_plugin_manifest(
        "agents",
        {"meta": {"pawapp": {"name": "App"}}},
    )
    registry.register_http_router("agents", router, prefix="/agents")
    with TestClient(app) as client:
        response = client.get(
            "/api/agents/value",
            headers={
                "X-QwenPaw-Runtime-Token": "boundary",
                PAWAPP_SCOPE_HEADER: "agents",
            },
        )
        assert response.status_code == 401
