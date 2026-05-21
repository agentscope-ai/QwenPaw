# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw models`` CLI surface."""

from __future__ import annotations

import json

from click.testing import CliRunner

from qwenpaw.cli.main import cli
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo


class _FakeManager:
    def __init__(self, active_model: ModelSlotConfig | None) -> None:
        self._active_model = active_model

    def get_active_model(self) -> ModelSlotConfig | None:
        return self._active_model


def _make_provider(
    *,
    provider_id: str,
    name: str,
    base_url: str = "",
    api_key: str = "",
    require_api_key: bool = True,
    models: list[ModelInfo] | None = None,
    extra_models: list[ModelInfo] | None = None,
) -> OpenAIProvider:
    return OpenAIProvider(
        id=provider_id,
        name=name,
        base_url=base_url,
        api_key=api_key,
        require_api_key=require_api_key,
        models=models or [],
        extra_models=extra_models or [],
    )


def test_models_list_default_text_output(monkeypatch) -> None:
    providers = [
        _make_provider(
            provider_id="openai",
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test-key",
            models=[ModelInfo(id="gpt-4o", name="GPT-4o")],
            extra_models=[ModelInfo(id="custom-model", name="Custom Model")],
        ),
    ]
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._manager",
        lambda: _FakeManager(
            ModelSlotConfig(provider_id="openai", model="gpt-4o"),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._all_provider_objects",
        lambda _manager: providers,
    )

    result = CliRunner().invoke(cli, ["models", "list"])

    assert result.exit_code == 0
    assert "OpenAI (openai)" in result.output
    assert "GPT-4o (gpt-4o)" in result.output
    assert "Custom Model (custom-model) [user-added]" in result.output
    assert "LLM             : openai / gpt-4o" in result.output


def test_models_list_json_output_contains_active_model(monkeypatch) -> None:
    providers = [
        _make_provider(
            provider_id="openai",
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test-key",
            models=[ModelInfo(id="gpt-4o", name="GPT-4o")],
            extra_models=[ModelInfo(id="custom-model", name="Custom Model")],
        ),
    ]
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._manager",
        lambda: _FakeManager(
            ModelSlotConfig(provider_id="openai", model="gpt-4o"),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._all_provider_objects",
        lambda _manager: providers,
    )

    result = CliRunner().invoke(cli, ["models", "list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["active_model"] == {
        "provider_id": "openai",
        "model": "gpt-4o",
    }
    assert payload["providers"][0]["configured"] is True
    assert payload["providers"][0]["api_key"] == "sk-t...ey"
    assert payload["providers"][0]["models"] == [
        {"id": "gpt-4o", "name": "GPT-4o", "user_added": False},
        {
            "id": "custom-model",
            "name": "Custom Model",
            "user_added": True,
        },
    ]


def test_models_list_configured_only_filters_text_output(monkeypatch) -> None:
    providers = [
        _make_provider(
            provider_id="openai",
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test-key",
            models=[ModelInfo(id="gpt-4o", name="GPT-4o")],
        ),
        _make_provider(
            provider_id="anthropic",
            name="Anthropic",
            base_url="https://api.anthropic.com",
            api_key="",
            models=[ModelInfo(id="claude-sonnet", name="Claude Sonnet")],
        ),
    ]
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._manager",
        lambda: _FakeManager(None),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._all_provider_objects",
        lambda _manager: providers,
    )

    result = CliRunner().invoke(cli, ["models", "list", "--configured-only"])

    assert result.exit_code == 0
    assert "OpenAI (openai)" in result.output
    assert "Anthropic (anthropic)" not in result.output


def test_models_list_configured_only_filters_json_output(monkeypatch) -> None:
    providers = [
        _make_provider(
            provider_id="openai",
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test-key",
            models=[ModelInfo(id="gpt-4o", name="GPT-4o")],
        ),
        _make_provider(
            provider_id="azure-openai",
            name="Azure OpenAI",
            base_url="",
            api_key="set-but-no-url",
            models=[ModelInfo(id="gpt-4.1", name="GPT-4.1")],
        ),
    ]
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._manager",
        lambda: _FakeManager(None),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._all_provider_objects",
        lambda _manager: providers,
    )

    result = CliRunner().invoke(
        cli,
        ["models", "list", "--json", "--configured-only"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [provider["id"] for provider in payload["providers"]] == ["openai"]


def test_models_list_json_uses_null_for_missing_active_model(
    monkeypatch,
) -> None:
    providers = [
        _make_provider(
            provider_id="openai",
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test-key",
            models=[ModelInfo(id="gpt-4o", name="GPT-4o")],
        ),
    ]
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._manager",
        lambda: _FakeManager(None),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._all_provider_objects",
        lambda _manager: providers,
    )

    result = CliRunner().invoke(cli, ["models", "list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["active_model"] is None


def test_models_list_text_shows_not_configured_when_active_model_missing(
    monkeypatch,
) -> None:
    providers = [
        _make_provider(
            provider_id="openai",
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test-key",
            models=[ModelInfo(id="gpt-4o", name="GPT-4o")],
        ),
    ]
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._manager",
        lambda: _FakeManager(None),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.providers_cmd._all_provider_objects",
        lambda _manager: providers,
    )

    result = CliRunner().invoke(cli, ["models", "list"])

    assert result.exit_code == 0
    assert "LLM             : (not configured)" in result.output
