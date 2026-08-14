# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GATEWAY_FILE = (
    REPOSITORY_ROOT
    / "plugins"
    / "apps"
    / "datapaw"
    / "backend"
    / "context_gateway.py"
)


def _gateway_class():
    spec = importlib.util.spec_from_file_location(
        "datapaw_context_gateway_under_test",
        GATEWAY_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ContextGateway


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
