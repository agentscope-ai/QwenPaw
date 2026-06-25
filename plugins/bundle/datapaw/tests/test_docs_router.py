# -*- coding: utf-8 -*-
"""Tests for the DataPaw KG docs proxy router."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin_datapaw.constants import (
    DATAPAW_CM_BASE_URL_ENV,
    DEFAULT_DATAPAW_CM_BASE_URL,
)

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _load_router_module():
    """Load the docs router without importing ``core.routers.__init__``."""
    name = "plugin_datapaw.core.routers.docs"
    if name in sys.modules:
        return sys.modules[name]
    path = PLUGIN_DIR / "core" / "routers" / "docs.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RecordingAsyncClient:
    """Minimal httpx.AsyncClient replacement for proxy assertions."""

    calls: list[dict[str, Any]] = []
    init_kwargs: list[dict[str, Any]] = []
    response: httpx.Response = httpx.Response(
        200,
        json={"code": 0, "message": "success", "data": {}},
    )
    exception: Exception | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs.append(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        return None

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.exception is not None:
            raise self.exception
        return self.response


@pytest.fixture(autouse=True)
def reset_recording_client() -> None:
    RecordingAsyncClient.calls = []
    RecordingAsyncClient.init_kwargs = []
    RecordingAsyncClient.response = httpx.Response(
        200,
        json={"code": 0, "message": "success", "data": {}},
    )
    RecordingAsyncClient.exception = None


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    router_mod = _load_router_module()
    monkeypatch.setenv(DATAPAW_CM_BASE_URL_ENV, "http://cm.local/")
    monkeypatch.setattr(router_mod.httpx, "AsyncClient", RecordingAsyncClient)

    app = FastAPI()
    app.include_router(router_mod.router, prefix="/api/v1/docs")
    return TestClient(app)


def test_upload_proxies_multipart_to_cm(api_client: TestClient) -> None:
    payload = {
        "code": 0,
        "message": "success",
        "data": {
            "doc_id": "kg-docs/report.pdf",
            "filename": "report.pdf",
            "file_size": 5,
            "download_url": "https://oss.example/report.pdf",
        },
    }
    RecordingAsyncClient.response = httpx.Response(200, json=payload)

    resp = api_client.post(
        "/api/v1/docs/upload",
        files={"file": ("report.pdf", b"hello", "application/pdf")},
    )

    assert resp.status_code == 200
    assert resp.json() == payload
    assert len(RecordingAsyncClient.calls) == 1
    call = RecordingAsyncClient.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://cm.local/api/v1/docs/upload"
    assert call["headers"]["Content-Type"].startswith("multipart/form-data;")
    assert b'filename="report.pdf"' in call["content"]
    assert b"hello" in call["content"]


def test_list_docs_proxies_query_to_cm(api_client: TestClient) -> None:
    payload = {
        "code": 0,
        "message": "success",
        "data": {"list": [], "page": 2, "page_size": 50, "total": 0},
    }
    RecordingAsyncClient.response = httpx.Response(200, json=payload)

    resp = api_client.get("/api/v1/docs?page=2&page_size=50")

    assert resp.status_code == 200
    assert resp.json() == payload
    assert RecordingAsyncClient.calls[0]["method"] == "GET"
    assert (
        RecordingAsyncClient.calls[0]["url"]
        == "http://cm.local/api/v1/docs?page=2&page_size=50"
    )


def test_delete_doc_encodes_doc_id_path_param(api_client: TestClient) -> None:
    payload = {
        "code": 0,
        "message": "success",
        "data": {"doc_id": "kg-docs/report.pdf"},
    }
    RecordingAsyncClient.response = httpx.Response(200, json=payload)

    resp = api_client.delete("/api/v1/docs/kg-docs%2Freport.pdf")

    assert resp.status_code == 200
    assert resp.json() == payload
    assert RecordingAsyncClient.calls[0]["method"] == "DELETE"
    assert (
        RecordingAsyncClient.calls[0]["url"]
        == "http://cm.local/api/v1/docs/kg-docs%2Freport.pdf"
    )


def test_cm_business_error_is_passthrough(api_client: TestClient) -> None:
    payload = {"code": 40901, "message": "doc_already_exists", "data": None}
    RecordingAsyncClient.response = httpx.Response(409, json=payload)

    resp = api_client.post(
        "/api/v1/docs/upload",
        files={"file": ("report.pdf", b"hello", "application/pdf")},
    )

    assert resp.status_code == 409
    assert resp.json() == payload


def test_missing_cm_base_url_uses_default(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATAPAW_CM_BASE_URL_ENV, raising=False)

    resp = api_client.get("/api/v1/docs")

    assert resp.status_code == 200
    assert RecordingAsyncClient.calls[0]["method"] == "GET"
    assert (
        RecordingAsyncClient.calls[0]["url"]
        == f"{DEFAULT_DATAPAW_CM_BASE_URL}/api/v1/docs"
    )


def test_cm_network_error_returns_proxy_error(api_client: TestClient) -> None:
    RecordingAsyncClient.exception = httpx.ConnectError("connect failed")

    resp = api_client.get("/api/v1/docs")

    assert resp.status_code == 500
    assert resp.json() == {"code": 50001, "message": "server_error", "data": None}


def test_cm_non_json_response_returns_proxy_error(api_client: TestClient) -> None:
    RecordingAsyncClient.response = httpx.Response(502, content=b"bad gateway")

    resp = api_client.get("/api/v1/docs")

    assert resp.status_code == 500
    assert resp.json() == {"code": 50001, "message": "server_error", "data": None}


def test_plugin_registers_docs_router() -> None:
    from plugin_datapaw.plugin import DataPawPlugin

    class FakeApi:
        http_routers: list[dict[str, Any]]

        def __init__(self) -> None:
            self.http_routers = []

        def register_startup_hook(self, **_kwargs: Any) -> None:
            return None

        def register_shutdown_hook(self, **_kwargs: Any) -> None:
            return None

        def register_uninstall_hook(self, **_kwargs: Any) -> None:
            return None

        def register_http_router(
            self,
            router: Any,
            *,
            prefix: str,
            tags: list[str],
        ) -> None:
            self.http_routers.append(
                {"router": router, "prefix": prefix, "tags": tags}
            )

        def register_skill_provider(self, **_kwargs: Any) -> None:
            return None

        def register_prompt_section(self, **_kwargs: Any) -> None:
            return None

    api = FakeApi()
    DataPawPlugin().register(api)

    assert any(
        item["prefix"] == "/v1/docs" and item["tags"] == ["datapaw-docs"]
        for item in api.http_routers
    )
