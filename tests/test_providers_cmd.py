# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from click.testing import CliRunner

import copaw.cli.providers_cmd as providers_cmd_module
from copaw.providers.provider import ModelInfo


@dataclass
class FakeProvider:
    id: str
    name: str
    base_url: str = ""
    api_key: str = ""
    api_key_prefix: str = ""
    is_custom: bool = False
    is_local: bool = False
    require_api_key: bool = True
    models: list[ModelInfo] = field(default_factory=list)
    extra_models: list[ModelInfo] = field(default_factory=list)

    async def add_model(self, model_info: ModelInfo) -> bool:
        self.extra_models.append(model_info)
        return True

    async def delete_model(self, model_id: str) -> bool:
        self.extra_models = [
            model for model in self.extra_models if model.id != model_id
        ]
        return True


class FakeManager:
    def __init__(self, providers: list[FakeProvider]) -> None:
        self._providers = {provider.id: provider for provider in providers}
        self._active = None
        self.last_update: dict | None = None
        self.saved: list[tuple[str, bool]] = []
        self.builtin_providers = {
            provider.id: provider
            for provider in providers
            if not provider.is_custom
        }

    async def list_provider_info(self):
        return [
            SimpleNamespace(id=provider_id) for provider_id in self._providers
        ]

    def get_provider(self, provider_id: str):
        return self._providers.get(provider_id)

    def update_provider(self, provider_id: str, config: dict) -> bool:
        provider = self.get_provider(provider_id)
        if provider is None:
            return False
        self.last_update = {"provider_id": provider_id, **config}
        if config.get("api_key") is not None:
            provider.api_key = config["api_key"]
        if config.get("base_url"):
            provider.base_url = config["base_url"]
        return True

    async def activate_model(self, provider_id: str, model: str) -> None:
        provider = self.get_provider(provider_id)
        if provider is None:
            raise ValueError("provider not found")
        all_models = provider.models + provider.extra_models
        if not any(m.id == model for m in all_models):
            raise ValueError("model not found")
        self._active = SimpleNamespace(provider_id=provider_id, model=model)

    def get_active_model(self):
        return self._active

    def _save_provider(
        self,
        provider: FakeProvider,
        is_builtin: bool = False,
        skip_if_exists: bool = False,
    ) -> None:
        _ = skip_if_exists
        self.saved.append((provider.id, is_builtin))


def _runner() -> CliRunner:
    return CliRunner()


def test_config_key_command_updates_provider(monkeypatch) -> None:
    fake = FakeManager(
        [
            FakeProvider(
                id="openai",
                name="OpenAI",
                base_url="https://api.openai.com/v1",
                api_key_prefix="sk-",
            ),
        ],
    )
    monkeypatch.setattr(providers_cmd_module, "_manager", lambda: fake)

    result = _runner().invoke(
        providers_cmd_module.models_group,
        ["config-key", "openai"],
        input="sk-test-123\n",
    )

    assert result.exit_code == 0
    assert fake.last_update is not None
    assert fake.last_update["provider_id"] == "openai"
    assert fake.last_update["api_key"] == "sk-test-123"


def test_set_llm_command_activates_selected_model(monkeypatch) -> None:
    fake = FakeManager(
        [
            FakeProvider(
                id="llamacpp",
                name="Llama.cpp",
                is_local=True,
                models=[ModelInfo(id="qwen-local", name="Qwen Local")],
                require_api_key=False,
            ),
            FakeProvider(
                id="ollama",
                name="Ollama",
                models=[ModelInfo(id="qwen2.5:3b", name="Qwen 2.5 3B")],
                require_api_key=False,
            ),
            FakeProvider(
                id="openai",
                name="OpenAI",
                base_url="https://api.openai.com/v1",
                models=[ModelInfo(id="gpt-5", name="GPT-5")],
                api_key="sk-test-123",
            ),
            FakeProvider(
                id="custom-no-key",
                name="Custom No Key",
                base_url="https://example.com/v1",
                models=[ModelInfo(id="custom-model", name="Custom Model")],
                require_api_key=False,
            ),
            FakeProvider(
                id="missing-base-url",
                name="Missing Base URL",
                api_key="sk-test-456",
                models=[ModelInfo(id="bad-1", name="Bad 1")],
            ),
            FakeProvider(
                id="missing-api-key",
                name="Missing API Key",
                base_url="https://azure.example.com/openai/v1",
                models=[ModelInfo(id="bad-2", name="Bad 2")],
            ),
        ],
    )
    monkeypatch.setattr(providers_cmd_module, "_manager", lambda: fake)

    choice_calls: list[tuple[str, list[str]]] = []

    def _fake_choice(_prompt, options, default=None):
        choice_calls.append((_prompt, list(options)))
        if _prompt == "Select provider for LLM:":
            assert default is None
            assert options == [
                "Llama.cpp (llamacpp)",
                "Ollama (ollama)",
                "OpenAI (openai)",
                "Custom No Key (custom-no-key)",
            ]
            return "OpenAI (openai)"

        assert _prompt == "Select LLM model:"
        assert default is None
        assert options == ["GPT-5"]
        return "GPT-5"

    monkeypatch.setattr(
        providers_cmd_module,
        "prompt_choice",
        _fake_choice,
    )

    result = _runner().invoke(
        providers_cmd_module.models_group,
        ["set-llm"],
    )

    assert result.exit_code == 0
    active = fake.get_active_model()
    assert active is not None
    assert active.provider_id == "openai"
    assert active.model == "gpt-5"
    assert len(choice_calls) == 2
    assert choice_calls[0][0] == "Select provider for LLM:"
    assert choice_calls[1][0] == "Select LLM model:"


def test_add_model_command_saves_provider(monkeypatch) -> None:
    fake = FakeManager(
        [
            FakeProvider(
                id="openai",
                name="OpenAI",
                base_url="https://api.openai.com/v1",
                models=[ModelInfo(id="gpt-5", name="GPT-5")],
            ),
        ],
    )
    monkeypatch.setattr(providers_cmd_module, "_manager", lambda: fake)

    result = _runner().invoke(
        providers_cmd_module.models_group,
        ["add-model", "openai", "-m", "gpt-5-mini", "-n", "GPT-5 Mini"],
    )

    assert result.exit_code == 0
    provider = fake.get_provider("openai")
    assert provider is not None
    assert any(model.id == "gpt-5-mini" for model in provider.extra_models)
    assert ("openai", True) in fake.saved


def test_ollama_list_command_uses_provider_host(monkeypatch) -> None:
    fake = FakeManager(
        [
            FakeProvider(
                id="ollama",
                name="Ollama",
                base_url="http://127.0.0.1:11434",
                require_api_key=False,
            ),
        ],
    )
    called = {}

    def _fake_list_models(host: str):
        called["host"] = host
        return [
            SimpleNamespace(
                name="qwen2.5:3b",
                size=2 * 1024 * 1024,
                digest="abc123",
            ),
        ]

    monkeypatch.setattr(providers_cmd_module, "_manager", lambda: fake)
    monkeypatch.setattr(
        providers_cmd_module.OllamaModelManager,
        "list_models",
        _fake_list_models,
    )

    result = _runner().invoke(
        providers_cmd_module.models_group,
        ["ollama-list"],
    )

    assert result.exit_code == 0
    assert called["host"] == "http://127.0.0.1:11434"
    assert "qwen2.5:3b" in result.output
