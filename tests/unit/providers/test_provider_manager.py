# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from agentscope_runtime.engine.schemas.exception import (
    ModelNotFoundException,
)

import copaw.providers.provider_manager as provider_manager_module
from copaw.exceptions import ProviderError
from copaw.providers.anthropic_provider import AnthropicProvider
from copaw.providers.models import ModelSlotConfig
from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.provider import ModelInfo
from copaw.providers.provider_manager import ProviderManager


LEGACY_PROVIDER = {
    "providers": {
        "modelscope": {
            "base_url": "https://api-inference.modelscope.cn/v1",
            "api_key": "",
            "extra_models": [],
            "chat_model": "",
        },
        "dashscope": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-test-legacy-secret",
            "extra_models": [{"id": "qwen-plus", "name": "Qwen Plus"}],
            "chat_model": "",
        },
        "aliyun-codingplan": {
            "base_url": "https://coding.dashscope.aliyuncs.com/v1",
            "api_key": "",
            "extra_models": [],
            "chat_model": "",
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "extra_models": [],
            "chat_model": "",
        },
        "azure-openai": {
            "base_url": "",
            "api_key": "",
            "extra_models": [],
            "chat_model": "",
        },
        "anthropic": {
            "base_url": "https://api.anthropic.com/v1",
            "api_key": "",
            "extra_models": [],
            "chat_model": "",
        },
        "ollama": {
            "base_url": "http://myhost:11434/v1",
            "api_key": "",
            "extra_models": [],
            "chat_model": "",
        },
    },
    "custom_providers": {
        "mydash": {
            "id": "mydash",
            "name": "MyDash",
            "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",  # noqa: E501
            "api_key_prefix": "sk-",
            "models": [{"id": "qwen3-max", "name": "qwen3-max"}],
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-test-legacy-custom-secret",
            "chat_model": "OpenAIChatModel",
        },
    },
    "active_llm": {"provider_id": "dashscope", "model": "qwen3-max"},
}


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".copaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_builtin_zhipu_providers_registered(isolated_secret_dir) -> None:
    manager = ProviderManager()

    expected_configs = {
        "zhipu-cn": {
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "support_connection_check": True,
        },
        "zhipu-cn-codingplan": {
            "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
            "support_connection_check": False,
        },
        "zhipu-intl": {
            "base_url": "https://api.z.ai/api/paas/v4",
            "support_connection_check": True,
        },
        "zhipu-intl-codingplan": {
            "base_url": "https://api.z.ai/api/coding/paas/v4",
            "support_connection_check": False,
        },
    }

    for provider_id, expected in expected_configs.items():
        provider = manager.get_provider(provider_id)

        assert provider is not None
        assert isinstance(provider, OpenAIProvider)
        assert provider.base_url == expected["base_url"]
        assert provider.freeze_url is True
        assert (
            provider.support_connection_check
            == expected["support_connection_check"]
        )
        assert [model.id for model in provider.models] == [
            "glm-5",
            "glm-5.1",
            "glm-5-turbo",
            "glm-5v-turbo",
        ]


async def test_add_custom_provider_and_reload_from_storage(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    custom = OpenAIProvider(
        id="custom-openai",
        name="Custom OpenAI",
        base_url="https://custom.example/v1",
        api_key="sk-custom",
        models=[ModelInfo(id="custom-model", name="Custom Model")],
    )

    created = await manager.add_custom_provider(custom)
    builtin_conflict = await manager.add_custom_provider(
        OpenAIProvider(
            id="openai",
            name="Conflict OpenAI",
        ),
    )
    duplicate = await manager.add_custom_provider(custom)

    reloaded = ProviderManager()
    loaded = reloaded.get_provider("custom-openai")
    loaded_builtin_conflict = reloaded.get_provider("openai-custom")
    loaded_duplicate = reloaded.get_provider("custom-openai-new")

    assert created.id == "custom-openai"
    assert builtin_conflict.id == "openai-custom"
    assert duplicate.id == "custom-openai-new"
    assert loaded is not None
    assert isinstance(loaded, OpenAIProvider)
    assert loaded.is_custom is True
    assert loaded.base_url == "https://custom.example/v1"
    assert loaded.api_key == "sk-custom"
    assert [m.id for m in loaded.models] == ["custom-model"]
    assert loaded_builtin_conflict is not None
    assert isinstance(loaded_builtin_conflict, OpenAIProvider)
    assert loaded_duplicate is not None
    assert isinstance(loaded_duplicate, OpenAIProvider)


async def test_activate_provider_persists_active_model(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(id="ok", request=kwargs)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )

    monkeypatch.setattr(
        OpenAIProvider,
        "_client",
        lambda self, timeout=5: fake_client,
    )

    await manager.activate_model("openai", "gpt-5")

    assert manager.active_model is not None
    assert manager.active_model.provider_id == "openai"
    assert manager.active_model.model == "gpt-5"

    reloaded = ProviderManager()
    assert reloaded.active_model is not None
    assert reloaded.active_model.provider_id == "openai"
    assert reloaded.active_model.model == "gpt-5"


async def test_resume_local_model_restores_server_and_runtime_state(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    model_id = "AgentScope/CoPaw-flash-2B-Q4_K_M"
    manager.update_provider(
        "copaw-local",
        {
            "base_url": "http://127.0.0.1:9000/v1",
            "extra_models": [
                {
                    "id": model_id,
                    "name": model_id,
                },
            ],
        },
    )
    manager.active_model = ModelSlotConfig(
        provider_id="copaw-local",
        model=model_id,
    )
    manager.save_active_model(manager.active_model)

    class FakeLocalManager:
        def __init__(self) -> None:
            self.restored_model_id = None

        def check_llamacpp_installation(self) -> tuple[bool, str]:
            return True, ""

        def is_model_downloaded(self, requested_model_id: str) -> bool:
            return requested_model_id == model_id

        async def setup_server(self, requested_model_id: str) -> int:
            self.restored_model_id = requested_model_id
            return 43111

    local_manager = FakeLocalManager()

    await manager._resume_local_model(local_manager)

    provider = manager.get_provider("copaw-local")

    assert local_manager.restored_model_id == model_id
    assert provider is not None
    assert provider.base_url == "http://127.0.0.1:43111/v1"
    assert [model.id for model in provider.extra_models] == [model_id]


async def test_remove_custom_provider_missing_file_is_safe(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    custom = OpenAIProvider(
        id="custom-to-remove",
        name="Custom To Remove",
        base_url="https://remove.example/v1",
        api_key="sk-remove",
    )
    await manager.add_custom_provider(custom)

    custom_path = manager.custom_path / "custom-to-remove.json"
    custom_path.unlink()

    manager.remove_custom_provider("custom-to-remove")

    assert manager.get_provider("custom-to-remove") is None


def test_load_provider_invalid_json_returns_none(isolated_secret_dir) -> None:
    manager = ProviderManager()
    bad_file = manager.custom_path / "bad-provider.json"
    bad_file.write_text("{invalid-json", encoding="utf-8")

    loaded = manager.load_provider("bad-provider", is_builtin=False)

    assert loaded is None


def test_migrate_legacy_file_and_persist_active_model(
    isolated_secret_dir,
) -> None:
    isolated_secret_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = isolated_secret_dir / "providers.json"
    legacy_file.write_text(
        json.dumps(
            LEGACY_PROVIDER,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manager = ProviderManager()

    assert legacy_file.exists() is False
    assert manager.active_model is not None
    assert manager.active_model.provider_id == "dashscope"
    assert manager.active_model.model == "qwen3-max"

    dashscope_provider = manager.get_provider("dashscope")
    assert dashscope_provider is not None
    assert dashscope_provider.api_key == "sk-test-legacy-secret"

    legacy_custom = manager.get_provider("mydash")
    assert legacy_custom is not None
    assert isinstance(legacy_custom, OpenAIProvider)
    assert len(legacy_custom.extra_models) == 1
    assert legacy_custom.extra_models[0].id == "qwen3-max"
    assert legacy_custom.api_key == "sk-test-legacy-custom-secret"

    legacy_ollama = manager.get_provider("ollama")
    assert legacy_ollama.base_url == "http://myhost:11434"

    active_model_file = isolated_secret_dir / "providers" / "active_model.json"
    assert active_model_file.exists()


async def test_add_custom_provider_conflict_resolution_loops_until_unique(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    conflict = OpenAIProvider(
        id="openai",
        name="Conflict OpenAI",
    )

    first = await manager.add_custom_provider(conflict)
    second = await manager.add_custom_provider(conflict)
    third = await manager.add_custom_provider(conflict)

    assert first.id == "openai-custom"
    assert second.id == "openai-custom-new"
    assert third.id == "openai-custom-new-new"

    assert manager.get_provider("openai-custom") is not None
    assert manager.get_provider("openai-custom-new") is not None
    assert manager.get_provider("openai-custom-new-new") is not None


def test_update_provider_for_builtin_persists_to_builtin_path(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()

    ok = manager.update_provider(
        "openai",
        {
            "base_url": "https://updated.example/v1",  # not taken effect
            "api_key": "sk-updated",
        },
    )

    assert ok is True
    persisted = manager.load_provider("openai", is_builtin=True)
    assert persisted is not None
    assert isinstance(persisted, OpenAIProvider)
    assert persisted.base_url == "https://api.openai.com/v1"
    assert persisted.api_key == "sk-updated"

    ok = manager.update_provider(
        "azure-openai",
        {
            "base_url": "https://azure-updated.example/v1",
            "api_key": "sk-azure-updated",
        },
    )
    assert ok is True
    persisted_azure = manager.load_provider("azure-openai", is_builtin=True)
    assert persisted_azure is not None
    assert isinstance(persisted_azure, OpenAIProvider)
    assert persisted_azure.base_url == "https://azure-updated.example/v1"
    assert persisted_azure.api_key == "sk-azure-updated"


def test_update_provider_for_unknown_returns_false(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()

    ok = manager.update_provider("unknown-provider", {"api_key": "sk-x"})

    assert ok is False


async def test_activate_provider_invalid_provider_raises(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()

    with pytest.raises(ProviderError, match="Provider 'missing' not found"):
        await manager.activate_model("missing", "gpt-5")


async def test_activate_provider_invalid_model_raises(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()

    with pytest.raises(ModelNotFoundException, match="not-exists"):
        await manager.activate_model("openai", "not-exists")


def test_save_provider_skip_if_exists_does_not_overwrite(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = OpenAIProvider(
        id="custom-skip",
        name="Original",
        api_key="sk-original",
    )
    manager._save_provider(provider, is_builtin=False)

    provider.name = "Changed"
    provider.api_key = "sk-changed"
    manager._save_provider(provider, is_builtin=False, skip_if_exists=True)

    loaded = manager.load_provider("custom-skip", is_builtin=False)
    assert loaded is not None
    assert loaded.name == "Original"
    assert loaded.api_key == "sk-original"


def test_load_provider_missing_returns_none(isolated_secret_dir) -> None:
    manager = ProviderManager()

    loaded = manager.load_provider("not-found", is_builtin=False)

    assert loaded is None


def test_provider_from_data_dispatch_to_anthropic(isolated_secret_dir) -> None:
    manager = ProviderManager()

    provider = manager._provider_from_data(
        {
            "id": "custom-anthropic",
            "name": "Custom Anthropic",
            "chat_model": "AnthropicChatModel",
            "api_key": "sk-ant-x",
        },
    )

    assert isinstance(provider, AnthropicProvider)


def test_provider_from_data_fallback_to_openai(isolated_secret_dir) -> None:
    manager = ProviderManager()

    provider = manager._provider_from_data(
        {
            "id": "custom-openai-like",
            "name": "OpenAI Like",
            "base_url": "https://custom.example/v1",
        },
    )

    assert isinstance(provider, OpenAIProvider)


def test_init_from_storage_migrates_with_different_provider(
    isolated_secret_dir,
) -> None:
    builtin_path = isolated_secret_dir / "providers" / "builtin"
    builtin_path.mkdir(parents=True, exist_ok=True)

    legacy_minimax_provider = {
        "id": "minimax",
        "name": "MiniMax",
        "base_url": "https://api.minimax.io/v1",
        "api_key": "sk-legacy-minimax",
        "chat_model": "OpenAIChatModel",
        "models": [{"id": "MiniMax-M2.5", "name": "MiniMax M2.5"}],
        "generate_kwargs": {"temperature": 1.0},
    }
    (builtin_path / "minimax.json").write_text(
        json.dumps(legacy_minimax_provider, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manager = ProviderManager()

    provider = manager.get_provider("minimax")

    assert provider is not None
    assert isinstance(provider, AnthropicProvider)
    # url / name / chatmodel should be updated
    assert provider.base_url == "https://api.minimax.io/anthropic"
    assert provider.chat_model == "AnthropicChatModel"
    assert provider.name == "MiniMax (International)"
    # api key should be preserved
    assert provider.api_key == "sk-legacy-minimax"

    from agentscope.model import AnthropicChatModel

    assert provider.get_chat_model_cls() == AnthropicChatModel

    legacy_ollama_provider = {
        "id": "ollama",
        "name": "Ollama New",
        "base_url": "http://legacy-ollama:11434",
        "api_key": "sk-legacy-ollama",
        "chat_model": "OpenAIChatModel",
        "models": [],
    }
    (builtin_path / "ollama.json").write_text(
        json.dumps(legacy_ollama_provider, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manager = ProviderManager()
    assert manager.get_provider("ollama") is not None
    assert (
        manager.get_provider("ollama").base_url == "http://legacy-ollama:11434"
    )
