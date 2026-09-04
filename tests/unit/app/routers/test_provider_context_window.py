# -*- coding: utf-8 -*-
"""Tests for active-model context-window metadata."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import providers as providers_router
from qwenpaw.app.routers.providers import (
    ModelConfigRequest,
    _active_models_info,
    configure_model,
)
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.exceptions import AgentConfigConflictError


def test_active_models_info_uses_runtime_context_resolution():
    provider = SimpleNamespace(get_context_size=lambda _model_id: 1_000_000)
    manager = SimpleNamespace(get_provider=lambda _provider_id: provider)
    slot = ModelSlotConfig(provider_id="dashscope", model="qwen3.7-max")

    info = _active_models_info(manager, slot)

    assert info.active_llm == slot
    assert info.effective_max_input_length == 1_000_000


async def test_configure_model_only_forwards_submitted_fields() -> None:
    captured = None

    async def update_model_config(**kwargs):
        nonlocal captured
        captured = kwargs
        return SimpleNamespace()

    manager = SimpleNamespace(update_model_config=update_model_config)

    await configure_model(
        manager=manager,
        provider_id="openai",
        model_id="gpt-test",
        body=ModelConfigRequest(max_tokens=4096),
    )

    assert captured == {
        "provider_id": "openai",
        "model_id": "gpt-test",
        "config": {"max_tokens": 4096},
    }


def _provider_manager(active_model):
    return SimpleNamespace(
        get_active_model=lambda: active_model,
        get_provider=lambda _provider_id: None,
    )


async def test_effective_model_falls_back_after_empty_agent_config(
    monkeypatch,
) -> None:
    global_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-global",
    )

    async def load_agent_model(_request, _agent_id):
        return None

    monkeypatch.setattr(
        providers_router,
        "_load_agent_model",
        load_agent_model,
    )

    result = await providers_router.get_active_models(
        request=SimpleNamespace(),
        manager=_provider_manager(global_model),
        scope="effective",
        agent_id="bot",
    )

    assert result.active_llm == global_model


async def test_effective_model_returns_503_for_agent_config_failure(
    monkeypatch,
) -> None:
    async def load_agent_model(_request, _agent_id):
        raise OSError("config unavailable")

    monkeypatch.setattr(
        providers_router,
        "_load_agent_model",
        load_agent_model,
    )

    with pytest.raises(HTTPException) as caught:
        await providers_router.get_active_models(
            request=SimpleNamespace(),
            manager=_provider_manager(None),
            scope="effective",
            agent_id="bot",
        )

    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "AGENT_CONFIG_UNAVAILABLE"


async def test_effective_model_preserves_agent_http_error(monkeypatch) -> None:
    async def load_agent_model(_request, _agent_id):
        raise HTTPException(status_code=404, detail="agent missing")

    monkeypatch.setattr(
        providers_router,
        "_load_agent_model",
        load_agent_model,
    )

    with pytest.raises(HTTPException) as caught:
        await providers_router.get_active_models(
            request=SimpleNamespace(),
            manager=_provider_manager(None),
            scope="effective",
            agent_id="bot",
        )

    assert caught.value.status_code == 404
    assert caught.value.detail == "agent missing"


async def test_effective_model_preserves_stale_config_error_code(
    monkeypatch,
) -> None:
    async def load_agent_model(_request, _agent_id):
        raise AgentConfigConflictError("bot")

    monkeypatch.setattr(
        providers_router,
        "_load_agent_model",
        load_agent_model,
    )

    with pytest.raises(HTTPException) as caught:
        await providers_router.get_active_models(
            request=SimpleNamespace(),
            manager=_provider_manager(None),
            scope="effective",
            agent_id="bot",
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "AGENT_CONFIG_STALE"
