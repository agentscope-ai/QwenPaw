# -*- coding: utf-8 -*-
"""Unit tests for the local-models router endpoints."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers.local_models import router
from qwenpaw.local_models import LocalModelConfig
from qwenpaw.providers.provider import ModelInfo

app = FastAPI()
app.include_router(router, prefix="/api")


class _FakeLocalModelManager:
    def __init__(self) -> None:
        self._config = LocalModelConfig()
        self.set_max_context_length_calls: list[int] = []
        self.set_port_calls: list[int | None] = []

    async def set_max_context_length(self, value: int) -> None:
        self.set_max_context_length_calls.append(value)
        self._config.max_context_length = value

    async def set_port(self, value: int | None) -> None:
        self.set_port_calls.append(value)
        self._config.port = value

    def get_config(self) -> LocalModelConfig:
        return self._config


class _FakeProviderManager:
    def __init__(self, provider: Any | None = None) -> None:
        self._provider = provider
        self.update_provider_calls: list[tuple[str, dict]] = []

    def get_provider(self, provider_id: str) -> Any | None:
        if provider_id == "qwenpaw-local":
            return self._provider
        return None

    def update_provider(self, provider_id: str, config: dict) -> bool:
        self.update_provider_calls.append((provider_id, config))
        return True


def _make_fake_provider(
    extra_models: list[ModelInfo] | None = None,
) -> MagicMock:
    provider = MagicMock()
    provider.extra_models = extra_models if extra_models is not None else []
    return provider


def _setup_client(manager: _FakeLocalModelManager) -> AsyncClient:
    fake_provider = _make_fake_provider()
    fake_provider_manager = _FakeProviderManager(provider=fake_provider)
    app.state.local_model_manager = manager
    app.state.provider_manager = fake_provider_manager
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


# ── PUT /config ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_max_ctx_syncs_provider_input_len() -> None:
    manager = _FakeLocalModelManager()
    model = ModelInfo(
        id="local-model",
        name="local-model",
        probe_source="probed",
        max_input_length=131072,
    )
    fake_provider = _make_fake_provider(extra_models=[model])
    fake_provider_manager = _FakeProviderManager(provider=fake_provider)
    app.state.local_model_manager = manager
    app.state.provider_manager = fake_provider_manager
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    async with client:
        resp = await client.put(
            "/api/local-models/config",
            json={"max_context_length": 65536},
        )

    assert resp.status_code == 200
    assert manager.set_max_context_length_calls == [65536]
    assert model.max_input_length == 65536
    assert ("qwenpaw-local", {}) in fake_provider_manager.update_provider_calls


@pytest.mark.asyncio
async def test_configure_max_context_length_noop_when_no_provider() -> None:
    manager = _FakeLocalModelManager()
    fake_provider_manager = _FakeProviderManager(provider=None)
    app.state.local_model_manager = manager
    app.state.provider_manager = fake_provider_manager
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    async with client:
        resp = await client.put(
            "/api/local-models/config",
            json={"max_context_length": 65536},
        )

    assert resp.status_code == 200
    assert manager.set_max_context_length_calls == [65536]
    assert not fake_provider_manager.update_provider_calls


@pytest.mark.asyncio
async def test_config_max_ctx_syncs_multiple_extra_models() -> None:
    manager = _FakeLocalModelManager()
    models = [
        ModelInfo(
            id="model-a",
            name="model-a",
            probe_source="probed",
            max_input_length=131072,
        ),
        ModelInfo(
            id="model-b",
            name="model-b",
            probe_source="probed",
            max_input_length=131072,
        ),
    ]
    fake_provider = _make_fake_provider(extra_models=models)
    fake_provider_manager = _FakeProviderManager(provider=fake_provider)
    app.state.local_model_manager = manager
    app.state.provider_manager = fake_provider_manager
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    async with client:
        resp = await client.put(
            "/api/local-models/config",
            json={"max_context_length": 32768},
        )

    assert resp.status_code == 200
    assert all(m.max_input_length == 32768 for m in models)


@pytest.mark.asyncio
async def test_configure_port() -> None:
    manager = _FakeLocalModelManager()
    client = _setup_client(manager)

    async with client:
        resp = await client.put(
            "/api/local-models/config",
            json={"port": 43110},
        )

    assert resp.status_code == 200
    assert manager.set_port_calls == [43110]


@pytest.mark.asyncio
async def test_configure_generate_kwargs() -> None:
    manager = _FakeLocalModelManager()
    fake_provider = _make_fake_provider()
    fake_provider_manager = _FakeProviderManager(provider=fake_provider)
    app.state.local_model_manager = manager
    app.state.provider_manager = fake_provider_manager
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    async with client:
        resp = await client.put(
            "/api/local-models/config",
            json={"generate_kwargs": {"temperature": 0.7}},
        )

    assert resp.status_code == 200
    assert any(
        call[0] == "qwenpaw-local"
        and call[1] == {"generate_kwargs": {"temperature": 0.7}}
        for call in fake_provider_manager.update_provider_calls
    )


# ── GET /config ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_config() -> None:
    manager = _FakeLocalModelManager()
    client = _setup_client(manager)

    async with client:
        resp = await client.get("/api/local-models/config")

    assert resp.status_code == 200
    data = resp.json()
    assert "max_context_length" in data
    assert "port" in data
