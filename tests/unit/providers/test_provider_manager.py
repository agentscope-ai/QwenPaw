# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

import qwenpaw.providers.capability_baseline as capability_baseline_module
import qwenpaw.providers.provider_manager as provider_manager_module
import qwenpaw.providers.provider_persistence as provider_persistence_module
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.exceptions import ModelNotFoundException, ProviderError
from qwenpaw.local_models.llamacpp import LlamaCppServerSetupResult
from qwenpaw.providers.anthropic_provider import AnthropicProvider
from qwenpaw.providers.gemini_provider import GeminiProvider
from qwenpaw.providers.capping_formatter import (
    _CappingAnthropicFormatter,
    _CappingGeminiFormatter,
    _CappingOpenAIFormatter,
)
from qwenpaw.providers.context_windows import DEFAULT_CONTEXT_WINDOW
from qwenpaw.providers.openai_provider import (
    GitHubModelsProvider,
    OpenCodeProvider,
    OpenAIProvider,
)
from qwenpaw.providers.openai_response_provider import OpenAIResponseProvider
from qwenpaw.providers.openrouter_provider import OpenRouterProvider
from qwenpaw.providers.provider import (
    ModelConnectionResult,
    ModelInfo,
    ProviderInfo,
)
from qwenpaw.providers.provider_manager import ProviderManager

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
    secret_dir = tmp_path / ".qwenpaw.secret"
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
        assert provider.support_connection_check == (
            expected["support_connection_check"]
        )
        model_ids = [m.id for m in provider.models]
        assert len(model_ids) > 0
        assert len(model_ids) == len(set(model_ids))


def test_builtin_restore_preserves_catalog_free_flags() -> None:
    builtin = OpenAIProvider(
        id="catalog-provider",
        name="Catalog Provider",
        models=[
            ModelInfo(id="free-model", name="Free", is_free=True),
            ModelInfo(id="paid-model", name="Paid", is_free=False),
        ],
    )
    stored = builtin.model_copy(deep=True)
    stored.models[0].is_free = False
    stored.models[1].is_free = True

    ProviderManager._restore_builtin_provider(builtin, stored)

    assert [model.is_free for model in builtin.models] == [True, False]


def test_builtin_restore_drops_provider_unavailable_models() -> None:
    builtin = OpenCodeProvider(
        id="opencode",
        name="OpenCode",
        models=[ModelInfo(id="mimo-v2.5-free", name="Mimo")],
    )
    stored = builtin.model_copy(deep=True)
    stored.extra_models = [
        ModelInfo(id="nemotron-3-super-free", name="Nemotron Super"),
        ModelInfo(id="user-model", name="User Model"),
    ]
    stored.discovered_models = [
        ModelInfo(id="deepseek-v4-flash-free", name="DeepSeek Flash"),
        ModelInfo(id="remote-model", name="Remote Model"),
    ]

    ProviderManager._restore_builtin_provider(builtin, stored)

    assert [model.id for model in builtin.extra_models] == ["user-model"]
    assert [model.id for model in builtin.discovered_models] == [
        "remote-model",
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
    assert created.support_model_discovery is True
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


async def test_custom_provider_identity_is_case_insensitive(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    created = await manager.add_custom_provider(
        OpenAIProvider(
            id="MixedCase",
            name="Mixed Case",
            base_url="https://first.example/v1",
        ),
    )
    duplicate = await manager.add_custom_provider(
        OpenAIProvider(
            id="mixedcase",
            name="Mixed Case Duplicate",
        ),
    )

    assert created.id == "MixedCase"
    assert duplicate.id == "mixedcase-new"
    assert manager.get_provider("MIXEDCASE").id == "MixedCase"
    assert (manager.custom_path / "mixedcase.json").exists()

    reloaded = ProviderManager()
    loaded = reloaded.get_provider("mIxEdCaSe")
    assert loaded is not None
    assert loaded.id == "MixedCase"
    assert await reloaded.update_provider_async(
        "MIXEDCASE",
        {"base_url": "https://updated.example/v1"},
    )
    assert list(reloaded._provider_save_locks) == ["mixedcase"]

    updated = ProviderManager().get_provider("mixedcase")
    assert updated is not None
    assert updated.base_url == "https://updated.example/v1"
    assert await reloaded.remove_custom_provider_async("MiXeDcAsE")
    assert not (reloaded.custom_path / "mixedcase.json").exists()


async def test_plugin_provider_rejects_casefold_collisions(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    await manager.add_custom_provider(
        OpenAIProvider(id="PluginMixed", name="Plugin Mixed"),
    )

    with pytest.raises(ProviderError, match="conflicts"):
        await manager.register_plugin_provider_async(
            "OPENAI",
            OpenAIProvider,
            "Builtin Collision",
            "https://plugin.example/v1",
            metadata={},
        )
    with pytest.raises(ProviderError, match="conflicts"):
        await manager.register_plugin_provider_async(
            "pluginmixed",
            OpenAIProvider,
            "Custom Collision",
            "https://plugin.example/v1",
            metadata={},
        )


async def test_case_colliding_legacy_files_keep_one_stable_snapshot(
    isolated_secret_dir,
) -> None:
    seed = ProviderManager()
    upper_path = seed.custom_path / "LegacyCase.json"
    lower_path = seed.custom_path / "legacycase.json"
    upper = OpenAIProvider(
        id="LegacyCase",
        name="Upper Legacy",
        base_url="https://upper.example/v1",
        is_custom=True,
    )
    lower = OpenAIProvider(
        id="legacycase",
        name="Lower Legacy",
        base_url="https://lower.example/v1",
        is_custom=True,
    )
    upper_path.write_text(
        json.dumps(upper.model_dump(mode="json")),
        encoding="utf-8",
    )
    lower_path.write_text(
        json.dumps(lower.model_dump(mode="json")),
        encoding="utf-8",
    )
    matching_files = [
        path
        for path in seed.custom_path.glob("*.json")
        if path.stem.casefold() == "legacycase"
    ]
    if len(matching_files) < 2:
        pytest.skip("Filesystem does not support case-distinct files.")

    manager = ProviderManager()
    loaded = manager.get_provider("LEGACYCASE")
    assert loaded is not None
    assert loaded.id == "LegacyCase"
    assert await manager.update_provider_async(
        "legacycase",
        {"base_url": "https://updated.example/v1"},
    )
    assert upper_path.exists()
    assert lower_path.exists()
    assert (
        json.loads(upper_path.read_text(encoding="utf-8"))["base_url"]
        == "https://updated.example/v1"
    )
    assert (
        json.loads(lower_path.read_text(encoding="utf-8"))["base_url"]
        == "https://lower.example/v1"
    )


@pytest.mark.parametrize(
    "provider_id",
    [
        "../escape",
        "team/provider",
        r"team\provider",
        "CON",
        "nul.json",
        "provider.",
    ],
)
async def test_add_custom_provider_rejects_unsafe_id(
    isolated_secret_dir,
    provider_id: str,
) -> None:
    manager = ProviderManager()

    with pytest.raises(ProviderError, match="Provider ID"):
        await manager.add_custom_provider(
            ProviderInfo(id=provider_id, name="Unsafe"),
        )

    assert not manager.custom_providers


async def test_add_custom_provider_publishes_after_persistence(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider_id = "custom-write-failure"

    async def fail_save(*_args, **_kwargs) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(manager, "save_provider_config_async", fail_save)

    with pytest.raises(OSError, match="write failed"):
        await manager.add_custom_provider(
            ProviderInfo(id=provider_id, name="Write Failure"),
        )

    assert manager.get_provider(provider_id) is None
    assert manager._provider_revision(provider_id) == 0
    assert not (manager.custom_path / f"{provider_id}.json").exists()


async def test_custom_provider_preserves_explicit_default_context_window(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    request_model = ModelInfo(
        id="claude-sonnet-4-5",
        name="Claude Sonnet 4.5",
        max_input_length=DEFAULT_CONTEXT_WINDOW,
    )
    assert "max_input_length" in request_model.model_fields_set
    assert request_model.max_input_length_configured is False

    await manager.add_custom_provider(
        ProviderInfo(
            id="custom-context-window",
            name="Custom Context Window",
            chat_model="OpenAIChatModel",
            extra_models=[request_model],
        ),
    )

    reloaded = ProviderManager().get_provider("custom-context-window")
    assert reloaded is not None
    model = reloaded.get_model_info("claude-sonnet-4-5")
    assert model is not None
    assert model.max_input_length_configured is True
    assert (
        reloaded.get_context_size("claude-sonnet-4-5")
        == DEFAULT_CONTEXT_WINDOW
    )


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


async def test_async_provider_path_resolution_runs_off_event_loop(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    event_loop_thread = threading.get_ident()
    path_threads = []
    original_safe_path = manager._safe_provider_path

    def safe_provider_path(provider_dir, provider_id):
        path_threads.append(threading.get_ident())
        return original_safe_path(provider_dir, provider_id)

    monkeypatch.setattr(
        manager,
        "_safe_provider_path",
        safe_provider_path,
    )

    provider_path = await manager._provider_config_path_async(
        "new-custom-provider",
    )

    assert provider_path.parent == manager.custom_path
    assert len(path_threads) == 1
    assert path_threads[0] != event_loop_thread


async def test_async_plugin_path_resolution_runs_off_event_loop(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    event_loop_thread = threading.get_ident()
    path_threads = []
    original_safe_path = manager._safe_provider_path

    def safe_provider_path(provider_dir, provider_id):
        path_threads.append(threading.get_ident())
        return original_safe_path(provider_dir, provider_id)

    monkeypatch.setattr(manager, "_safe_provider_path", safe_provider_path)

    provider_path = await manager._provider_path_for_kind_async(
        "plugin",
        "new-plugin-provider",
    )

    assert provider_path.parent == manager.plugin_path
    assert len(path_threads) == 1
    assert path_threads[0] != event_loop_thread


async def test_activate_provider_does_not_block_event_loop(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()

    def slow_save(_active_model):
        time.sleep(0.1)

    monkeypatch.setattr(manager, "save_active_model", slow_save)

    activation = asyncio.create_task(
        manager.activate_model("openai", "gpt-5"),
    )
    await asyncio.sleep(0.02)

    assert activation.done() is False
    await activation


async def test_cancelled_active_model_save_holds_lock_until_io_finishes(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    manager.active_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-5",
    )
    started = threading.Event()
    release = threading.Event()
    original_save = manager.save_active_model

    def slow_save(active_model):
        started.set()
        release.wait(timeout=5)
        original_save(active_model)

    monkeypatch.setattr(manager, "save_active_model", slow_save)
    save_task = asyncio.create_task(
        manager.save_active_model_async(manager.active_model),
    )
    assert await asyncio.to_thread(started.wait, 5)
    save_task.cancel()
    clear_task = asyncio.create_task(manager.clear_active_model_async())
    await asyncio.sleep(0.02)

    assert clear_task.done() is False
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await save_task
    assert await clear_task is True
    assert not (manager.root_path / "active_model.json").exists()


async def test_cancelled_active_model_save_commits_memory_after_write(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    manager.active_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-5.2",
    )
    requested = ModelSlotConfig(
        provider_id="openai",
        model="gpt-5",
    )
    started = threading.Event()
    release = threading.Event()
    original_save = manager.save_active_model

    def slow_save(active_model):
        started.set()
        release.wait(timeout=5)
        original_save(active_model)

    monkeypatch.setattr(manager, "save_active_model", slow_save)
    save_task = asyncio.create_task(
        manager.save_active_model_async(requested),
    )
    assert await asyncio.to_thread(started.wait, 5)
    save_task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await save_task
    assert manager.active_model == requested
    assert manager.load_active_model() == requested


async def test_cancelled_provider_mutation_commits_persisted_snapshot(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    started = threading.Event()
    release = threading.Event()
    original_save = manager._save_provider_snapshot_locked

    def slow_save(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        original_save(*args, **kwargs)

    monkeypatch.setattr(
        manager,
        "_save_provider_snapshot_locked",
        slow_save,
    )
    mutation = asyncio.create_task(
        manager.set_model_hidden(
            "openai",
            "gpt-5",
            hidden=True,
        ),
    )
    assert await asyncio.to_thread(started.wait, 5)
    mutation.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert "gpt-5" in provider.hidden_model_ids
    reloaded = ProviderManager().get_provider("openai")
    assert reloaded is not None
    assert "gpt-5" in reloaded.hidden_model_ids


async def test_cancelled_custom_delete_finishes_before_lock_releases(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    custom = OpenAIProvider(
        id="custom-cancel-delete",
        name="Custom Cancel Delete",
        base_url="https://remove.example/v1",
        api_key="sk-remove",
    )
    await manager.add_custom_provider(custom)
    path = manager.custom_path / "custom-cancel-delete.json"
    started = threading.Event()
    release = threading.Event()
    original_unlink = type(path).unlink
    finished = threading.Event()

    def slow_unlink(self, *, missing_ok=False):
        started.set()
        release.wait(timeout=5)
        original_unlink(self, missing_ok=missing_ok)
        finished.set()

    monkeypatch.setattr(type(path), "unlink", slow_unlink)
    delete_task = asyncio.create_task(
        manager.remove_custom_provider_async("custom-cancel-delete"),
    )
    assert await asyncio.to_thread(started.wait, 5)
    for _ in range(2):
        delete_task.cancel()
        await asyncio.sleep(0)
    update_task = asyncio.create_task(
        manager.update_provider_async(
            "custom-cancel-delete",
            {"base_url": "https://new.example/v1"},
        ),
    )
    await asyncio.sleep(0.02)

    assert update_task.done() is False
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await delete_task
    assert await asyncio.to_thread(finished.wait, 5)
    assert manager.get_provider("custom-cancel-delete") is None
    assert path.exists() is False
    assert await update_task is False
    assert path.exists() is False


async def test_cancelled_active_model_clear_commits_memory_after_unlink(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    active_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-5",
    )
    manager.active_model = active_model
    manager.save_active_model(active_model)
    active_path = manager.root_path / "active_model.json"
    started = threading.Event()
    release = threading.Event()
    original_unlink = type(active_path).unlink
    finished = threading.Event()

    def slow_unlink(self, *, missing_ok=False):
        if self == active_path:
            started.set()
            release.wait(timeout=5)
        original_unlink(self, missing_ok=missing_ok)
        if self == active_path:
            finished.set()

    monkeypatch.setattr(type(active_path), "unlink", slow_unlink)
    clear_task = asyncio.create_task(manager.clear_active_model_async())
    assert await asyncio.to_thread(started.wait, 5)
    for _ in range(2):
        clear_task.cancel()
        await asyncio.sleep(0)
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await clear_task
    assert await asyncio.to_thread(finished.wait, 5)
    assert manager.active_model is None
    assert active_path.exists() is False


async def test_custom_delete_failure_preserves_memory_and_disk(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    custom = OpenAIProvider(
        id="custom-delete-failure",
        name="Custom Delete Failure",
        base_url="https://remove.example/v1",
        api_key="sk-remove",
    )
    await manager.add_custom_provider(custom)
    path = manager.custom_path / "custom-delete-failure.json"
    original_unlink = type(path).unlink

    def failing_unlink(self, *, missing_ok=False):
        if self == path:
            raise OSError("unlink failed")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(type(path), "unlink", failing_unlink)

    with pytest.raises(OSError, match="unlink failed"):
        await manager.remove_custom_provider_async("custom-delete-failure")
    assert manager.get_provider("custom-delete-failure") is not None
    assert path.exists() is True


async def test_active_model_clear_failure_preserves_memory_and_disk(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    active_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-5",
    )
    manager.active_model = active_model
    manager.save_active_model(active_model)
    active_path = manager.root_path / "active_model.json"
    original_unlink = type(active_path).unlink

    def failing_unlink(self, *, missing_ok=False):
        if self == active_path:
            raise OSError("unlink failed")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(type(active_path), "unlink", failing_unlink)

    with pytest.raises(OSError, match="unlink failed"):
        await manager.clear_active_model_async()
    assert manager.active_model is active_model
    assert active_path.exists() is True


def test_save_active_model_uses_atomic_replace(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    replacements: list[tuple[str, str]] = []
    original_replace = provider_persistence_module.replace_with_retry

    def record_replace(source: str, destination: str) -> None:
        replacements.append((source, destination))
        original_replace(source, destination)

    monkeypatch.setattr(
        provider_persistence_module,
        "replace_with_retry",
        record_replace,
    )
    manager.save_active_model(
        ModelSlotConfig(provider_id="openai", model="gpt-5"),
    )

    active_path = manager.root_path / "active_model.json"
    assert replacements == [(replacements[0][0], str(active_path))]
    assert replacements[0][0] != str(active_path)
    assert json.loads(active_path.read_text(encoding="utf-8")) == {
        "provider_id": "openai",
        "model": "gpt-5",
    }


async def test_resume_local_model_restores_server_and_runtime_state(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    model_id = "AgentScope/QwenPaw-Flash-2B-Q4_K_M"
    manager.update_provider(
        "qwenpaw-local",
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
        provider_id="qwenpaw-local",
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

        async def setup_server(
            self,
            requested_model_id: str,
        ) -> LlamaCppServerSetupResult:
            self.restored_model_id = requested_model_id
            return LlamaCppServerSetupResult(
                port=43111,
                model_info=ModelInfo(
                    id=requested_model_id,
                    name=requested_model_id,
                    supports_multimodal=True,
                    supports_image=True,
                    supports_video=True,
                    probe_source="documentation",
                ),
            )

    local_manager = FakeLocalManager()

    await manager._resume_local_model(local_manager)

    provider = manager.get_provider("qwenpaw-local")

    assert local_manager.restored_model_id == model_id
    assert provider is not None
    assert provider.base_url == "http://127.0.0.1:43111/v1"
    assert [model.id for model in provider.extra_models] == [model_id]
    assert provider.extra_models[0].supports_multimodal is True
    assert provider.extra_models[0].supports_image is True
    assert provider.extra_models[0].supports_video is True
    assert provider.extra_models[0].probe_source == "documentation"


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


async def test_async_custom_provider_delete_rolls_back_on_disk_failure(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    custom = OpenAIProvider(
        id="custom-delete-failure",
        name="Custom Delete Failure",
        base_url="https://remove.example/v1",
        api_key="sk-remove",
    )
    await manager.add_custom_provider(custom)

    async def fail_to_thread(_func, *_args, **_kwargs):
        raise OSError("delete failed")

    monkeypatch.setattr(
        provider_manager_module.asyncio,
        "to_thread",
        fail_to_thread,
    )

    with pytest.raises(OSError, match="delete failed"):
        await manager.remove_custom_provider_async(
            "custom-delete-failure",
        )

    assert manager.get_provider("custom-delete-failure") is not None


async def test_custom_delete_rejects_inflight_discovery_save(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    await manager.add_custom_provider(
        ProviderInfo(
            id="custom-delete-race",
            name="Custom Delete Race",
            base_url="https://race.example/v1",
            chat_model="OpenAIChatModel",
        ),
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch_models(_self, timeout=5):
        _ = timeout
        started.set()
        await release.wait()
        return [ModelInfo(id="race-model", name="Race Model")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    discovery = asyncio.create_task(
        manager.discover_provider_models("custom-delete-race"),
    )
    await started.wait()
    assert await manager.remove_custom_provider_async("custom-delete-race")
    release.set()
    await discovery

    assert manager.get_provider("custom-delete-race") is None
    assert not (manager.custom_path / "custom-delete-race.json").exists()


async def test_connection_config_change_resets_model_availability(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    model = provider.models[0]
    model.availability_status = "permission_denied"
    model.availability_message = "old credential"
    model.availability_http_status = 401
    model.availability_retryable = False
    model.availability_checked_at = "2026-07-28T00:00:00+00:00"

    assert await manager.update_provider_async(
        "openai",
        {"api_key": "new-key"},
    )

    assert model.availability_status == "unverified"
    assert model.availability_message is None
    assert model.availability_http_status is None
    assert model.availability_retryable is True
    assert model.availability_checked_at is None


async def test_async_provider_update_commits_only_after_snapshot_write(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """A worker write must not expose a partially updated provider."""
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.api_key = "old-key"
    started = threading.Event()
    release = threading.Event()
    original_save = manager._save_provider_snapshot

    def delayed_save(*args, **kwargs):
        started.set()
        release.wait(timeout=2)
        return original_save(*args, **kwargs)

    monkeypatch.setattr(manager, "_save_provider_snapshot", delayed_save)
    update = asyncio.create_task(
        manager.update_provider_async("openai", {"api_key": "new-key"}),
    )
    assert await asyncio.to_thread(started.wait, 1)
    assert provider.api_key == "old-key"

    release.set()
    assert await update is True
    assert provider.api_key == "new-key"


async def test_stale_async_update_restores_live_snapshot_on_disk(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """A write that lost the revision race must not stay on disk.

    Without the compensating rewrite, the stale snapshot would silently
    swallow the concurrent winning update on the next restart.
    """
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.api_key = "winning-key"
    original_save = manager._save_provider_snapshot
    saved_keys = []

    def racing_save(provider_id, candidate, **kwargs):
        saved_keys.append(candidate.api_key)
        if len(saved_keys) == 1:
            # A concurrent update wins the revision race while this
            # detached snapshot is being written.
            manager._bump_provider_revision("openai")
        return original_save(provider_id, candidate, **kwargs)

    monkeypatch.setattr(manager, "_save_provider_snapshot", racing_save)

    result = await manager.update_provider_async(
        "openai",
        {"api_key": "stale-key"},
    )

    assert result is False
    assert provider.api_key == "winning-key"
    # The stale write happened first, then the compensating rewrite
    # restored the live provider state on disk.
    assert saved_keys == ["stale-key", "winning-key"]


async def test_async_provider_update_keeps_memory_on_write_failure(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """A failed snapshot write must leave the live provider untouched."""
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.api_key = "old-key"
    revision = manager._provider_revision("openai")

    def fail_save(*_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(manager, "_save_provider_snapshot", fail_save)

    with pytest.raises(OSError, match="write failed"):
        await manager.update_provider_async("openai", {"api_key": "new-key"})

    assert provider.api_key == "old-key"
    assert manager._provider_revision("openai") == revision


async def test_add_model_write_failure_preserves_provider_state(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    await manager.save_provider_config_async("openai", provider)
    provider_path = manager._provider_config_path("openai")
    disk_before = provider_path.read_bytes()
    revision = manager._provider_revision("openai")
    models_before = [model.id for model in provider.extra_models]

    def fail_save(*_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(manager, "_save_provider_snapshot", fail_save)

    with pytest.raises(OSError, match="write failed"):
        await manager.add_model_to_provider(
            "openai",
            ModelInfo(id="failed-add", name="Failed Add"),
        )

    assert [model.id for model in provider.extra_models] == models_before
    assert manager._provider_revision("openai") == revision
    assert provider_path.read_bytes() == disk_before


async def test_hide_model_write_failure_preserves_provider_state(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    await manager.save_provider_config_async("openai", provider)
    provider_path = manager._provider_config_path("openai")
    disk_before = provider_path.read_bytes()
    revision = manager._provider_revision("openai")
    hidden_before = list(provider.hidden_model_ids)

    def fail_save(*_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(manager, "_save_provider_snapshot", fail_save)

    with pytest.raises(OSError, match="write failed"):
        await manager.set_model_hidden(
            "openai",
            "failed-hidden",
            hidden=True,
        )

    assert provider.hidden_model_ids == hidden_before
    assert manager._provider_revision("openai") == revision
    assert provider_path.read_bytes() == disk_before


async def test_update_model_write_failure_preserves_provider_state(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    model = provider.models[0]
    await manager.save_provider_config_async("openai", provider)
    provider_path = manager._provider_config_path("openai")
    disk_before = provider_path.read_bytes()
    revision = manager._provider_revision("openai")
    max_tokens_before = model.max_tokens

    def fail_save(*_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(manager, "_save_provider_snapshot", fail_save)

    with pytest.raises(OSError, match="write failed"):
        await manager.update_model_config(
            "openai",
            model.id,
            {"max_tokens": max_tokens_before + 1},
        )

    assert model.max_tokens == max_tokens_before
    assert manager._provider_revision("openai") == revision
    assert provider_path.read_bytes() == disk_before


async def test_delete_model_write_failure_preserves_provider_state(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.extra_models.append(
        ModelInfo(id="failed-delete", name="Failed Delete"),
    )
    await manager.save_provider_config_async("openai", provider)
    provider_path = manager._provider_config_path("openai")
    disk_before = provider_path.read_bytes()
    revision = manager._provider_revision("openai")

    def fail_save(*_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(manager, "_save_provider_snapshot", fail_save)

    with pytest.raises(OSError, match="write failed"):
        await manager.delete_model_from_provider("openai", "failed-delete")

    assert provider.get_model_info("failed-delete") is not None
    assert "failed-delete" not in provider.removed_model_ids
    assert manager._provider_revision("openai") == revision
    assert provider_path.read_bytes() == disk_before


async def test_capability_probe_write_failure_preserves_provider_state(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert isinstance(provider, OpenAIProvider)
    model = ModelInfo(
        id="failed-probe",
        name="Failed Probe",
        supports_image=False,
        supports_video=False,
        supports_multimodal=False,
        probe_source="catalog",
    )
    provider.extra_models.append(model)
    await manager.save_provider_config_async("openai", provider)
    provider_path = manager._provider_config_path("openai")
    disk_before = provider_path.read_bytes()
    revision = manager._provider_revision("openai")

    async def probe(_self, _model_id, **_kwargs):
        return SimpleNamespace(
            supports_image=True,
            supports_video=True,
            supports_multimodal=True,
            image_message="ok",
            video_message="ok",
            probe_source="probed",
        )

    def fail_save(*_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(OpenAIProvider, "probe_model_multimodal", probe)
    monkeypatch.setattr(manager, "_save_provider_snapshot", fail_save)

    with pytest.raises(OSError, match="write failed"):
        await manager.probe_model_multimodal("openai", "failed-probe")

    assert model.supports_image is False
    assert model.supports_video is False
    assert model.supports_multimodal is False
    assert model.probe_source == "catalog"
    assert manager._provider_revision("openai") == revision
    assert provider_path.read_bytes() == disk_before


async def test_stale_model_check_does_not_restore_old_failure(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    model = provider.models[0]
    started = asyncio.Event()
    release = asyncio.Event()

    async def check_model_connection(_self, model_id, timeout=5):
        _ = model_id, timeout
        started.set()
        await release.wait()
        return ModelConnectionResult(
            success=False,
            message="old credential",
            http_status=401,
        )

    monkeypatch.setattr(
        OpenAIProvider,
        "check_model_connection",
        check_model_connection,
    )
    check = asyncio.create_task(
        manager.check_provider_model("openai", model.id),
    )
    await started.wait()
    assert await manager.update_provider_async(
        "openai",
        {"api_key": "new-key"},
    )
    release.set()
    await check

    assert model.availability_status == "unverified"
    assert model.availability_message is None


async def test_recreated_custom_provider_rejects_old_discovery(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider_data = ProviderInfo(
        id="custom-recreated",
        name="Custom Recreated",
        base_url="https://old.example/v1",
        chat_model="OpenAIChatModel",
    )
    await manager.add_custom_provider(provider_data)
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch_models(_self, timeout=5):
        _ = timeout
        started.set()
        await release.wait()
        return [ModelInfo(id="old-model", name="Old Model")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    discovery = asyncio.create_task(
        manager.discover_provider_models("custom-recreated"),
    )
    await started.wait()
    assert await manager.remove_custom_provider_async("custom-recreated")
    await manager.add_custom_provider(
        provider_data.model_copy(
            update={"base_url": "https://new.example/v1"},
        ),
    )
    release.set()
    await discovery

    recreated = manager.get_provider("custom-recreated")
    assert recreated is not None
    assert recreated.base_url == "https://new.example/v1"
    assert recreated.get_discovered_model_info("old-model") is None


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


async def test_add_custom_provider_avoids_plugin_id_collision(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    plugin_id = "plugin-openai"
    plugin_info = ProviderInfo(
        id=plugin_id,
        name="Plugin OpenAI",
        base_url="https://plugin.example/v1",
    )
    manager.plugin_providers[plugin_id] = {
        "info": plugin_info,
        "class": OpenAIProvider,
    }
    plugin_path = manager.plugin_path / f"{plugin_id}.json"
    plugin_path.write_text(
        json.dumps(plugin_info.model_dump()),
        encoding="utf-8",
    )

    created = await manager.add_custom_provider(
        OpenAIProvider(
            id=plugin_id,
            name="Custom OpenAI",
            base_url="https://custom.example/v1",
        ),
    )

    assert created.id == "plugin-openai-new"
    assert json.loads(plugin_path.read_text(encoding="utf-8"))["name"] == (
        "Plugin OpenAI"
    )
    assert (manager.custom_path / "plugin-openai-new.json").exists()


async def test_provider_info_exposes_derived_thinking_capability(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("dashscope")
    assert provider is not None
    model_id = "newly-discovered-dashscope-model"
    provider.extra_models.append(
        ModelInfo(
            id=model_id,
            name="Discovered DashScope Model",
        ),
    )

    info = await provider.get_info()
    model = next(model for model in info.extra_models if model.id == model_id)

    assert model.supports_agent_thinking is True


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


def test_initial_builtin_save_uses_requested_builtin_path(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = OpenAIProvider(
        id="builtin-path-test",
        name="Builtin Path Test",
    )

    manager._save_provider(provider, is_builtin=True)

    assert (manager.builtin_path / "builtin-path-test.json").exists()
    assert not (manager.custom_path / "builtin-path-test.json").exists()


async def test_sync_update_and_async_discovery_share_atomic_transaction(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    save_started = threading.Event()
    release_save = threading.Event()
    read_errors = []
    stop_reading = threading.Event()
    original_save = manager._save_provider_snapshot

    def hold_discovery_save(*args, **kwargs):
        snapshot = args[1]
        if snapshot.models_last_synced_at:
            save_started.set()
            assert release_save.wait(timeout=5)
        return original_save(*args, **kwargs)

    monkeypatch.setattr(
        manager,
        "_save_provider_snapshot",
        hold_discovery_save,
    )
    provider_path = manager.builtin_path / "openai.json"
    original_save("openai", provider)

    def read_json_until_stopped() -> None:
        while not stop_reading.is_set():
            try:
                json.loads(provider_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                read_errors.append(exc)
            except OSError:
                continue
            time.sleep(0.001)

    reader = threading.Thread(target=read_json_until_stopped)
    reader.start()

    async def fetch_models(_self, timeout: float = 10):
        del timeout
        return [ModelInfo(id="fresh-model", name="Fresh Model")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    discovery_save = asyncio.create_task(
        manager.discover_provider_models(
            "openai",
        ),
    )
    assert await asyncio.to_thread(save_started.wait, 5)
    sync_update = asyncio.create_task(
        asyncio.to_thread(
            manager.update_provider,
            "openai",
            {"api_key": "new-key"},
        ),
    )
    await asyncio.sleep(0.05)
    assert sync_update.done() is False
    try:
        release_save.set()
        await asyncio.gather(discovery_save, sync_update)
    finally:
        stop_reading.set()
        reader.join(timeout=5)

    persisted = json.loads(provider_path.read_text(encoding="utf-8"))
    reloaded = manager.load_provider("openai", is_builtin=True)
    assert persisted["id"] == "openai"
    assert reloaded is not None
    assert reloaded.api_key == "new-key"
    assert not read_errors
    assert reloaded.models_last_synced_at is not None
    assert reloaded.get_discovered_model_info("fresh-model") is not None


@pytest.mark.parametrize(
    ("saved_length", "expected_configured"),
    [
        (64_000, True),
        (DEFAULT_CONTEXT_WINDOW, False),
    ],
)
def test_legacy_builtin_context_window_infers_non_default_as_configured(
    isolated_secret_dir,
    saved_length: int,
    expected_configured: bool,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    data = provider.model_dump()
    for model in data["models"]:
        model.pop("max_input_length_configured", None)
        if model["id"] == "gpt-4o":
            model["max_input_length"] = saved_length

    builtin_path = isolated_secret_dir / "providers" / "builtin"
    (builtin_path / "openai.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    reloaded = ProviderManager().get_provider("openai")
    assert reloaded is not None
    model = reloaded.get_model_info("gpt-4o")
    assert model is not None
    assert model.max_input_length == saved_length
    assert model.max_input_length_configured is expected_configured


def test_builtin_capability_probe_results_survive_storage_reload(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    data = provider.model_dump()
    for model in data["models"]:
        if model["id"] == "gpt-4o":
            model["supports_multimodal"] = False
            model["supports_image"] = False
            model["supports_video"] = False
            model["max_input_length_auto_detected"] = 256_000
            model["availability_status"] = "permission_denied"
            model["availability_message"] = "status=403: forbidden"
            model["availability_http_status"] = 403
            model["availability_retryable"] = False
            model["availability_checked_at"] = "2026-07-27T00:00:00+00:00"

    builtin_path = isolated_secret_dir / "providers" / "builtin"
    (builtin_path / "openai.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    reloaded = ProviderManager().get_provider("openai")
    assert reloaded is not None
    model = reloaded.get_model_info("gpt-4o")
    assert model is not None
    assert model.supports_multimodal is False
    assert model.supports_image is False
    assert model.supports_video is False
    assert model.max_input_length_auto_detected == 256_000
    assert model.availability_status == "permission_denied"
    assert model.availability_http_status == 403
    assert model.availability_retryable is False


async def test_openrouter_metadata_probe_restores_and_persists_capabilities(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openrouter")
    assert isinstance(provider, OpenRouterProvider)

    model_id = "x-ai/grok-4.5"
    poisoned_model = ModelInfo(
        id=model_id,
        name="Grok 4.5",
        supports_multimodal=False,
        supports_image=False,
        supports_video=False,
        probe_source="probed",
    )
    monkeypatch.setattr(provider, "extra_models", [poisoned_model])

    row = SimpleNamespace(
        id=model_id,
        name="Grok 4.5",
        pricing=None,
        architecture={
            "input_modalities": ["text", "image", "file"],
            "output_modalities": ["text"],
        },
    )

    class FakeModels:
        async def list(self, timeout=None):
            _ = timeout
            return SimpleNamespace(data=[row])

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(
        OpenRouterProvider,
        "_client",
        lambda self, timeout=30: fake_client,
    )

    result = await manager.probe_model_multimodal("openrouter", model_id)

    assert result["supports_image"] is True
    assert poisoned_model.supports_image is True
    assert poisoned_model.supports_video is False
    assert poisoned_model.supports_multimodal is True
    assert poisoned_model.probe_source == "documentation"

    saved_path = (
        isolated_secret_dir / "providers" / "builtin" / "openrouter.json"
    )
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    saved_model = next(
        item for item in saved["extra_models"] if item["id"] == model_id
    )
    assert saved_model["supports_image"] is True
    assert saved_model["supports_multimodal"] is True
    assert saved_model["probe_source"] == "documentation"


async def test_openrouter_inconclusive_probe_does_not_overwrite_capabilities(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openrouter")
    assert isinstance(provider, OpenRouterProvider)

    model_id = "x-ai/grok-4.5"
    configured_model = ModelInfo(
        id=model_id,
        name="Grok 4.5",
        supports_multimodal=True,
        supports_image=True,
        supports_video=False,
        probe_source="documentation",
    )
    monkeypatch.setattr(provider, "extra_models", [configured_model])

    class FakeModels:
        async def list(self, timeout=None):
            _ = timeout
            return SimpleNamespace(data=[])

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(
        OpenRouterProvider,
        "_client",
        lambda self, timeout=30: fake_client,
    )
    save_calls = []
    monkeypatch.setattr(
        manager,
        "_save_provider",
        lambda *args, **kwargs: save_calls.append((args, kwargs)),
    )

    with pytest.raises(ProviderError, match="was not found"):
        await manager.probe_model_multimodal("openrouter", model_id)

    assert configured_model.supports_multimodal is True
    assert configured_model.supports_image is True
    assert configured_model.supports_video is False
    assert configured_model.probe_source == "documentation"
    assert not save_calls


def test_update_provider_for_unknown_returns_false(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()

    ok = manager.update_provider("unknown-provider", {"api_key": "sk-x"})

    assert ok is False


async def test_discovery_keeps_user_models_and_persists_cache(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.discovered_models = []
    provider.extra_models = [
        ModelInfo(id="user-only", name="User Only", source="user"),
    ]

    async def fetch_models(_self, timeout=5):
        assert timeout == 10
        assert provider.models_syncing is True
        return [
            ModelInfo(
                id="remote-new",
                name="Remote New",
                max_input_length_auto_detected=256_000,
            ),
        ]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("openai")

    assert result.success is True
    assert result.discovered_count == 1
    assert result.last_synced_at
    assert provider.models_syncing is False
    assert [model.id for model in provider.extra_models] == ["user-only"]
    assert [model.id for model in provider.discovered_models] == [
        "remote-new",
    ]
    assert provider.discovered_models[0].source == "discovered"
    candidate = provider.get_discovered_model_info("remote-new")
    assert candidate is not None
    assert candidate.max_input_length_auto_detected == 256_000

    reloaded = ProviderManager().get_provider("openai")
    assert reloaded is not None
    assert reloaded.has_model("user-only")
    assert not reloaded.has_model("remote-new")
    assert reloaded.get_discovered_model_info("remote-new") is not None
    assert reloaded.models_last_synced_at == result.last_synced_at


async def test_overlapping_discovery_keeps_latest_syncing_state(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    calls = 0

    async def fetch_models(_self, timeout=5):
        nonlocal calls
        _ = timeout
        calls += 1
        call_number = calls
        if call_number == 1:
            first_started.set()
            await first_release.wait()
        else:
            second_started.set()
            await second_release.wait()
        return [ModelInfo(id=f"remote-{call_number}", name="Remote")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    first = asyncio.create_task(
        manager.discover_provider_models("openai"),
    )
    await first_started.wait()
    second = asyncio.create_task(
        manager.discover_provider_models("openai"),
    )
    await second_started.wait()

    assert provider.models_syncing is True
    first_release.set()
    await first
    assert provider.models_syncing is True

    second_release.set()
    await second
    assert provider.models_syncing is False


async def test_failed_discovery_preserves_last_cache_and_user_models(
    isolated_secret_dir,
    monkeypatch,
    caplog,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.discovered_models = []
    provider.discovered_models = [
        ModelInfo(
            id="cached-remote",
            name="Cached Remote",
            source="discovered",
        ),
    ]
    provider.extra_models = [
        ModelInfo(id="user-only", name="User Only", source="user"),
    ]

    async def fetch_models(_self, timeout=5):
        raise TimeoutError("model discovery timed out")

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("openai")

    assert result.success is False
    assert result.used_static_fallback is True
    assert result.error == "model discovery timed out"
    assert provider.models_last_sync_error == result.error
    assert provider.models_syncing is False
    assert [model.id for model in provider.discovered_models] == [
        "cached-remote",
    ]
    assert [model.id for model in provider.extra_models] == ["user-only"]
    assert {model.id for model in result.models} >= {"cached-remote"}
    assert "user-only" not in {model.id for model in result.models}
    assert caplog.records[-1].getMessage() == (
        "Model discovery failed; using static fallback"
    )


async def test_discovery_write_failure_preserves_live_model_cache(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """A failed discovery write must not replace the running cache."""
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.discovered_models = [
        ModelInfo(id="cached-model", name="Cached Model", source="discovered"),
    ]
    original_save = manager._save_provider_snapshot
    attempts = 0

    async def fetch_models(_self, timeout=5):
        _ = timeout
        return [ModelInfo(id="new-model", name="New Model")]

    def fail_first_save(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("write failed")
        return original_save(*args, **kwargs)

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    monkeypatch.setattr(manager, "_save_provider_snapshot", fail_first_save)

    result = await manager.discover_provider_models("openai")

    assert result.success is False
    assert [model.id for model in provider.discovered_models] == [
        "cached-model",
    ]
    assert provider.models_syncing is False


def _configure_single_startup_provider(
    manager: ProviderManager,
) -> OpenAIProvider:
    for candidate in manager.builtin_providers.values():
        candidate.model_sync_mode = "manual"
    provider = manager.get_provider("openai")
    assert isinstance(provider, OpenAIProvider)
    provider.model_sync_mode = "startup"
    provider.support_model_discovery = True
    provider.discovery_requires_auth = False
    return provider


def test_prepare_startup_discovery_marks_provider_syncing(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = _configure_single_startup_provider(manager)

    provider_ids = manager.prepare_startup_provider_model_sync()

    assert provider_ids == ["openai"]
    assert provider.models_syncing is True


@pytest.mark.parametrize("should_fail", [False, True])
async def test_startup_discovery_clears_syncing_after_completion(
    isolated_secret_dir,
    monkeypatch,
    should_fail: bool,
) -> None:
    manager = ProviderManager()
    provider = _configure_single_startup_provider(manager)
    provider_ids = manager.prepare_startup_provider_model_sync()

    async def discover(_provider_id: str):
        assert provider.models_syncing is True
        if should_fail:
            raise RuntimeError("startup discovery failed")
        return SimpleNamespace()

    monkeypatch.setattr(manager, "discover_provider_models", discover)

    await manager.sync_startup_provider_models(provider_ids)

    assert provider.models_syncing is False


async def test_startup_discovery_clears_syncing_when_cancelled(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = _configure_single_startup_provider(manager)
    provider_ids = manager.prepare_startup_provider_model_sync()
    started = asyncio.Event()

    async def discover(_provider_id: str):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(manager, "discover_provider_models", discover)
    task = asyncio.create_task(
        manager.sync_startup_provider_models(provider_ids),
    )
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.models_syncing is False


def test_models_syncing_is_not_persisted_and_legacy_true_is_reset(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = OpenAIProvider(
        id="custom-sync-state",
        name="Custom Sync State",
        models_syncing=True,
    )

    manager._save_provider(provider, is_builtin=False)
    provider_path = manager.custom_path / "custom-sync-state.json"
    payload = json.loads(provider_path.read_text(encoding="utf-8"))
    assert "models_syncing" not in payload

    payload["models_syncing"] = True
    provider_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    reloaded = ProviderManager().get_provider("custom-sync-state")
    assert reloaded is not None
    assert reloaded.models_syncing is False


async def test_removed_builtin_model_stays_removed_after_restart(
    isolated_secret_dir,
) -> None:
    """A built-in model tombstone survives manager reconstruction."""
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    model_id = provider.models[0].id

    info = await manager.delete_model_from_provider("openai", model_id)

    assert model_id in info.removed_model_ids
    assert all(model.id != model_id for model in info.models)
    assert provider.get_model_info(model_id) is None

    reloaded = ProviderManager().get_provider("openai")
    assert reloaded is not None
    assert model_id in reloaded.removed_model_ids
    assert reloaded.get_model_info(model_id) is None


async def test_removed_discovery_model_does_not_return_on_refresh(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """API discovery continues to respect an explicit removal."""
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.discovered_models = [
        ModelInfo(id="remote-removed", name="Remote Removed"),
    ]

    await manager.delete_model_from_provider("openai", "remote-removed")

    async def fetch_models(_self, timeout=5):
        _ = timeout
        return [ModelInfo(id="remote-removed", name="Remote Removed")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    result = await manager.discover_provider_models("openai")

    assert result.success is True
    assert all(model.id != "remote-removed" for model in result.models)
    assert provider.get_discovered_model_info("remote-removed") is None


async def test_stale_snapshot_cannot_clear_new_tombstone(
    isolated_secret_dir,
) -> None:
    """Detached snapshots cannot overwrite the live removed-model state."""
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    stale = provider.model_copy(deep=True)

    await manager.delete_model_from_provider("openai", "stale-model")
    await manager.save_provider_config_async("openai", stale)

    reloaded = ProviderManager().get_provider("openai")
    assert reloaded is not None
    assert "stale-model" in reloaded.removed_model_ids


async def test_explicit_add_restores_tombstoned_model(
    isolated_secret_dir,
) -> None:
    """Add-before-use is the explicit recovery path for a removed model."""
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    model_id = provider.models[0].id

    await manager.delete_model_from_provider("openai", model_id)
    info = await manager.add_model_to_provider(
        "openai",
        ModelInfo(id=model_id, name=model_id),
    )

    assert model_id not in info.removed_model_ids
    assert any(model.id == model_id for model in info.models)
    assert provider.get_model_info(model_id) is not None


async def test_hidden_and_removed_model_states_are_independent(
    isolated_secret_dir,
) -> None:
    """Candidate visibility changes must not clear removal tombstones."""
    manager = ProviderManager()

    await manager.delete_model_from_provider("openai", "removed-model")
    await manager.set_model_hidden(
        "openai",
        "hidden-model",
        hidden=True,
    )
    info = await manager.set_model_hidden(
        "openai",
        "hidden-model",
        hidden=False,
    )

    assert info.hidden_model_ids == []
    assert info.removed_model_ids == ["removed-model"]


async def test_removal_invalidates_inflight_discovery(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """A discovery started before removal cannot restore its model."""
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch_models(_self, timeout=5):
        _ = timeout
        started.set()
        await release.wait()
        return [ModelInfo(id="racing-model", name="Racing Model")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    discovery = asyncio.create_task(
        manager.discover_provider_models("openai"),
    )
    await started.wait()
    await manager.delete_model_from_provider("openai", "racing-model")
    release.set()
    result = await discovery

    assert result.success is True
    assert all(model.id != "racing-model" for model in result.models)
    assert provider.get_discovered_model_info("racing-model") is None


async def test_discovery_empty_result_surfaces_connection_error(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None

    async def fetch_models(_self, timeout=5):
        return []

    async def check_connection(_self, timeout=5):
        return False, "API error (status=401): invalid api key"

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    monkeypatch.setattr(
        OpenAIProvider,
        "check_connection",
        check_connection,
    )

    result = await manager.discover_provider_models("openai")

    assert result.success is False
    assert result.used_static_fallback is True
    assert "401" in result.error
    assert provider.models_last_sync_error == result.error


async def test_discovery_empty_catalog_uses_generic_message(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None

    async def fetch_models(_self, timeout=5):
        return []

    async def check_connection(_self, timeout=5):
        return True, ""

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    monkeypatch.setattr(
        OpenAIProvider,
        "check_connection",
        check_connection,
    )

    result = await manager.discover_provider_models("openai")

    assert result.success is False
    assert result.error == "Provider returned no models"


async def test_discovery_merges_catalog_when_flag_enabled(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("deepseek")
    assert provider is not None
    assert provider.merge_with_catalog is True
    catalog_ids = {model.id for model in provider.models}
    assert catalog_ids

    async def fetch_models(_self, timeout=5):
        return [ModelInfo(id="brand-new-remote", name="Brand New")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("deepseek")

    assert result.success is True
    discovered_ids = {model.id for model in provider.discovered_models}
    assert "brand-new-remote" in discovered_ids
    assert catalog_ids <= discovered_ids
    origins = {
        model.id: model.discovery_origin
        for model in provider.discovered_models
    }
    assert all(
        origins[model_id] in {"catalog", "both"} for model_id in catalog_ids
    )


async def test_discovery_skips_catalog_when_flag_disabled(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    assert provider.merge_with_catalog is False

    async def fetch_models(_self, timeout=5):
        return [ModelInfo(id="remote-only", name="Remote Only")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("openai")

    assert result.success is True
    assert [m.id for m in provider.discovered_models] == ["remote-only"]
    assert provider.discovered_models[0].discovery_origin == "api"


def test_replace_with_retry_recovers_from_transient_lock(
    monkeypatch,
) -> None:
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("locked")

    sleeps: list[float] = []
    monkeypatch.setattr(
        provider_persistence_module.os,
        "replace",
        flaky_replace,
    )
    monkeypatch.setattr(
        provider_persistence_module.time,
        "sleep",
        sleeps.append,
    )

    provider_persistence_module.replace_with_retry(
        "src",
        "dst",
        attempts=5,
        delay=0.01,
    )

    assert calls["count"] == 3
    assert sleeps == [0.01, 0.01]


def test_replace_with_retry_reraises_when_always_locked(
    monkeypatch,
) -> None:
    def always_locked(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(
        provider_persistence_module.os,
        "replace",
        always_locked,
    )
    monkeypatch.setattr(
        provider_persistence_module.time,
        "sleep",
        lambda delay: None,
    )

    with pytest.raises(PermissionError):
        provider_persistence_module.replace_with_retry(
            "src",
            "dst",
            attempts=3,
            delay=0,
        )


async def test_discovery_deduplicates_and_preserves_builtin_metadata(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.discovered_models = []
    builtin = provider.models[0]
    builtin.supports_image = True

    async def fetch_models(_self, timeout=5):
        return [
            ModelInfo(id=builtin.id, name="Remote Name"),
            ModelInfo(id=builtin.id, name="Duplicate"),
        ]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("openai", save=False)

    assert result.success is True
    assert len(result.models) == 1
    assert result.models[0].name == "Remote Name"
    assert result.models[0].supports_image is True
    assert provider.discovered_models == []


async def test_discovery_preserves_explicit_context_override(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openrouter")
    assert provider is not None
    provider.discovered_models = [
        ModelInfo(
            id="vendor/model",
            name="Configured Model",
            source="discovered",
            max_input_length=64_000,
            max_input_length_configured=True,
        ),
    ]

    async def fetch_models(_self, timeout=5):
        return [
            ModelInfo(
                id="vendor/model",
                name="Remote Model",
                max_input_length=1_000_000,
                max_input_length_auto_detected=1_000_000,
            ),
        ]

    monkeypatch.setattr(OpenRouterProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("openrouter")

    assert result.success is True
    model = provider.get_discovered_model_info("vendor/model")
    assert model is not None
    assert model.max_input_length == 64_000
    assert model.max_input_length_configured is True
    assert model.max_input_length_auto_detected == 1_000_000
    assert provider.get_context_size("vendor/model") == 64_000


async def test_discovery_applies_metadata_to_configured_model(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    configured = provider.models[0]
    configured.max_tokens = 1024
    configured.config_overrides = ["max_tokens"]

    async def fetch_models(_self, timeout=5):
        _ = timeout
        return [
            ModelInfo(
                id=configured.id,
                name="API Model Name",
                max_input_length_auto_detected=256_000,
                max_tokens=32_768,
                supports_image=True,
            ),
        ]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("openai")

    assert result.success is True
    assert configured.source == "builtin"
    assert configured.max_input_length_auto_detected == 256_000
    assert configured.max_tokens == 1024
    assert configured.supports_image is True
    assert provider.get_context_size(configured.id) == 256_000


def test_unchanged_model_config_does_not_create_overrides(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    model = provider.models[0]

    assert provider.update_model_config(
        model.id,
        {
            "generate_kwargs": dict(model.generate_kwargs),
            "max_tokens": model.max_tokens,
            "relay_reasoning": model.relay_reasoning,
            "thinking_enabled": model.thinking_enabled,
            "thinking_budget": model.thinking_budget,
            "reasoning_effort": model.reasoning_effort,
        },
    )

    assert model.config_overrides == []


def test_builtin_variants_do_not_share_model_instances(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    china = manager.get_provider("aliyun-tokenplan")
    international = manager.get_provider("aliyun-tokenplan-intl")

    assert china is not None
    assert international is not None
    assert china.models[0] is not international.models[0]

    original = international.models[0].max_tokens
    china.models[0].max_tokens = 4096

    assert international.models[0].max_tokens == original


async def test_discovery_preserves_model_config_overrides(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.discovered_models = [
        ModelInfo(
            id="remote-model",
            name="Remote Model",
            source="discovered",
        ),
    ]
    provider.discovered_models[0].max_tokens = 1234
    provider.discovered_models[0].generate_kwargs = {"temperature": 0.2}
    provider.discovered_models[0].config_overrides = [
        "max_tokens",
        "generate_kwargs",
    ]

    async def fetch_models(_self, timeout=5):
        return [
            ModelInfo(
                id="remote-model",
                name="Updated Remote Model",
                max_tokens=8192,
                generate_kwargs={"temperature": 1},
            ),
        ]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("openai")

    assert result.success is True
    model = provider.get_discovered_model_info("remote-model")
    assert model is not None
    assert model.name == "Updated Remote Model"
    assert model.max_tokens == 1234
    assert model.generate_kwargs == {"temperature": 0.2}
    assert set(model.config_overrides) >= {"max_tokens", "generate_kwargs"}


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


async def test_discovery_only_model_cannot_activate_until_added(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.discovered_models = [
        ModelInfo(id="candidate-only", name="Candidate", source="discovered"),
    ]

    with pytest.raises(ModelNotFoundException):
        await manager.activate_model("openai", "candidate-only")

    await manager.add_model_to_provider(
        "openai",
        ModelInfo(id="candidate-only", name="Candidate"),
    )
    await manager.activate_model("openai", "candidate-only")
    assert manager.active_model is not None
    assert manager.active_model.model == "candidate-only"


async def test_preview_discovery_does_not_invalidate_saved_refresh(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    call_count = 0

    async def fetch_models(_self, timeout=5):
        nonlocal call_count
        _ = timeout
        call_count += 1
        if call_count == 1:
            first_started.set()
            await release_first.wait()
            return [ModelInfo(id="saved-model", name="Saved")]
        return [ModelInfo(id="preview-model", name="Preview")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    saved_task = asyncio.create_task(
        manager.discover_provider_models("openai", save=True),
    )
    await first_started.wait()
    preview = await manager.discover_provider_models(
        "openai",
        save=False,
        provider_override=provider.model_copy(deep=True),
    )
    release_first.set()
    saved = await saved_task

    assert preview.models[0].id == "preview-model"
    assert saved.success is True
    assert provider.get_discovered_model_info("saved-model") is not None


async def test_plugin_discovery_and_check_update_fresh_provider_instance(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    plugin_id = "plugin-openai"
    manager.plugin_providers[plugin_id] = {
        "info": ProviderInfo(
            id=plugin_id,
            name="Plugin OpenAI",
            base_url="https://plugin.example/v1",
            chat_model="OpenAIChatModel",
        ),
        "class": OpenAIProvider,
    }

    async def fetch_models(_self, timeout=5):
        _ = timeout
        return [ModelInfo(id="plugin-model", name="Plugin Model")]

    async def check_model_connection(_self, model_id, timeout=5):
        _ = model_id, timeout
        return ModelConnectionResult(
            success=True,
        )

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    monkeypatch.setattr(
        OpenAIProvider,
        "check_model_connection",
        check_model_connection,
    )

    discovery = await manager.discover_provider_models(plugin_id)
    check = await manager.check_provider_model(plugin_id, "plugin-model")
    refreshed = manager.get_provider(plugin_id)

    assert discovery.success is True
    assert check.status == "available"
    assert refreshed is not None
    model = refreshed.get_discovered_model_info("plugin-model")
    assert model is not None
    assert model.availability_status == "available"


async def test_stale_plugin_discovery_preserves_new_configuration(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    plugin_id = "plugin-concurrent"
    manager.plugin_providers[plugin_id] = {
        "info": ProviderInfo(
            id=plugin_id,
            name="Plugin Concurrent",
            api_key="old-key",
            base_url="https://old.example/v1",
            chat_model="OpenAIChatModel",
        ),
        "class": OpenAIProvider,
    }
    discovery_started = asyncio.Event()
    release_discovery = asyncio.Event()

    async def fetch_models(_self, timeout=5):
        _ = timeout
        discovery_started.set()
        await release_discovery.wait()
        return [ModelInfo(id="fresh-model", name="Fresh Model")]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    discovery = asyncio.create_task(
        manager.discover_provider_models(plugin_id),
    )
    await discovery_started.wait()
    await manager.update_provider_async(
        plugin_id,
        {
            "api_key": "new-key",
            "base_url": "https://new.example/v1",
        },
    )
    release_discovery.set()
    await discovery

    provider = manager.get_provider(plugin_id)
    assert provider is not None
    assert provider.api_key == "new-key"
    assert provider.base_url == "https://new.example/v1"
    assert provider.get_discovered_model_info("fresh-model") is None


async def test_plugin_availability_preserves_discovery_state(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    plugin_id = "plugin-availability"
    manager.plugin_providers[plugin_id] = {
        "info": ProviderInfo(
            id=plugin_id,
            name="Plugin Availability",
            chat_model="OpenAIChatModel",
            discovered_models=[
                ModelInfo(id="checked-model", name="Checked Model"),
            ],
        ),
        "class": OpenAIProvider,
    }
    check_started = asyncio.Event()
    release_check = asyncio.Event()

    async def check_model_connection(_self, model_id, timeout=5):
        _ = model_id, timeout
        check_started.set()
        await release_check.wait()
        return ModelConnectionResult(success=True)

    monkeypatch.setattr(
        OpenAIProvider,
        "check_model_connection",
        check_model_connection,
    )
    check = asyncio.create_task(
        manager.check_provider_model(plugin_id, "checked-model"),
    )
    await check_started.wait()
    refreshed = manager.get_provider(plugin_id)
    assert refreshed is not None
    refreshed.discovered_models.append(
        ModelInfo(id="new-model", name="New Model"),
    )
    refreshed.models_last_synced_at = "2026-07-28T00:00:00+00:00"
    await manager.save_provider_config_async(
        plugin_id,
        refreshed,
        update_kind="discovery",
    )
    release_check.set()
    await check

    provider = manager.get_provider(plugin_id)
    assert provider is not None
    assert provider.models_last_synced_at == "2026-07-28T00:00:00+00:00"
    assert provider.get_discovered_model_info("new-model") is not None
    checked = provider.get_discovered_model_info("checked-model")
    assert checked is not None
    assert checked.availability_status == "available"


async def test_plugin_save_failure_does_not_mutate_canonical_state(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    plugin_id = "plugin-write-failure"
    manager.plugin_providers[plugin_id] = {
        "info": ProviderInfo(
            id=plugin_id,
            name="Plugin Write Failure",
            api_key="old-key",
            chat_model="OpenAIChatModel",
        ),
        "class": OpenAIProvider,
    }

    def fail_save(_provider_id, _provider, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(manager, "_save_provider_snapshot", fail_save)

    with pytest.raises(OSError, match="write failed"):
        await manager.update_provider_async(
            plugin_id,
            {"api_key": "new-key"},
        )

    provider = manager.get_provider(plugin_id)
    assert provider is not None
    assert provider.api_key == "old-key"


async def test_async_plugin_registration_runs_prepare_off_event_loop(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    called_in_thread = False
    original = manager._prepare_plugin_registration

    def prepare(*args, **kwargs):
        nonlocal called_in_thread
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            called_in_thread = True
        return original(*args, **kwargs)

    monkeypatch.setattr(manager, "_prepare_plugin_registration", prepare)
    await manager.register_plugin_provider_async(
        "plugin-async-register",
        OpenAIProvider,
        "Plugin Async Register",
        "https://plugin.example/v1",
        metadata={"chat_model": "OpenAIChatModel"},
    )

    assert called_in_thread is True
    assert manager.get_provider("plugin-async-register") is not None


async def test_model_check_uses_structured_http_status(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.discovered_models = [
        ModelInfo(
            id="missing-candidate",
            name="Missing Candidate",
            source="discovered",
        ),
    ]

    async def check_model_connection(_self, model_id, timeout=5):
        _ = model_id, timeout
        return ModelConnectionResult(
            success=False,
            message="request rejected",
            http_status=404,
        )

    monkeypatch.setattr(
        OpenAIProvider,
        "check_model_connection",
        check_model_connection,
    )

    result = await manager.check_provider_model(
        "openai",
        "missing-candidate",
    )

    assert result.status == "model_not_found"
    assert result.http_status == 404
    assert result.retryable is False
    candidate = provider.get_discovered_model_info("missing-candidate")
    assert candidate is not None
    assert candidate.availability_status == "model_not_found"
    assert result.verification == "live"
    assert candidate.availability_verification == "live"


async def test_legacy_tuple_model_check_is_unverified(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    model = provider.models[0]

    async def check_model_connection(_self, model_id, timeout=5):
        _ = model_id, timeout
        return True, "legacy plugin result"

    monkeypatch.setattr(
        OpenAIProvider,
        "check_model_connection",
        check_model_connection,
    )

    result = await manager.check_provider_model("openai", model.id)

    assert result.success is True
    assert result.verification == "unverified"
    assert model.availability_verification == "unverified"


async def test_provider_only_model_check_preserves_evidence(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    model = provider.models[0]

    async def check_model_connection(_self, model_id, timeout=5):
        _ = model_id, timeout
        return ModelConnectionResult(
            success=True,
            message="endpoint and credentials verified",
            verification="provider_only",
        )

    monkeypatch.setattr(
        OpenAIProvider,
        "check_model_connection",
        check_model_connection,
    )

    result = await manager.check_provider_model("openai", model.id)

    assert result.success is True
    assert result.verification == "provider_only"
    assert model.availability_verification == "provider_only"


async def test_remote_catalog_sync_runs_updates_in_threads(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    calls: list[str] = []
    thread_calls: list[object] = []

    monkeypatch.setattr(
        provider_manager_module.EnvVarLoader,
        "get_str",
        lambda name: (
            "https://example.invalid/catalog.json"
            if name
            in {
                provider_manager_module.model_catalog.CATALOG_URL_ENV,
                capability_baseline_module.CAPABILITY_URL_ENV,
            }
            else ""
        ),
    )

    def update_model() -> None:
        calls.append("model")

    def update_capability() -> None:
        calls.append("capability")

    async def to_thread(func, *args, **kwargs):
        thread_calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(
        provider_manager_module.model_catalog,
        "update_model_catalog",
        update_model,
    )
    monkeypatch.setattr(
        provider_manager_module.model_catalog,
        "load_model_catalog",
        lambda: {},
    )
    monkeypatch.setattr(
        capability_baseline_module,
        "update_capability_catalog",
        update_capability,
    )
    monkeypatch.setattr(
        provider_manager_module.asyncio,
        "to_thread",
        to_thread,
    )

    await manager.sync_remote_catalogs()

    assert calls == ["model", "capability"]
    assert thread_calls == [
        update_model,
        provider_manager_module.model_catalog.load_model_catalog,
        update_capability,
        manager._capability_registry.reload,
    ]


async def test_remote_catalog_sync_updates_live_manager_state(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """Apply OTA models without replacing provider or user state."""
    manager = ProviderManager()
    provider = manager.get_provider("deepseek")
    assert provider is not None
    provider.api_key = "live-key"
    provider.extra_models = [ModelInfo(id="user-model", name="User Model")]
    provider.hidden_model_ids = ["hidden-model"]
    provider.removed_model_ids = ["removed-model"]
    existing = provider.models[0]
    existing.max_tokens = 1234
    existing.config_overrides = ["max_tokens"]

    monkeypatch.setattr(
        provider_manager_module.EnvVarLoader,
        "get_str",
        lambda name: (
            "https://example.invalid/catalog.json"
            if name == provider_manager_module.model_catalog.CATALOG_URL_ENV
            else ""
        ),
    )
    monkeypatch.setattr(
        provider_manager_module.model_catalog,
        "update_model_catalog",
        lambda: None,
    )
    monkeypatch.setattr(
        provider_manager_module.model_catalog,
        "load_model_catalog",
        lambda: {
            "DEEPSEEK_MODELS": [
                ModelInfo(
                    id=existing.id,
                    name="Updated Name",
                    max_tokens=9999,
                ),
                ModelInfo(id="ota-model", name="OTA Model"),
            ],
        },
    )

    await manager.sync_remote_catalogs()

    assert manager.get_provider("deepseek") is provider
    assert provider.api_key == "live-key"
    assert [model.id for model in provider.extra_models] == ["user-model"]
    assert provider.hidden_model_ids == ["hidden-model"]
    assert provider.removed_model_ids == ["removed-model"]
    assert provider.get_model_info(existing.id).name == "Updated Name"
    assert provider.get_model_info(existing.id).max_tokens == 1234
    assert provider.get_model_info("ota-model") is not None


async def test_remote_catalog_sync_respects_removed_model(
    isolated_secret_dir,
) -> None:
    """Catalog reload may retain definitions but cannot revive a model."""
    manager = ProviderManager()
    provider = manager.get_provider("deepseek")
    assert provider is not None

    await manager.delete_model_from_provider("deepseek", "ota-removed")
    await manager._refresh_builtin_catalog(
        {
            "DEEPSEEK_MODELS": [
                ModelInfo(id="ota-removed", name="OTA Removed"),
            ],
        },
    )

    assert provider.get_model_info("ota-removed") is None
    info = await provider.get_info()
    assert all(model.id != "ota-removed" for model in info.models)


async def test_remote_capability_sync_updates_documentation_annotations(
    isolated_secret_dir,
    monkeypatch,
    tmp_path,
) -> None:
    packaged = tmp_path / "packaged.json"
    ota = tmp_path / "ota.json"
    local = tmp_path / "local.json"
    payload = {
        "schema_version": 1,
        "catalog_version": "packaged",
        "capabilities": [],
    }
    packaged.write_text(json.dumps(payload), encoding="utf-8")
    manager = ProviderManager()
    manager._capability_registry = (
        capability_baseline_module.ExpectedCapabilityRegistry(
            packaged,
            ota,
            local,
        )
    )
    provider = manager.get_provider("openai")
    assert provider is not None
    documented = provider.models[0]
    documented.supports_image = False
    documented.supports_video = False
    documented.supports_multimodal = False
    documented.probe_source = "documentation"
    probed = provider.models[1]
    probed.supports_image = False
    probed.supports_video = False
    probed.supports_multimodal = False
    probed.probe_source = "probed"

    updated = {
        "schema_version": 1,
        "catalog_version": "ota",
        "capabilities": [
            {
                "provider_id": "openai",
                "model_id": documented.id,
                "expected_image": True,
                "expected_video": False,
            },
            {
                "provider_id": "openai",
                "model_id": probed.id,
                "expected_image": True,
                "expected_video": True,
            },
        ],
    }

    monkeypatch.setattr(
        provider_manager_module.EnvVarLoader,
        "get_str",
        lambda name: (
            "https://example.invalid/capabilities.json"
            if name == capability_baseline_module.CAPABILITY_URL_ENV
            else ""
        ),
    )

    def update_capability() -> None:
        ota.write_text(json.dumps(updated), encoding="utf-8")

    monkeypatch.setattr(
        capability_baseline_module,
        "update_capability_catalog",
        update_capability,
    )

    await manager.sync_remote_catalogs()

    assert documented.supports_image is True
    assert documented.supports_video is False
    assert documented.supports_multimodal is True
    assert documented.probe_source == "documentation"
    assert probed.supports_image is False
    assert probed.supports_video is False
    assert probed.supports_multimodal is False
    assert probed.probe_source == "probed"


@pytest.mark.parametrize(
    ("chat_model", "provider_type"),
    [
        ("OpenAIChatModel", OpenAIProvider),
        ("OpenAIResponseModel", OpenAIResponseProvider),
        ("AnthropicChatModel", AnthropicProvider),
        ("GeminiChatModel", GeminiProvider),
    ],
)
def test_materialize_discovery_provider_uses_protocol_class(
    isolated_secret_dir,
    chat_model,
    provider_type,
) -> None:
    manager = ProviderManager()

    provider = manager.materialize_discovery_provider(
        "openai",
        {"chat_model": chat_model},
    )

    assert isinstance(provider, provider_type)
    assert provider.chat_model == chat_model


async def test_discovery_fetch_override_saves_to_canonical_provider(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    canonical = manager.get_provider("openai")
    assert canonical is not None
    fetch_provider = manager.materialize_discovery_provider(
        "openai",
        {"chat_model": "AnthropicChatModel"},
    )

    async def fetch_models(_self, timeout=5):
        _ = timeout
        return [ModelInfo(id="claude-test", name="Claude Test")]

    monkeypatch.setattr(AnthropicProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models(
        "openai",
        provider_override=fetch_provider,
    )

    assert result.success is True
    assert [model.id for model in canonical.discovered_models] == [
        "claude-test",
    ]


async def test_discovery_failure_probe_uses_override_provider(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    canonical = manager.get_provider("openai")
    assert canonical is not None
    canonical.api_key = "saved-key"
    override = canonical.model_copy(
        deep=True,
        update={"api_key": "temporary-key"},
    )

    async def fetch_models(self, timeout=5):
        _ = timeout
        assert self.api_key == "temporary-key"
        return []

    async def check_connection(self, timeout=5):
        _ = timeout
        if self.api_key == "temporary-key":
            return False, "Temporary credential rejected"
        return True, ""

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    monkeypatch.setattr(
        OpenAIProvider,
        "check_connection",
        check_connection,
    )

    result = await manager.discover_provider_models(
        "openai",
        save=False,
        provider_override=override,
    )

    assert result.success is False
    assert result.error == "Temporary credential rejected"


@pytest.mark.parametrize(
    ("error", "expected_kind"),
    [
        (TimeoutError("timed out"), "timeout"),
        (RuntimeError("status=401: invalid api key"), "authentication"),
        (RuntimeError("status=403: forbidden"), "authorization"),
        (ConnectionError("connection refused"), "network"),
        (RuntimeError("status=404: unsupported endpoint"), "unsupported"),
        (RuntimeError("status=503: unavailable"), "provider_unavailable"),
    ],
)
async def test_discovery_classifies_failures(
    isolated_secret_dir,
    monkeypatch,
    error,
    expected_kind,
) -> None:
    manager = ProviderManager()

    async def fetch_models(_self, timeout=5):
        _ = timeout
        raise error

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("openai")

    assert result.success is False
    assert result.error_kind == expected_kind


async def test_discovery_error_redacts_credentials_before_persisting(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()

    async def fetch_models(_self, timeout=5):
        _ = timeout
        raise RuntimeError("api_key=discovery-secret")

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)

    result = await manager.discover_provider_models("openai")
    provider = manager.get_provider("openai")

    assert result.success is False
    assert "discovery-secret" not in result.error
    assert result.error == "api_key=[redacted]"
    assert provider is not None
    assert provider.models_last_sync_error == result.error


def test_connection_message_sanitizer_redacts_credentials() -> None:
    message = "authorization=Bearer discovery-secret"

    assert (
        "discovery-secret"
        not in OpenAIProvider.sanitize_connection_message(message)
    )


async def test_add_model_to_provider_duplicate_id_raises(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    model_info = ModelInfo(id="custom-duplicate", name="Custom Duplicate")

    provider = await manager.add_model_to_provider("openai", model_info)

    assert [m.id for m in provider.extra_models].count("custom-duplicate") == 1

    with pytest.raises(ProviderError, match="already exists"):
        await manager.add_model_to_provider("openai", model_info)

    reloaded = ProviderManager()
    reloaded_provider = reloaded.get_provider("openai")

    assert reloaded_provider is not None
    assert reloaded_provider.extra_models is not None
    assert [m.id for m in reloaded_provider.extra_models].count(
        "custom-duplicate",
    ) == 1


async def test_add_discovered_model_copies_catalog_metadata(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    original = manager.get_provider("openai")
    assert original is not None
    original.discovered_models = [
        ModelInfo(
            id="remote-candidate",
            name="Remote Candidate",
            source="discovered",
            max_input_length_auto_detected=256_000,
            max_tokens=16_384,
            is_free=True,
        ),
    ]

    info = await manager.add_model_to_provider(
        "openai",
        ModelInfo(id="remote-candidate", name="Remote Candidate"),
    )

    assert all(model.id != "remote-candidate" for model in info.models)
    added = next(m for m in info.extra_models if m.id == "remote-candidate")
    assert added.source == "user"
    assert added.max_input_length_auto_detected == 256_000
    assert added.max_tokens == 16_384
    assert added.is_free is True


def test_model_check_classification() -> None:
    manager = ProviderManager.__new__(ProviderManager)

    denied = manager._classify_model_check(
        False,
        "API error (status=401): unauthorized",
    )
    assert denied.status == "permission_denied"
    assert denied.http_status == 401
    assert denied.retryable is False

    missing = manager._classify_model_check(
        False,
        "API error (status=404): model not found",
    )
    assert missing.status == "model_not_found"
    assert missing.retryable is False

    limited = manager._classify_model_check(
        False,
        "HTTP 429 rate limit exceeded",
    )
    assert limited.status == "rate_limited"
    assert limited.retryable is True

    temporary = manager._classify_model_check(False, "request timed out")
    assert temporary.status == "transient_error"
    assert temporary.retryable is True

    chat_incompatible = manager._classify_model_check(
        False,
        "status=400: Chat completions is not supported",
    )
    assert chat_incompatible.status == "incompatible_api"
    assert chat_incompatible.retryable is False

    structured_missing = manager._classify_model_check(
        False,
        "request rejected",
        http_status=404,
    )
    assert structured_missing.status == "model_not_found"
    assert structured_missing.http_status == 404
    assert structured_missing.retryable is False

    unsupported_tools = manager._classify_model_check(
        False,
        "status=400: The tool call is not supported",
    )
    assert unsupported_tools.status == "transient_error"
    assert unsupported_tools.retryable is True


def test_legacy_available_model_remains_available() -> None:
    model = ModelInfo.model_validate(
        {
            "id": "legacy-model",
            "name": "Legacy Model",
            "availability_status": "available",
        },
    )
    assert model.availability_status == "available"


def test_legacy_tool_probe_failure_becomes_unverified() -> None:
    model = ModelInfo.model_validate(
        {
            "id": "legacy-tool-probe-model",
            "name": "Legacy Tool Probe Model",
            "availability_status": "incompatible_api",
            "availability_message": "Tool probe returned no valid tool call",
            "availability_http_status": 400,
            "availability_retryable": False,
            "availability_checked_at": "2026-01-01T00:00:00+00:00",
            "supports_tool_calling": False,
        },
    )

    assert model.availability_status == "unverified"
    assert model.availability_message is None
    assert model.availability_http_status is None
    assert model.availability_retryable is True
    assert model.availability_checked_at is None


def test_legacy_chat_incompatibility_remains_blocking() -> None:
    model = ModelInfo.model_validate(
        {
            "id": "legacy-non-chat-model",
            "name": "Legacy Non-Chat Model",
            "availability_status": "incompatible_api",
            "availability_message": "Chat completions is not supported",
            "availability_retryable": False,
        },
    )

    assert model.availability_status == "incompatible_api"
    assert model.availability_retryable is False


async def test_kimi_discovery_merges_api_and_catalog(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("kimi-cn")
    assert provider is not None
    provider.discovered_models = []

    async def fetch_models(_self, timeout=5):
        _ = timeout
        return [
            ModelInfo(id="kimi-k2.6", name="Kimi K2.6"),
            ModelInfo(id="kimi-k2.5", name="Kimi K2.5"),
        ]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fetch_models)
    result = await manager.discover_provider_models("kimi-cn", save=False)

    by_id = {model.id: model for model in result.models}
    assert by_id["kimi-k2.6"].discovery_origin == "api"
    assert by_id["kimi-k2.5"].discovery_origin == "both"
    assert by_id["kimi-k2-thinking"].discovery_origin == "catalog"
    assert result.discovered_count == 2


async def test_rejects_unavailable_discovered_model(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.discovered_models = [
        ModelInfo(
            id="forbidden-model",
            name="Forbidden Model",
            source="discovered",
            availability_status="permission_denied",
            availability_message="status=401: unauthorized",
            availability_retryable=False,
        ),
    ]

    with pytest.raises(ProviderError, match="cannot be added"):
        await manager.add_model_to_provider(
            "openai",
            ModelInfo(id="forbidden-model", name="Forbidden Model"),
        )


async def test_rejects_activation_of_incompatible_model(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("openai")
    assert provider is not None
    provider.extra_models = [
        ModelInfo(
            id="chat-only-model",
            name="Chat Only Model",
            source="user",
            availability_status="incompatible_api",
            availability_message="Chat completions is not supported",
            availability_retryable=False,
        ),
    ]

    with pytest.raises(ProviderError, match="cannot be activated"):
        await manager.activate_model("openai", "chat-only-model")


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


def test_provider_group_metadata(isolated_secret_dir) -> None:
    """Providers in the same brand share provider_group."""
    manager = ProviderManager()

    aliyun_ids = [
        "dashscope",
        "aliyun-codingplan",
        "aliyun-codingplan-intl",
        "aliyun-tokenplan",
    ]
    for pid in aliyun_ids:
        p = manager.get_provider(pid)
        assert p is not None, f"{pid} not found"
        assert p.provider_group == "aliyun"
        assert p.provider_group_name == "Aliyun"

    kimi_ids = ["kimi-cn", "kimi-intl", "kimi-codingplan"]
    for pid in kimi_ids:
        p = manager.get_provider(pid)
        assert p is not None, f"{pid} not found"
        assert p.provider_group == "kimi"

    volcengine_ids = [
        "volcengine-cn",
        "volcengine-cn-codingplan",
        "volcengine-cn-agentplan",
    ]
    for pid in volcengine_ids:
        p = manager.get_provider(pid)
        assert p is not None, f"{pid} not found"
        assert p.provider_group == "volcengine"

    mimo_ids = ["mimo-tokenplan", "mimo"]
    for pid in mimo_ids:
        p = manager.get_provider(pid)
        assert p is not None, f"{pid} not found"
        assert p.provider_group == "mimo"


async def test_provider_group_in_get_info(isolated_secret_dir) -> None:
    """get_info() should include provider_group fields."""
    manager = ProviderManager()
    provider = manager.get_provider("dashscope")
    assert provider is not None

    info = await provider.get_info()
    assert info.provider_group == "aliyun"
    assert info.provider_group_name == "Aliyun"
    assert info.provider_variant == "dashscope"


def test_dashscope_max_inline_media_bytes_loaded_from_json(
    isolated_secret_dir,
) -> None:
    """A user-set ``max_inline_media_bytes`` in dashscope.json must be
    loaded by ``_init_from_storage`` and actually used by the capping
    formatter at runtime.

    Writes a builtin dashscope.json with a custom threshold, boots a fresh
    ``ProviderManager`` (which runs ``_init_from_storage``), and asserts
    the runtime builtin instance, not just the freshly deserialized one,
    carries the value through to the formatter.
    """
    builtin_path = isolated_secret_dir / "providers" / "builtin"
    builtin_path.mkdir(parents=True, exist_ok=True)

    dashscope_json = {
        "id": "dashscope",
        "name": "DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "sk-test",
        "chat_model": "DashScopeChatModel",
        "models": [{"id": "qwen3-max", "name": "Qwen3 Max"}],
        "max_inline_media_bytes": 4096,
    }
    (builtin_path / "dashscope.json").write_text(
        json.dumps(dashscope_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manager = ProviderManager()

    provider = manager.get_provider("dashscope")
    assert provider is not None
    # The runtime builtin must reflect the value loaded from disk, not the
    # field default (2 MB).
    assert provider.max_inline_media_bytes == 4096

    # And it must reach the capping formatter that actually guards requests.
    model = provider.get_chat_model_instance("qwen3-max")
    assert model.formatter.max_bytes == 4096


def test_dashscope_max_inline_media_bytes_defaults_when_absent(
    isolated_secret_dir,
) -> None:
    """An existing dashscope.json without the new key must fall back to the
    built-in default (2 MB) -- i.e. upgrading must not silently cap at 0."""
    builtin_path = isolated_secret_dir / "providers" / "builtin"
    builtin_path.mkdir(parents=True, exist_ok=True)

    # Legacy JSON: no max_inline_media_bytes key at all.
    dashscope_json = {
        "id": "dashscope",
        "name": "DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "sk-test",
        "chat_model": "DashScopeChatModel",
        "models": [{"id": "qwen3-max", "name": "Qwen3 Max"}],
    }
    (builtin_path / "dashscope.json").write_text(
        json.dumps(dashscope_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manager = ProviderManager()
    provider = manager.get_provider("dashscope")
    assert provider is not None
    assert provider.max_inline_media_bytes == 2 * 1024 * 1024
    assert (
        provider.get_chat_model_instance("qwen3-max").formatter.max_bytes
        == 2 * 1024 * 1024
    )


# ---------------------------------------------------------------------------
# Inline-media capping for the other providers (OpenAI / Anthropic / Gemini).
# Same oversized-request bug as DashScope: their agentscope formatters read
# every file:// media off disk and base64-inline the whole file on every
# call. Each provider now wires a shared capping formatter and exposes the
# same configurable ``max_inline_media_bytes`` field, restored by
# ``_init_from_storage`` via the generic ``hasattr`` branch.
# ---------------------------------------------------------------------------

# (provider_id, chat_model, model_id, capping_formatter_cls)
_CAPPING_PROVIDER_CASES = [
    ("openai", "OpenAIChatModel", "gpt-4o", _CappingOpenAIFormatter),
    (
        "anthropic",
        "AnthropicChatModel",
        "claude-3-5-sonnet",
        _CappingAnthropicFormatter,
    ),
    (
        "gemini",
        "GeminiChatModel",
        "gemini-2.0-flash",
        _CappingGeminiFormatter,
    ),
]


def _write_builtin_provider_json(
    isolated_secret_dir,
    provider_id: str,
    chat_model: str,
    model_id: str,
    *,
    with_cap: bool,
) -> None:
    """Write a builtin <id>.json under providers/builtin/.

    ``with_cap=True`` sets a 4096-byte ``max_inline_media_bytes``;
    ``False`` omits the key (legacy JSON) to exercise the default fallback.
    """
    builtin_path = isolated_secret_dir / "providers" / "builtin"
    builtin_path.mkdir(parents=True, exist_ok=True)

    data = {
        "id": provider_id,
        "name": provider_id.title(),
        "base_url": "https://example.test/v1",
        "api_key": "sk-test",
        "chat_model": chat_model,
        "models": [{"id": model_id, "name": model_id}],
    }
    if with_cap:
        data["max_inline_media_bytes"] = 4096
    (builtin_path / f"{provider_id}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "provider_id,chat_model,model_id,formatter_cls",
    _CAPPING_PROVIDER_CASES,
)
def test_max_inline_media_bytes_loaded_from_json(
    isolated_secret_dir,
    provider_id,
    chat_model,
    model_id,
    formatter_cls,
) -> None:
    """A user-set ``max_inline_media_bytes`` in <id>.json must be loaded by
    ``_init_from_storage`` and reach the runtime capping formatter."""
    _write_builtin_provider_json(
        isolated_secret_dir,
        provider_id,
        chat_model,
        model_id,
        with_cap=True,
    )

    manager = ProviderManager()
    provider = manager.get_provider(provider_id)
    assert provider is not None
    # Runtime builtin reflects the disk value, not the 2 MB default.
    assert provider.max_inline_media_bytes == 4096

    model = provider.get_chat_model_instance(model_id)
    assert isinstance(model.formatter, formatter_cls)
    assert model.formatter.max_bytes == 4096


@pytest.mark.parametrize(
    "provider_id,chat_model,model_id,formatter_cls",
    _CAPPING_PROVIDER_CASES,
)
def test_max_inline_media_bytes_defaults_when_absent(
    isolated_secret_dir,
    provider_id,
    chat_model,
    model_id,
    formatter_cls,
) -> None:
    """A legacy <id>.json without the key falls back to the 2 MB default
    (upgrading must not silently cap at 0)."""
    _write_builtin_provider_json(
        isolated_secret_dir,
        provider_id,
        chat_model,
        model_id,
        with_cap=False,
    )

    manager = ProviderManager()
    provider = manager.get_provider(provider_id)
    assert provider is not None
    assert provider.max_inline_media_bytes == 2 * 1024 * 1024

    model = provider.get_chat_model_instance(model_id)
    assert isinstance(model.formatter, formatter_cls)
    assert model.formatter.max_bytes == 2 * 1024 * 1024


async def test_github_models_provider_uses_new_endpoint_and_prefixes(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("github-models")

    assert provider is not None
    assert isinstance(provider, OpenAIProvider)
    assert isinstance(provider, GitHubModelsProvider)
    assert provider.base_url == "https://models.github.ai/inference"
    assert provider.freeze_url is False
    assert provider.api_key_prefix == "ghp_"
    assert provider.api_key_prefixes == ["ghp_", "github_pat_"]

    info = await provider.get_info()
    assert info.base_url == "https://models.github.ai/inference"
    assert info.freeze_url is False
    assert info.api_key_prefix == "ghp_"
    assert info.api_key_prefixes == ["ghp_", "github_pat_"]


async def test_update_config_persists_api_key_prefixes(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    provider = manager.get_provider("github-models")
    assert provider is not None

    manager.update_provider(
        "github-models",
        {"api_key_prefixes": ["ghp_", "github_pat_"]},
    )

    provider = manager.get_provider("github-models")
    assert provider.api_key_prefixes == ["ghp_", "github_pat_"]
    info = await provider.get_info()
    assert info.api_key_prefixes == ["ghp_", "github_pat_"]


async def test_activate_model_clears_rejects_media_for_selected_model(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """Re-selecting a model drops its stale rejects_media entry."""
    from qwenpaw.providers.model_capability_cache import (
        ModelCapabilityCache,
        get_capability_cache,
    )

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(id="ok", request=kwargs)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    monkeypatch.setattr(
        OpenAIProvider,
        "_client",
        lambda self, timeout=5: fake_client,
    )

    fresh = ModelCapabilityCache()
    monkeypatch.setattr(ModelCapabilityCache, "_instance", fresh)
    cache = get_capability_cache()
    cache.learn("openai:gpt-5", "rejects_media", True)
    assert cache.get("openai:gpt-5", "rejects_media", False) is True

    manager = ProviderManager()
    await manager.activate_model("openai", "gpt-5")

    assert cache.get("openai:gpt-5", "rejects_media", False) is False


async def test_activate_model_preserves_other_models_and_capabilities(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """Activating one model must not evict capabilities of other models."""
    from qwenpaw.providers.model_capability_cache import (
        ModelCapabilityCache,
        get_capability_cache,
    )

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(id="ok", request=kwargs)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    monkeypatch.setattr(
        OpenAIProvider,
        "_client",
        lambda self, timeout=5: fake_client,
    )

    fresh = ModelCapabilityCache()
    monkeypatch.setattr(ModelCapabilityCache, "_instance", fresh)
    cache = get_capability_cache()
    cache.learn("openai:gpt-5", "rejects_media", True)
    cache.learn("openai:gpt-5", "needs_reasoning_content", True)
    cache.learn("ollama:llama3", "rejects_media", True)

    manager = ProviderManager()
    await manager.activate_model("openai", "gpt-5")

    # rejects_media for the selected model is cleared
    assert cache.get("openai:gpt-5", "rejects_media", False) is False
    # needs_reasoning_content for the same model is preserved
    assert cache.get("openai:gpt-5", "needs_reasoning_content", False) is True
    # another model's entries are untouched
    assert cache.get("ollama:llama3", "rejects_media", False) is True


async def test_restore_latest_snapshot_removes_orphan_file(
    isolated_secret_dir,
) -> None:
    """A stale write for a since-removed provider must not resurrect it.

    The compensating rewrite runs after a detached snapshot write; when
    the provider was removed mid-flight there is no live state to
    restore, so the stale file must be deleted or the removed provider
    would come back on the next startup glob.
    """
    manager = ProviderManager()
    manager.custom_path.mkdir(parents=True, exist_ok=True)
    orphan_path = manager.custom_path / "ghost.json"
    orphan_path.write_text("{}", encoding="utf-8")

    assert manager.get_provider("ghost") is None
    await manager._restore_latest_snapshot("ghost", orphan_path)

    assert not orphan_path.exists()
