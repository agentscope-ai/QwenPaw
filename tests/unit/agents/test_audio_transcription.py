# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import copaw.agents.utils.audio_transcription as audio_transcription_module
import copaw.app.routers.agent as agent_router_module
from copaw.providers.ollama_provider import OllamaProvider
from copaw.providers.openai_provider import OpenAIProvider


def test_list_transcription_providers_marks_unavailable_entries(monkeypatch):
    manager = SimpleNamespace(
        builtin_providers={
            "openai": OpenAIProvider(
                id="openai",
                name="OpenAI",
                base_url="https://api.openai.com/v1",
                api_key="",
            ),
            "ollama": OllamaProvider(
                id="ollama",
                name="Ollama",
                base_url="http://127.0.0.1:11434",
                api_key="",
            ),
        },
        custom_providers={},
    )

    monkeypatch.setattr(
        audio_transcription_module,
        "_get_manager",
        lambda: manager,
    )

    providers = audio_transcription_module.list_transcription_providers()

    assert providers == [
        {
            "id": "openai",
            "name": "OpenAI",
            "available": False,
        },
        {
            "id": "ollama",
            "name": "Ollama",
            "available": True,
        },
    ]


@pytest.mark.asyncio
async def test_put_transcription_provider_rejects_unknown_provider(
    monkeypatch,
):
    config = SimpleNamespace(
        agents=SimpleNamespace(
            transcription_provider_type="whisper_api",
            transcription_provider_id="",
        ),
    )

    saved_ids: list[str] = []

    monkeypatch.setattr(agent_router_module, "load_config", lambda: config)
    monkeypatch.setattr(
        agent_router_module,
        "save_config",
        lambda current: saved_ids.append(
            current.agents.transcription_provider_id,
        ),
    )
    monkeypatch.setattr(
        audio_transcription_module,
        "_get_manager",
        lambda: SimpleNamespace(get_provider=lambda provider_id: None),
    )

    with pytest.raises(HTTPException, match="Unknown transcription provider"):
        await agent_router_module.put_transcription_provider(
            {"provider_id": "missing"},
        )

    assert saved_ids == []


@pytest.mark.asyncio
async def test_put_transcription_provider_allows_clearing_selection(
    monkeypatch,
):
    config = SimpleNamespace(
        agents=SimpleNamespace(
            transcription_provider_type="whisper_api",
            transcription_provider_id="openai",
        ),
    )

    monkeypatch.setattr(agent_router_module, "load_config", lambda: config)
    monkeypatch.setattr(agent_router_module, "save_config", lambda current: None)
    monkeypatch.setattr(
        audio_transcription_module,
        "_get_manager",
        lambda: SimpleNamespace(get_provider=lambda provider_id: None),
    )

    result = await agent_router_module.put_transcription_provider(
        {"provider_id": ""},
    )

    assert result == {"provider_id": ""}
    assert config.agents.transcription_provider_id == ""
