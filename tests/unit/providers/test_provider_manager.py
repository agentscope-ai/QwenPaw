# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import copaw.providers.provider_manager as provider_manager_module
from copaw.app.routers.providers import (
    logout_provider_auth,
    poll_provider_device_auth,
)
from copaw.providers.anthropic_provider import AnthropicProvider
from copaw.providers.github_copilot_provider import (
    DeviceAuthorizationPollResult,
    GitHubCopilotProvider,
)
from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.provider import DefaultProvider, ModelInfo
from copaw.providers.provider_manager import ProviderManager


class FakeSecretStore:
    def __init__(self, *, available: bool = False) -> None:
        self.available = available
        self.secret: str | None = None
        self.delete_calls = 0

    def load_payload(self) -> dict | None:
        if self.secret is None:
            return None
        return json.loads(self.secret)

    def save_payload(self, payload: dict) -> bool:
        if not self.available:
            return False
        self.secret = json.dumps(payload, ensure_ascii=False)
        return True

    def delete_payload(self) -> None:
        self.delete_calls += 1
        self.secret = None


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


@pytest.fixture(autouse=True)
def fake_secret_store(monkeypatch):
    store = FakeSecretStore(available=False)
    monkeypatch.setattr(
        GitHubCopilotProvider,
        "_load_keyring_auth_payload",
        lambda self: store.load_payload(),
    )
    monkeypatch.setattr(
        GitHubCopilotProvider,
        "_save_keyring_auth_payload",
        lambda self, payload: store.save_payload(payload),
    )
    monkeypatch.setattr(
        GitHubCopilotProvider,
        "_delete_keyring_auth_payload",
        lambda self: store.delete_payload(),
    )
    return store


@pytest.fixture(autouse=True)
def fresh_github_copilot_provider(monkeypatch):
    monkeypatch.setattr(
        provider_manager_module,
        "PROVIDER_GITHUB_COPILOT",
        GitHubCopilotProvider(
            id="github-copilot",
            name="GitHub Copilot",
            base_url="https://api.individual.githubcopilot.com",
            require_api_key=False,
            support_model_discovery=True,
            freeze_url=True,
        ),
    )


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

    with pytest.raises(ValueError, match="Provider 'missing' not found"):
        await manager.activate_model("missing", "gpt-5")


async def test_activate_provider_invalid_model_raises(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()

    with pytest.raises(ValueError, match="Model 'not-exists' not found"):
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


def test_provider_from_data_dispatch_to_default_local(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()

    provider = manager._provider_from_data(
        {
            "id": "local-default",
            "name": "Local Default",
            "is_local": True,
        },
    )

    assert isinstance(provider, DefaultProvider)


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


def test_provider_from_data_dispatch_to_github_copilot(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()

    provider = manager._provider_from_data(
        {
            "id": "github-copilot",
            "name": "GitHub Copilot",
            "base_url": "https://api.individual.githubcopilot.com",
            "require_api_key": False,
            "support_model_discovery": True,
            "freeze_url": True,
        },
    )

    assert isinstance(provider, GitHubCopilotProvider)


def test_save_provider_for_github_copilot_persists_refresh_credentials_only(
    isolated_secret_dir,
    fake_secret_store,
) -> None:
    fake_secret_store.available = True
    manager = ProviderManager()
    provider = manager.get_provider("github-copilot")

    assert isinstance(provider, GitHubCopilotProvider)

    provider.is_authenticated = True
    provider.auth_account_label = "octocat"
    provider.github_oauth_token = "gho_test"
    provider.github_scope = "read:user"
    provider.github_user_login = "octocat"
    provider.github_user_id = 1
    provider.copilot_access_token = "copilot-token"
    provider.api_key = "copilot-token"

    manager._save_provider(provider, is_builtin=True)

    persisted_path = manager.builtin_path / "github-copilot.json"
    persisted = json.loads(persisted_path.read_text(encoding="utf-8"))

    assert persisted["github_auth_storage"] == "keychain"
    assert "github_oauth_token" not in persisted
    assert json.loads(fake_secret_store.secret or "{}") == {
        "github_oauth_token": "gho_test",
        "github_token_type": "bearer",
        "github_scope": "read:user",
        "github_user_login": "octocat",
        "github_user_id": 1,
    }
    assert "api_key" not in persisted
    assert "is_authenticated" not in persisted
    assert "copilot_access_token" not in persisted

    reloaded = manager.load_provider("github-copilot", is_builtin=True)

    assert isinstance(reloaded, GitHubCopilotProvider)
    assert reloaded.github_oauth_token == "gho_test"
    assert reloaded.github_user_login == "octocat"
    assert reloaded.copilot_access_token == ""


async def test_poll_provider_device_auth_persists_authorized_credentials(
    isolated_secret_dir,
    monkeypatch,
    fake_secret_store,
) -> None:
    fake_secret_store.available = True
    manager = ProviderManager()
    provider = manager.get_provider("github-copilot")

    assert isinstance(provider, GitHubCopilotProvider)

    async def fake_poll(self, session_id: str, timeout: float = 10):
        _ = self, session_id, timeout
        provider.github_oauth_token = "gho_test"
        provider.github_scope = "read:user"
        provider.github_user_login = "octocat"
        provider.github_user_id = 1
        provider.copilot_access_token = "copilot-token"
        provider.copilot_token_expires_at = 4_102_444_800
        provider.api_key = "copilot-token"
        return DeviceAuthorizationPollResult(
            status="authorized",
            message="GitHub authorization completed",
        )

    monkeypatch.setattr(
        GitHubCopilotProvider,
        "poll_device_authorization",
        fake_poll,
    )

    response = await poll_provider_device_auth(
        manager=manager,
        provider_id="github-copilot",
        session_id="session-1",
    )

    persisted_path = manager.builtin_path / "github-copilot.json"
    persisted = json.loads(persisted_path.read_text(encoding="utf-8"))

    assert response.status == "authorized"
    assert response.provider is not None
    assert response.provider.is_authenticated is True
    assert persisted["github_auth_storage"] == "keychain"
    assert "github_oauth_token" not in persisted
    assert json.loads(fake_secret_store.secret or "{}") == {
        "github_oauth_token": "gho_test",
        "github_token_type": "bearer",
        "github_scope": "read:user",
        "github_user_login": "octocat",
        "github_user_id": 1,
    }
    assert "copilot_access_token" not in persisted


async def test_logout_provider_auth_clears_persisted_credentials(
    isolated_secret_dir,
    fake_secret_store,
) -> None:
    fake_secret_store.available = True
    manager = ProviderManager()
    provider = manager.get_provider("github-copilot")

    assert isinstance(provider, GitHubCopilotProvider)

    provider.github_oauth_token = "gho_test"
    provider.github_scope = "read:user"
    provider.github_user_login = "octocat"
    provider.github_user_id = 1
    provider.copilot_access_token = "copilot-token"
    provider.api_key = "copilot-token"
    manager._save_provider(provider, is_builtin=True)

    response = await logout_provider_auth(
        manager=manager,
        provider_id="github-copilot",
    )

    persisted_path = manager.builtin_path / "github-copilot.json"
    persisted = json.loads(persisted_path.read_text(encoding="utf-8"))

    assert response.is_authenticated is False
    assert persisted["github_auth_storage"] == "none"
    assert "github_oauth_token" not in persisted
    assert "github_user_login" not in persisted
    assert "copilot_access_token" not in persisted
    assert fake_secret_store.secret is None
    assert fake_secret_store.delete_calls >= 1


def test_load_provider_legacy_json_auth_migrates_to_keychain_on_save(
    isolated_secret_dir,
    fake_secret_store,
) -> None:
    fake_secret_store.available = True
    manager = ProviderManager()
    persisted_path = manager.builtin_path / "github-copilot.json"
    persisted_path.write_text(
        json.dumps(
            {
                "id": "github-copilot",
                "name": "GitHub Copilot",
                "base_url": "https://api.individual.githubcopilot.com",
                "require_api_key": False,
                "support_model_discovery": True,
                "freeze_url": True,
                "github_oauth_token": "gho_test",
                "github_token_type": "bearer",
                "github_scope": "read:user",
                "github_user_login": "octocat",
                "github_user_id": 1,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    reloaded = manager.load_provider("github-copilot", is_builtin=True)

    assert isinstance(reloaded, GitHubCopilotProvider)
    assert reloaded.github_oauth_token == "gho_test"
    assert reloaded.github_user_login == "octocat"

    manager._save_provider(reloaded, is_builtin=True)

    persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
    assert persisted["github_auth_storage"] == "keychain"
    assert "github_oauth_token" not in persisted
    assert json.loads(fake_secret_store.secret or "{}") == {
        "github_oauth_token": "gho_test",
        "github_token_type": "bearer",
        "github_scope": "read:user",
        "github_user_login": "octocat",
        "github_user_id": 1,
    }


def test_init_from_storage_restores_github_copilot_auth_state(
    isolated_secret_dir,
    fake_secret_store,
    monkeypatch,
) -> None:
    fake_secret_store.available = True
    manager = ProviderManager()
    provider = manager.get_provider("github-copilot")

    assert isinstance(provider, GitHubCopilotProvider)

    provider.github_oauth_token = "gho_test"
    provider.github_scope = "read:user"
    provider.github_user_login = "octocat"
    provider.github_user_id = 1
    manager._save_provider(provider, is_builtin=True)

    monkeypatch.setattr(
        provider_manager_module,
        "PROVIDER_GITHUB_COPILOT",
        GitHubCopilotProvider(
            id="github-copilot",
            name="GitHub Copilot",
            base_url="https://api.individual.githubcopilot.com",
            require_api_key=False,
            support_model_discovery=True,
            freeze_url=True,
        ),
    )

    restarted_manager = ProviderManager()
    restarted_provider = restarted_manager.get_provider("github-copilot")

    assert isinstance(restarted_provider, GitHubCopilotProvider)
    assert restarted_provider.github_auth_storage == "keychain"
    assert restarted_provider.github_oauth_token == "gho_test"
    assert restarted_provider.github_user_login == "octocat"
    assert restarted_provider.is_authenticated is True
    assert restarted_provider.auth_account_label == "octocat"
    assert restarted_provider.copilot_access_token == ""


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
