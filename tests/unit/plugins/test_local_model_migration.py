# -*- coding: utf-8 -*-
"""Default provisioning, saved provider state and selected-model recovery."""

# pylint: disable=protected-access

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from qwenpaw.plugins import _providers
from qwenpaw.plugins.local_model_legacy import migrate_local_model_plugin
from qwenpaw.plugins.settings import persist_plugin_settings
from qwenpaw.plugins.testing import PluginTestHost

PLUGIN_ID = "local-llamacpp"


def test_local_plugin_requires_new_sdk_before_import(monkeypatch):
    from qwenpaw.plugins import sdk_version
    from qwenpaw.plugins.errors import SDKCompatibilityError
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.local_model_legacy import bundled_local_source

    source = bundled_local_source()
    loader = PluginLoader([])
    _, manifest = loader.read_source_manifest(source)
    assert manifest.sdk["version"] == "1.2.0"

    monkeypatch.setattr(sdk_version, "SDK_VERSION", "1.1.0")
    with pytest.raises(
        SDKCompatibilityError,
        match="Unsupported SDK version: 1.2.0",
    ):
        loader.read_source_manifest(source)


async def test_new_user_stays_uninstalled(tmp_path):
    from qwenpaw.config.utils import load_config

    async with PluginTestHost(tmp_path / "host") as host:
        assert not await migrate_local_model_plugin(host._loader)
        assert host._loader.find_installed_plugin_dir(PLUGIN_ID) is None
        assert load_config().local_model_plugin_migrated
        assert PLUGIN_ID not in load_config().plugins


async def test_saved_local_settings_migrate_once(tmp_path):
    from qwenpaw.config.utils import load_config
    from qwenpaw.providers.provider_manager import ProviderManager
    from qwenpaw.plugins import local_model_legacy

    async with PluginTestHost(tmp_path / "host") as host:
        manager = ProviderManager.get_instance()
        (manager.builtin_path / "qwenpaw-local.json").write_text(
            '{"generate_kwargs": {"temperature": 0.7}}',
            encoding="utf-8",
        )
        manager._migrate_copaw_config()

        loader = host._loader
        assert await migrate_local_model_plugin(loader)
        path = loader.find_installed_plugin_dir(PLUGIN_ID)
        assert (path / "requirements.txt").is_file()
        assert load_config().local_model_plugin_migrated
        assert loader.registry.get_provider("qwenpaw-local") is None
        await loader.unload_plugin(PLUGIN_ID, delete_files=True)
        await local_model_legacy.load_upgraded_local_model(loader)
        assert loader.registry.get_provider("qwenpaw-local") is None
        assert not await migrate_local_model_plugin(loader)
        assert loader.find_installed_plugin_dir(PLUGIN_ID) is None


async def test_provisioning_preserves_explicit_disable(tmp_path, monkeypatch):
    from qwenpaw.plugins import local_model_legacy

    monkeypatch.setattr(
        local_model_legacy,
        "_used_local_models",
        lambda _path: True,
    )
    from qwenpaw.config.utils import load_config

    async with PluginTestHost(tmp_path / "host") as host:
        persist_plugin_settings(PLUGIN_ID, enabled=False)
        assert not await migrate_local_model_plugin(host._loader)
        assert host._loader.find_installed_plugin_dir(PLUGIN_ID) is not None
        assert load_config().plugins[PLUGIN_ID]["enabled"] is False


@pytest.mark.parametrize("selected", ["cloud", "A", "B"])
async def test_restore_requires_effective_selection_of_published_model(
    tmp_path,
    monkeypatch,
    selected,
):
    from qwenpaw.providers.provider_manager import ProviderManager

    restored = []

    @asynccontextmanager
    async def connect(model):
        restored.append(model)
        yield

    async with PluginTestHost(tmp_path / "host"):
        manager = ProviderManager.get_instance()
        binding = _providers.ProviderBinding(
            None,
            SimpleNamespace(id="qwenpaw-local"),
        )
        binding.provider = lambda: SimpleNamespace(
            enabled=True,
            all_models=lambda: [SimpleNamespace(id="A")],
        )
        binding.connect = connect
        monkeypatch.setattr(
            _providers,
            "configured_models",
            lambda _: [
                SimpleNamespace(
                    provider_id="openai"
                    if selected == "cloud"
                    else "qwenpaw-local",
                    model=selected,
                ),
            ],
        )
        assert manager is ProviderManager.get_instance()
        await binding.restore_selected()
    assert restored == (["A"] if selected == "A" else [])


@pytest.mark.parametrize("model_type", ["chat", "decision"])
def test_effective_choices_respect_agent_overrides_and_disabled_agents(
    monkeypatch,
    model_type,
):
    from qwenpaw.config import config, utils

    cloud = SimpleNamespace(provider_id="openai", model="cloud")
    local = SimpleNamespace(provider_id="qwenpaw-local", model="A")
    profiles = {
        "unreadable": SimpleNamespace(enabled=True),
        "override": SimpleNamespace(enabled=True),
        "inherit": SimpleNamespace(enabled=True),
        "disabled": SimpleNamespace(enabled=False),
    }
    monkeypatch.setattr(
        utils,
        "load_config",
        lambda: SimpleNamespace(agents=SimpleNamespace(profiles=profiles)),
    )

    def load_profile(agent):
        if agent == "unreadable":
            raise config.ConfigurationException(
                config_key="agent",
                message="invalid agent.json",
            )
        return SimpleNamespace(
            active_model=(
                cloud if model_type == "chat" and agent == "override" else None
            ),
            decision_model=(
                cloud
                if model_type == "decision" and agent == "override"
                else None
            ),
        )

    monkeypatch.setattr(config, "load_agent_config", load_profile)
    defaults = {"chat": None, "decision": None}
    defaults[model_type] = local
    assert _providers.configured_models(
        SimpleNamespace(default_models=defaults),
    ) == [
        cloud,
        local,
    ]


@pytest.mark.parametrize("legacy_id", ["copaw-local", "qwenpaw-local"])
@pytest.mark.parametrize("media_limit", [0, 1234])
async def test_old_provider_snapshot_moves_to_plugin_storage(
    tmp_path,
    legacy_id,
    media_limit,
):
    from qwenpaw.providers.provider_manager import ProviderManager
    from qwenpaw.providers.openai_provider import OpenAIProvider
    from qwenpaw.providers.provider_persistence import write_provider_snapshot
    from qwenpaw.security.secret_store import is_encrypted

    async with PluginTestHost(tmp_path / "host"):
        manager = ProviderManager.get_instance()
        source = manager.builtin_path / f"{legacy_id}.json"
        write_provider_snapshot(
            OpenAIProvider(
                id=legacy_id,
                name="Local",
                base_url="http://localhost:1234/v1",
                api_key="legacy-key",
                require_api_key=False,
                max_inline_media_bytes=media_limit,
                generate_kwargs={"temperature": 0.3},
                extra_models=[{"id": "A", "name": "A"}],
            ),
            source,
        )
        if legacy_id == "copaw-local":
            snapshot = json.loads(source.read_text(encoding="utf-8"))
            del snapshot["name"]
            snapshot["api_key"] = "legacy-key"
            source.write_text(json.dumps(snapshot), encoding="utf-8")
        manager._migrate_copaw_config()
        assert not source.exists()
        target = manager.plugin_path / "qwenpaw-local.json"
        assert is_encrypted(json.loads(target.read_text())["api_key"])
        assert manager.get_provider("qwenpaw-local") is None
        await manager.register_plugin_provider_async(
            "qwenpaw-local",
            OpenAIProvider,
            "Local",
            "",
            metadata={"require_api_key": False, "is_local": True},
        )
        provider = manager.get_provider("qwenpaw-local")
        assert provider.base_url == "http://localhost:1234/v1"
        assert provider.api_key == "legacy-key"
        assert provider.generate_kwargs == {"temperature": 0.3}
        assert provider.extra_models[0].id == "A"
        assert provider.max_inline_media_bytes == media_limit
        await manager.update_provider_async(
            "qwenpaw-local",
            {"generate_kwargs": {"temperature": 0.4}},
        )
        assert (
            manager.get_provider("qwenpaw-local").max_inline_media_bytes
            == media_limit
        )
        saved = json.loads(
            (manager.plugin_path / "qwenpaw-local.json").read_text(),
        )
        assert saved["max_inline_media_bytes"] == media_limit
        manager.unregister_plugin_provider("qwenpaw-local")
        await manager.register_plugin_provider_async(
            "qwenpaw-local",
            OpenAIProvider,
            "Local",
            "",
            metadata={"require_api_key": False, "is_local": True},
        )
        assert (
            manager.get_provider("qwenpaw-local").max_inline_media_bytes
            == media_limit
        )


@pytest.mark.parametrize("existing_target", [False, True])
async def test_local_provider_snapshot_migration_preserves_legacy_settings(
    tmp_path,
    existing_target,
):
    from qwenpaw.providers.provider_manager import ProviderManager

    async with PluginTestHost(tmp_path / "host"):
        manager = ProviderManager.get_instance()
        current = manager.builtin_path / "qwenpaw-local.json"
        legacy = manager.builtin_path / "copaw-local.json"
        target = manager.plugin_path / current.name
        current_config = {
            "id": "qwenpaw-local",
            "name": "QwenPaw Local",
            "base_url": "http://localhost:8080/v1",
            "extra_models": [{"id": "A", "name": "A"}],
            "generate_kwargs": {"temperature": 0.1},
            "max_inline_media_bytes": 1234,
        }
        legacy_config = {
            "id": "copaw-local",
            "base_url": "http://localhost:8081/v1",
            "extra_models": [{"id": "B", "name": "B"}],
            "generate_kwargs": {"temperature": 0.7},
        }
        current.write_text(json.dumps(current_config), encoding="utf-8")
        legacy.write_text(json.dumps(legacy_config), encoding="utf-8")
        target_config = {
            **current_config,
            "base_url": "http://localhost:8082/v1",
        }
        if existing_target:
            target.write_text(json.dumps(target_config), encoding="utf-8")

        manager._migrate_copaw_config()

        saved = json.loads(target.read_text(encoding="utf-8"))
        if existing_target:
            assert saved == target_config
            assert current.exists() and legacy.exists()
        else:
            assert saved["id"] == "qwenpaw-local"
            assert saved["max_inline_media_bytes"] == 1234
            for field in ("base_url", "extra_models", "generate_kwargs"):
                assert saved[field] == legacy_config[field]
            assert not current.exists() and not legacy.exists()


@pytest.mark.parametrize("broken_id", ["copaw-local", "qwenpaw-local"])
async def test_local_snapshot_migration_keeps_the_valid_source(
    tmp_path,
    broken_id,
):
    from qwenpaw.providers.provider_manager import ProviderManager

    async with PluginTestHost(tmp_path / "host"):
        manager = ProviderManager.get_instance()
        broken = manager.builtin_path / f"{broken_id}.json"
        valid = manager.builtin_path / (
            "copaw-local.json"
            if broken_id == "qwenpaw-local"
            else "qwenpaw-local.json"
        )
        broken.write_text("{broken", encoding="utf-8")
        settings = {
            "extra_models": [{"id": "A", "name": "A"}],
            "generate_kwargs": {"temperature": 0.7},
        }
        valid.write_text(json.dumps(settings), encoding="utf-8")

        manager._migrate_copaw_config()

        target = manager.plugin_path / "qwenpaw-local.json"
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert all(saved[key] == value for key, value in settings.items())
        assert not valid.exists()
        assert broken.read_text(encoding="utf-8") == "{broken"


@pytest.mark.parametrize("custom", [False, True])
async def test_legacy_data_directory_survives_removal_of_plugin_settings(
    tmp_path,
    custom,
):
    from qwenpaw import constant
    from qwenpaw.plugins.settings import drop_plugin_settings

    async with PluginTestHost(tmp_path / "host") as host:
        data = (
            tmp_path / "custom"
            if custom
            else constant.DEFAULT_LOCAL_PROVIDER_DIR
        )
        data.mkdir(parents=True, exist_ok=True)
        (data / "config.json").write_text("{}")
        persist_plugin_settings(
            PLUGIN_ID,
            config={"data_dir": str(data)} if custom else {},
        )
        assert await migrate_local_model_plugin(host._loader)
        drop_plugin_settings(PLUGIN_ID)
        locator = (
            constant.WORKING_DIR / "plugin-data/local-llamacpp/data-root.json"
        )
        assert json.loads(locator.read_text()) == {"data_dir": str(data)}
        assert (data / "config.json").read_text() == "{}"


@pytest.mark.parametrize("used", [False, True])
async def test_default_enablement_follows_existing_local_data(
    tmp_path,
    monkeypatch,
    used,
):
    from qwenpaw import constant
    from qwenpaw.config.utils import load_config

    data = tmp_path / "old-local"
    monkeypatch.setattr(constant, "DEFAULT_LOCAL_PROVIDER_DIR", data)
    monkeypatch.setattr(_providers, "configured_models", lambda manager: [])
    if used:
        data.mkdir()
        (data / "config.json").write_text("{}")
    async with PluginTestHost(tmp_path / "host") as host:
        assert await migrate_local_model_plugin(host._loader) is used
        assert (
            load_config().plugins.get(PLUGIN_ID, {}).get("enabled", False)
            is used
        )
        assert (
            host._loader.find_installed_plugin_dir(PLUGIN_ID) is not None
        ) is used
        assert host._loader.registry.get_provider("qwenpaw-local") is None


async def test_failed_migration_retries_without_losing_intent(
    tmp_path,
    monkeypatch,
):
    from unittest.mock import AsyncMock
    from qwenpaw.plugins import local_model_legacy
    from qwenpaw.config.utils import load_config

    monkeypatch.setattr(
        local_model_legacy,
        "_used_local_models",
        lambda _path: True,
    )
    async with PluginTestHost(tmp_path / "host") as host:
        with monkeypatch.context() as patch:
            patch.setattr(
                host._loader,
                "_seed_bundled_source",
                AsyncMock(side_effect=OSError("copy failed")),
            )
            with pytest.raises(OSError, match="copy failed"):
                await migrate_local_model_plugin(host._loader)
            assert not load_config().local_model_plugin_migrated
        assert await migrate_local_model_plugin(host._loader)
        assert load_config().local_model_plugin_migrated
        assert host._loader.find_installed_plugin_dir(PLUGIN_ID) is not None


async def test_channel_seed_still_publishes_without_dependency_install(
    tmp_path,
    monkeypatch,
):
    from unittest.mock import AsyncMock
    from qwenpaw.plugins.local_model_legacy import bundled_local_source

    source = bundled_local_source().parents[1] / "channel/feishu"
    async with PluginTestHost(tmp_path / "host") as host:
        prepare = AsyncMock(
            side_effect=AssertionError(
                "Seeding must not install dependencies",
            ),
        )
        monkeypatch.setattr(
            host._loader.lifecycle,
            "preflight_backend",
            prepare,
        )
        record = await host._loader.seed_bundled_channel(source)
        assert (record.source_path / "channel.json").is_file()
        assert "channel_validation_pending" in record.diagnostics
        prepare.assert_not_awaited()


def test_catalog_offers_local_source_without_importing_plugin(
    tmp_path,
    monkeypatch,
):
    import sys
    from qwenpaw.plugins import download_catalog as catalog
    from qwenpaw.plugins.local_model_legacy import bundled_local_source

    monkeypatch.setattr(
        catalog,
        "_build_remote_plugin_catalog",
        lambda: {"plugins": [], "error": "offline"},
    )
    monkeypatch.setattr(catalog, "_installed_plugin_ids", lambda: {})
    before = set(sys.modules)
    rows = catalog.build_plugin_catalog()["plugins"]
    local = next(row for row in rows if row["plugin_id"] == PLUGIN_ID)
    assert not local["installed"]
    assert local["install_url"] == str(bundled_local_source().resolve())
    assert not any(
        name.startswith(
            ("modelscope", "huggingface_hub", "plugin_local_llamacpp"),
        )
        for name in set(sys.modules) - before
    )


@pytest.mark.parametrize("docker", [False, True])
async def test_upgrade_resumes_until_dependency_preparation_is_attempted(
    tmp_path,
    monkeypatch,
    docker,
):
    from unittest.mock import AsyncMock
    from qwenpaw.plugins import local_model_legacy

    monkeypatch.setattr(
        local_model_legacy,
        "_used_local_models",
        lambda _path: True,
    )
    async with PluginTestHost(tmp_path / "host") as host:
        if docker:
            marker = tmp_path / "container-layer"
            monkeypatch.setenv(
                "QWENPAW_LOCAL_MODEL_UPGRADE_MARKER",
                str(marker),
            )
        else:
            monkeypatch.delenv(
                "QWENPAW_LOCAL_MODEL_UPGRADE_MARKER",
                raising=False,
            )
        loader = host._loader
        prepare = AsyncMock(
            side_effect=RuntimeError("Package index unavailable"),
        )
        monkeypatch.setattr(loader.lifecycle, "preflight_backend", prepare)

        # The first app exited before its deferred dependency work started.
        from qwenpaw.providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
        assert await local_model_legacy.prepare_startup_local_model(
            loader,
            manager,
        ) == (PLUGIN_ID,)
        assert await local_model_legacy.prepare_startup_local_model(
            loader,
            manager,
        ) == (PLUGIN_ID,)
        prepare.assert_not_awaited()
        with pytest.raises(RuntimeError, match="Package index unavailable"):
            await local_model_legacy._prepare_dependencies(loader)
        assert loader.find_installed_plugin_dir(PLUGIN_ID) is not None
        assert not await migrate_local_model_plugin(loader)
        prepare.assert_awaited_once()

        if docker:
            marker.unlink()
            prepare.side_effect = None
            assert await migrate_local_model_plugin(loader)
            await local_model_legacy._prepare_dependencies(loader)
            assert prepare.await_count == 2


@pytest.mark.parametrize("state", ["new", "disabled", "uninstalled"])
async def test_upgrade_skips_users_without_enabled_local_plugin(
    tmp_path,
    monkeypatch,
    state,
):
    from unittest.mock import AsyncMock
    from qwenpaw.config.utils import mutate_config
    from qwenpaw.plugins import local_model_legacy
    from qwenpaw.plugins.loader import PluginLoader

    async with PluginTestHost(tmp_path / "host"):
        monkeypatch.setattr(
            local_model_legacy,
            "_used_local_models",
            lambda _path: state != "new",
        )
        if state == "disabled":
            persist_plugin_settings(PLUGIN_ID, enabled=False)
        elif state == "uninstalled":
            mutate_config(
                lambda root: setattr(
                    root,
                    "local_model_plugin_migrated",
                    True,
                ),
            )
        create = AsyncMock(
            side_effect=AssertionError("Unexpected preparation"),
        )
        monkeypatch.setattr(PluginLoader, "create", create)
        assert await local_model_legacy.prepare_local_model_upgrade() == {}
        create.assert_not_awaited()


async def test_normal_install_prepares_dependencies_before_registering(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.dependency_gate import combined_requirements
    from qwenpaw.plugins.local_model_legacy import bundled_local_source

    async with PluginTestHost(tmp_path / "host") as host:

        async def preflight(binding, **kwargs):
            assert kwargs["allow_install"]
            with combined_requirements(
                binding.description.source_path,
            ) as path:
                assert path.read_text().splitlines() == [
                    "modelscope-hub>=0.7.1",
                    "huggingface_hub>=0.20.0",
                ]
            raise RuntimeError("dependency installation failed")

        monkeypatch.setattr(
            host._loader.lifecycle,
            "preflight_backend",
            preflight,
        )
        with pytest.raises(SDKError, match="dependency installation failed"):
            await host.install(bundled_local_source())
        assert host._loader.registry.get_provider("qwenpaw-local") is None
        assert host._loader.find_installed_plugin_dir(PLUGIN_ID) is None


async def test_installed_plugin_reports_missing_dependencies_on_boot(
    tmp_path,
    monkeypatch,
):
    from unittest.mock import AsyncMock
    from qwenpaw.plugins import dependency_gate, local_model_legacy

    names = {"modelscope-hub", "huggingface-hub"}
    original = dependency_gate.is_requirement_satisfied
    version = dependency_gate._dist_version

    def version_of(name):
        if name.replace("_", "-") in names:
            raise dependency_gate.PackageNotFoundError(name)
        return version(name)

    monkeypatch.setattr(dependency_gate, "_dist_version", version_of)

    async with PluginTestHost(tmp_path / "host") as host:
        monkeypatch.setattr(
            local_model_legacy,
            "_used_local_models",
            lambda _path: True,
        )
        assert await migrate_local_model_plugin(host._loader)
        source = host._loader.find_installed_plugin_dir(PLUGIN_ID)
        _, manifest = host._loader.read_source_manifest(source)
        monkeypatch.setattr(
            dependency_gate,
            "is_requirement_satisfied",
            lambda req: False
            if req.name.replace("_", "-") in names
            else original(req),
        )

        installer = AsyncMock(
            side_effect=AssertionError("Boot must not install"),
        )
        monkeypatch.setattr(
            host._loader,
            "_prepare_python_dependencies",
            installer,
        )
        record = await host._loader.load_plugin(
            manifest,
            source,
            allow_install=False,
        )
        assert record.status == "failed"
        diagnostic = " ".join(record.diagnostics)
        assert "missing dependencies" in diagnostic
        for name in names:
            assert name.replace("-", "_") in diagnostic.replace("-", "_")
        assert host._loader.registry.get_provider("qwenpaw-local") is None
        installer.assert_not_awaited()
