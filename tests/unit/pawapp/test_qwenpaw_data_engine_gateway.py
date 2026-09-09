# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GATEWAY_FILE = (
    REPOSITORY_ROOT
    / "plugins"
    / "apps"
    / "qwenpaw-data"
    / "backend"
    / "engine_gateway.py"
)


def _gateway_module():
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_data_engine_gateway_under_test",
        GATEWAY_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gateway_class():
    return _gateway_module().EngineGateway


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/api/v1/sessions",
        "/api/v1/sessions/ses_1/chats",
        "/api/v1/sessions/ses_1/chats/chat_1/events",
        "/api/v1/sessions/ses_1/chats/chat_1/clarification/answer",
        "/api/v1/cron/jobs",
    ],
)
def test_engine_gateway_allows_declared_routes(path: str) -> None:
    _gateway_class()._validate_path(path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("api/v1/sessions", "/api/v1/sessions"),
        ("health", "/health"),
        ("api/v1/%73essions", "/api/v1/sessions"),
        (
            "api/v1/sessions/ses_1/chats/chat_1/events",
            "/api/v1/sessions/ses_1/chats/chat_1/events",
        ),
    ],
)
def test_engine_gateway_normalizes_paths(path: str, expected: str) -> None:
    assert _gateway_class()._upstream_path(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api",
        "/api/v2/sessions",
        "/metrics",
        "/api/v1/../secrets",
        "/api/v1/%2e%2e/secrets",
        "/api/v1/%252e%252e/secrets",
        "/api/v1/sessions?x=1",
        "/api/v1/sessions#frag",
        "/api/v1/sess\\ions",
        "/api/v1//sessions",
        "/api/v1/session name",
        "/api/v1/session%2520name",
        "/api/v1/session\x00name",
        "/api/v1/session%250aname",
    ],
)
def test_engine_gateway_rejects_undeclared_or_escaped_paths(path: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _gateway_class()._validate_path(path)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/%252e%252e/secrets",
        "/api/v1/sessions?redirect=/health",
    ],
)
def test_engine_gateway_rejects_unsafe_path_before_request_build(
    path: str,
) -> None:
    gateway = _gateway_class()(
        SimpleNamespace(is_external=False, base_url="http://127.0.0.1:9"),
        "managed-token",
    )

    with pytest.raises(HTTPException) as exc:
        gateway._build_request("GET", path)

    assert exc.value.status_code == 404


def test_engine_gateway_rejects_long_invalid_path() -> None:
    path = "/api/v1/" + "a" * 100_000 + "%2520x"
    with pytest.raises(HTTPException) as exc:
        _gateway_class()._validate_path(path)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/system/channel-config",
        "/api/v1/system/channel-config/",
        "/api/v1/system/channel-config/dingtalk",
        "/api/v1/system/channel-config/wechat/qrcode",
        "/api/v1/channels/reload",
    ],
)
def test_engine_gateway_denies_channel_management_routes(path: str) -> None:
    # The QwenPaw host owns channel delivery; the engine's own channel
    # management surface must stay unreachable through the plugin.
    with pytest.raises(HTTPException) as exc:
        _gateway_class()._validate_path(path)
    assert exc.value.status_code == 404


def test_sse_path_detection() -> None:
    module = _gateway_module()
    assert module._SSE_PATH_RE.search("/api/v1/sessions/s1/chats/c1/events")
    assert module._SSE_PATH_RE.search("/api/v1/sessions/s1/chats/c1/events/")
    assert not module._SSE_PATH_RE.search("/api/v1/sessions/s1/chats")
    assert not module._SSE_PATH_RE.search("/api/v1/sessions/s1/chats/c1/steer")


def test_managed_token_used_for_managed_service(monkeypatch) -> None:
    monkeypatch.delenv("QWENPAW_DATA_ENGINE_TOKEN", raising=False)
    gateway_cls = _gateway_class()
    gateway = gateway_cls(
        SimpleNamespace(is_external=False, base_url="http://127.0.0.1:9"),
        "managed-token",
    )
    import httpx

    gateway._client = httpx.AsyncClient()
    request = gateway._build_request("GET", "/api/v1/sessions")
    assert request.headers["Authorization"] == "Bearer managed-token"


def test_external_token_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("QWENPAW_DATA_ENGINE_TOKEN", "external-token")
    gateway_cls = _gateway_class()
    gateway = gateway_cls(
        SimpleNamespace(is_external=True, base_url="http://engine.example"),
        "managed-token",
    )
    import httpx

    gateway._client = httpx.AsyncClient()
    request = gateway._build_request("GET", "/api/v1/sessions")
    assert request.headers["Authorization"] == "Bearer external-token"


def test_unready_service_maps_to_503() -> None:
    gateway_cls = _gateway_class()

    class _NotReady:
        is_external = False

        @property
        def base_url(self) -> str:
            raise RuntimeError("not started")

    gateway = gateway_cls(_NotReady(), "managed-token")
    import httpx

    gateway._client = httpx.AsyncClient()
    with pytest.raises(HTTPException) as exc:
        gateway._build_request("GET", "/api/v1/sessions")
    assert exc.value.status_code == 503
