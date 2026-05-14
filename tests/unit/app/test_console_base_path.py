# -*- coding: utf-8 -*-
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app.console_base_path import (
    BasePathMiddleware,
    normalize_console_base_path,
)


def test_normalize_console_base_path_accepts_common_forms():
    assert normalize_console_base_path(None) == ""
    assert normalize_console_base_path("") == ""
    assert normalize_console_base_path("/") == ""
    assert normalize_console_base_path("copaw/test-001/") == "/copaw/test-001"
    assert (
        normalize_console_base_path("https://example.com/copaw/test-001/")
        == "/copaw/test-001"
    )


def test_normalize_console_base_path_rejects_traversal_segments():
    try:
        normalize_console_base_path("/copaw/../test")
    except ValueError as exc:
        assert "must not contain" in str(exc)
    else:
        raise AssertionError("expected invalid base path to raise")


def test_base_path_middleware_strips_prefix_for_route_matching():
    app = FastAPI()
    app.add_middleware(BasePathMiddleware, base_path="/copaw/test-001")

    @app.get("/api/version")
    def version(request: Request):
        return {
            "path": request.scope["path"],
            "root_path": request.scope["root_path"],
        }

    response = TestClient(app).get("/copaw/test-001/api/version")

    assert response.status_code == 200
    assert response.json() == {
        "path": "/api/version",
        "root_path": "/copaw/test-001",
    }


def test_base_path_middleware_requires_path_boundary():
    app = FastAPI()
    app.add_middleware(BasePathMiddleware, base_path="/copaw")

    @app.get("/api/version")
    def version():
        return {"ok": True}

    response = TestClient(app).get("/copawish/api/version")

    assert response.status_code == 404
