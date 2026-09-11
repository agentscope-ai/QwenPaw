# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Load-time validation of the qwenpaw-data context-service configuration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAIN_FILE = (
    REPOSITORY_ROOT
    / "plugins"
    / "apps"
    / "qwenpaw-data"
    / "backend"
    / "main.py"
)


@pytest.fixture(scope="module")
def backend():
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_data_main_runtime_validation",
        MAIN_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_context_env(monkeypatch):
    for name in (
        "QWENPAW_DATA_CONTEXT_MODE",
        "QWENPAW_DATA_CONTEXT_URL",
        "QWENPAW_DATA_CONTEXT_TOKEN",
        "QWENPAW_DATA_MODEL_PROVIDER",
        "QWENPAW_DATA_MODEL_NAME",
        "QWENPAW_DATA_MODEL_API_KEY",
        "QWENPAW_DATA_MODEL_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_external_mode_with_url_and_token_is_valid(
    backend,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QWENPAW_DATA_CONTEXT_MODE", "external")
    monkeypatch.setenv("QWENPAW_DATA_CONTEXT_URL", "http://127.0.0.1:8300")
    monkeypatch.setenv("QWENPAW_DATA_CONTEXT_TOKEN", "secret")

    assert backend._context_runtime_issue() is None


def test_external_mode_without_endpoint_reports_missing_vars(
    backend,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QWENPAW_DATA_CONTEXT_MODE", "external")

    issue = backend._context_runtime_issue()

    assert issue is not None
    assert issue["code"] == "EXTERNAL_MODE_INCOMPLETE"
    assert "QWENPAW_DATA_CONTEXT_URL" in issue["message"]
    assert "QWENPAW_DATA_CONTEXT_TOKEN" in issue["message"]
    assert issue["remediation"]


def test_external_url_without_token_reports_the_token(
    backend,
    monkeypatch,
) -> None:
    # Setting the URL alone selects external mode implicitly.
    monkeypatch.setenv("QWENPAW_DATA_CONTEXT_URL", "http://127.0.0.1:8300")

    issue = backend._context_runtime_issue()

    assert issue is not None
    assert issue["code"] == "EXTERNAL_MODE_INCOMPLETE"
    assert "QWENPAW_DATA_CONTEXT_TOKEN" in issue["message"]
    assert "QWENPAW_DATA_CONTEXT_URL" not in issue["message"]


def test_managed_mode_without_runtime_reports_runtime_missing(
    backend,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        backend._context_service,
        "runtime_available",
        lambda: False,
    )

    issue = backend._context_runtime_issue()

    assert issue is not None
    assert issue["code"] == "RUNTIME_MISSING"
    assert "QWENPAW_DATA_CONTEXT_MODE=external" in issue["remediation"]


def test_managed_mode_with_runtime_is_valid(backend, monkeypatch) -> None:
    monkeypatch.setattr(
        backend._context_service,
        "runtime_available",
        lambda: True,
    )

    assert backend._context_runtime_issue() is None


@pytest.mark.asyncio
async def test_engine_start_replaces_then_clears_model_environment(
    backend,
    monkeypatch,
    tmp_path: Path,
) -> None:
    class _UnavailableContextService:
        is_external = False

        @property
        def base_url(self) -> str:
            raise RuntimeError("not started")

    llm = SimpleNamespace(
        provider="test-provider",
        model="test-model",
        api_key="test-api-key",
        base_url="https://model.invalid/v1",
    )
    monkeypatch.setattr(backend, "ENGINE_HOME", tmp_path / "engine")
    monkeypatch.setattr(
        backend,
        "_context_service",
        _UnavailableContextService(),
    )
    monkeypatch.setattr(
        backend,
        "load_config",
        lambda: SimpleNamespace(llm=llm),
    )
    for name in (
        "QWENPAW_DATA_MODEL_PROVIDER",
        "QWENPAW_DATA_MODEL_NAME",
        "QWENPAW_DATA_MODEL_API_KEY",
        "QWENPAW_DATA_MODEL_BASE_URL",
    ):
        monkeypatch.setenv(name, "stale-value")

    await backend._engine_before_start()

    assert backend.os.environ["QWENPAW_DATA_MODEL_PROVIDER"] == "test-provider"
    assert backend.os.environ["QWENPAW_DATA_MODEL_NAME"] == "test-model"
    assert backend.os.environ["QWENPAW_DATA_MODEL_API_KEY"] == "test-api-key"
    assert (
        backend.os.environ["QWENPAW_DATA_MODEL_BASE_URL"]
        == "https://model.invalid/v1"
    )

    llm.provider = ""
    llm.model = ""
    llm.api_key = ""
    llm.base_url = ""
    await backend._engine_before_start()

    assert all(
        name not in backend.os.environ
        for name in (
            "QWENPAW_DATA_MODEL_PROVIDER",
            "QWENPAW_DATA_MODEL_NAME",
            "QWENPAW_DATA_MODEL_API_KEY",
            "QWENPAW_DATA_MODEL_BASE_URL",
        )
    )


@pytest.mark.asyncio
async def test_stop_gateway_closes_all_http_clients(
    backend,
    monkeypatch,
) -> None:
    context_stop = AsyncMock()
    engine_stop = AsyncMock()
    bridge_close = AsyncMock()
    monkeypatch.setattr(backend._gateway, "stop", context_stop)
    monkeypatch.setattr(backend._engine_gateway, "stop", engine_stop)
    monkeypatch.setattr(backend._bridge_client, "aclose", bridge_close)

    await backend._stop_gateway()

    context_stop.assert_awaited_once_with()
    engine_stop.assert_awaited_once_with()
    bridge_close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_stop_gateway_closes_remaining_clients_after_failure(
    backend,
    monkeypatch,
) -> None:
    context_stop = AsyncMock(side_effect=RuntimeError("stop failed"))
    engine_stop = AsyncMock()
    bridge_close = AsyncMock()
    monkeypatch.setattr(backend._gateway, "stop", context_stop)
    monkeypatch.setattr(backend._engine_gateway, "stop", engine_stop)
    monkeypatch.setattr(backend._bridge_client, "aclose", bridge_close)

    with pytest.raises(RuntimeError, match="stop failed"):
        await backend._stop_gateway()

    context_stop.assert_awaited_once_with()
    engine_stop.assert_awaited_once_with()
    bridge_close.assert_awaited_once_with()
