# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GATEWAY_FILE = (
    REPOSITORY_ROOT
    / "plugins"
    / "apps"
    / "qwenpaw-data"
    / "backend"
    / "context_gateway.py"
)


def _gateway_module():
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_data_context_gateway_under_test",
        GATEWAY_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gateway_class():
    return _gateway_module().ContextGateway


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/v1/cm/datasources",
        "/api/system/model-config",
        "/api/semantic-config/domains",
    ],
)
def test_context_gateway_allows_declared_routes(path: str) -> None:
    _gateway_class()._validate_path(path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("v1/cm/datasources", "/api/v1/cm/datasources"),
        ("semantic-config/metric-lib", "/api/semantic-config/metric-lib"),
        ("api/v1/cm/datasources", "/api/v1/cm/datasources"),
        ("api/semantic-config/metric-lib", "/api/semantic-config/metric-lib"),
    ],
)
def test_context_gateway_accepts_ui_and_cli_path_shapes(
    path: str,
    expected: str,
) -> None:
    assert _gateway_class()._proxy_upstream_path(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/api/healthcheck",
        "/api/v10/private",
        "/api/v1/../private",
        "/api/v1/%2e%2e/private",
        "/api/v1/%252e%252e/private",
        # Four to seven encode layers: within the eight decode passes shared
        # with the frontend scope guard.
        "/api/v1/%25252525252e%25252525252e/private",
        # Still not at a fixed point after eight passes: rejected outright.
        "/api/v1/%" + "25" * 8 + "2e/private",
        "/api/v1/%2F..%2Fprivate",
        "/api/v1/private?token=leak",
        "/api/v1\\private",
    ],
)
def test_context_gateway_rejects_boundary_and_traversal_paths(
    path: str,
) -> None:
    with pytest.raises(HTTPException) as error:
        _gateway_class()._validate_path(path)
    assert error.value.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/auth/status",
        "/api/v1/cm/datasources",
        "/api/system/model-config",
        # The Context service mounts its config listing at "/".
        "/api/system/model-config/",
        "/api/system/model-config/llm/test",
        "/api/semantic-config/domains",
        "/api/datasources/active",
        "/api/v1/cm/datasources/6f9a2b1e-0c4d-4e5f-9a8b-1c2d3e4f5a6b",
        "/api/system/model-config/models/qwen3.8-max",
        # Non-ASCII and percent-encoded segments are structurally fine;
        # semantics stay _validate_path's job.
        "/api/semantic-config/metric-lib/销售额",
        "/api/v1/x%20y",
    ],
)
def test_plain_path_guard_allows_forwarded_routes(path: str) -> None:
    assert _gateway_module()._CONTEXT_PATH_RE.fullmatch(path)


@pytest.mark.parametrize(
    "path",
    [
        "/api/secret",
        "/api/v1/private?token=leak",
        "/api/v1/x#frag",
        # Empty segment.
        "/api/v1//x",
        "/api/v1\\private",
        # Control characters cannot reach the URL.
        "/api/v1/x\ty",
    ],
)
def test_plain_path_guard_rejects_path_escape_characters(
    path: str,
) -> None:
    assert not _gateway_module()._CONTEXT_PATH_RE.fullmatch(path)


def test_send_rejects_traversal_path_before_dispatch() -> None:
    # Structurally plain, but _validate_path rejects the traversal
    # segment before any client is touched.
    gateway = _gateway_class()(service=object(), managed_token="")
    with pytest.raises(HTTPException) as error:
        asyncio.run(gateway._send("GET", "/api/v1/../private"))
    assert error.value.status_code == 404


def test_send_maps_not_ready_runtime_error_to_structured_503() -> None:
    # The startup hook can leave a live client behind while the managed
    # service is still booting; base_url then raises RuntimeError, which
    # must surface as the structured 503, never a bare framework 500.
    class _NotReadyService:
        is_external = False

        @property
        def base_url(self):
            raise RuntimeError("managed service context is not ready")

    gateway = _gateway_class()(
        service=_NotReadyService(),
        managed_token="token",
    )
    gateway._client = SimpleNamespace(request=AsyncMock())
    with pytest.raises(HTTPException) as error:
        asyncio.run(gateway._send("GET", "/api/health"))
    assert error.value.status_code == 503
    assert error.value.detail == "Context service is unavailable"
