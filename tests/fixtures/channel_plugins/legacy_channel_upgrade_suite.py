"""Real all-official bundle publication from persisted legacy user intent.

These contracts prove offline source migration, not platform login or delivery.
All writes use temporary roots; no SDK stubs or credentials are injected.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS


@pytest.fixture
def upgrade(tmp_path, monkeypatch):
    from qwenpaw.config import utils
    from qwenpaw.plugins import official_channels
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    host = tmp_path / "host"
    host.mkdir()
    config_path = host / "config.json"
    config_path.write_text("{}")
    monkeypatch.setattr(utils, "WORKING_DIR", host)
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", host)
    monkeypatch.setattr("qwenpaw.constant.PLUGINS_DIR", host / "plugins")
    monkeypatch.setattr(utils, "get_config_path", lambda: config_path)
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    runtime = resolve_default_channel_runtime()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline migration attempted dependency/SDK work")

    def loader(runtime_settings=None):
        # A fresh registry models the next process, using exactly the same files.
        PluginRegistry._instance = None
        value = PluginLoader(
            [host / "plugins"], channel_runtime=runtime_settings or runtime
        )
        value.registry.projector = WorkspaceProjector(
            live_workspaces=lambda: []
        )
        monkeypatch.setattr(value, "_prepare_channel_candidate", forbidden)
        monkeypatch.setattr(value, "_ensure_dependencies_installed", forbidden)
        monkeypatch.setattr(value, "_acquire_dependency_wheels", forbidden)
        return value

    def save(data):
        config_path.write_text(json.dumps(data))
        utils._config_cache = None
        utils._config_mtime = None

    return NS(
        root=tmp_path,
        host=host,
        path=config_path,
        save=save,
        load=utils.load_config,
        official=official_channels,
        loader=loader,
        runtime=runtime,
    )


def installed_bytes(root):
    return {
        path.relative_to(root)
        .as_posix(): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_explicit_upgrade_cli_prepares_enabled_channel_without_repair(upgrade):
    from click.testing import CliRunner
    from qwenpaw.cli.main import cli

    values = {
        "enabled": True,
        "host": "localhost",
        "subscribe_topic": "qwenpaw/in/+",
        "publish_topic": "qwenpaw/out/{client_id}",
    }
    upgrade.save({"channels": {"mqtt": values}})
    result = CliRunner().invoke(cli, ["plugins", "prepare-upgrade"])
    assert result.exit_code == 0, result.output
    assert upgrade.load().channels.mqtt.enabled is True
    assert upgrade.load().channels.mqtt.host == "localhost"
    assert (upgrade.host / "plugins/mqtt/channel.json").is_file()
    assert installed_bytes(upgrade.runtime.dependency_install_target) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "missing",
        "off",
        "plugin-only",
        "disabled",
        "uninstalled",
        "whitelist",
        "blacklist",
    ],
)
async def test_upgrade_preparation_respects_only_enabled_user_intent(
    upgrade, monkeypatch, reason
):
    raw = {"channels": {"mqtt": {"enabled": True}}}
    if reason == "missing":
        upgrade.path.unlink()
    elif reason in {"off", "plugin-only"}:
        raw["channels"]["mqtt"]["enabled"] = False
        if reason == "plugin-only":
            raw["plugins"] = {"mqtt": {"enabled": True}}
    elif reason == "disabled":
        raw["plugins"] = {"mqtt": {"enabled": False}}
    elif reason == "uninstalled":
        raw["channel_plugin_state"] = {"uninstalled": ["mqtt"]}
    elif reason == "whitelist":
        monkeypatch.setenv("QWENPAW_ENABLED_CHANNELS", "slack")
    elif reason == "blacklist":
        monkeypatch.setenv("QWENPAW_DISABLED_CHANNELS", "mqtt")
    if reason != "missing":
        upgrade.save(raw)
    before = upgrade.path.read_bytes() if upgrade.path.exists() else None
    assert await upgrade.official.prepare_channel_upgrade() == {}
    assert not (upgrade.host / "plugins").exists()
    assert installed_bytes(upgrade.runtime.dependency_install_target) == {}
    assert (
        upgrade.path.read_bytes() if upgrade.path.exists() else None
    ) == before


@pytest.mark.asyncio
async def test_upgrade_preparation_unions_global_and_workspace_selections(
    upgrade,
):
    workspace = upgrade.root / "saved-workspace"
    workspace.mkdir()
    agent = workspace / "agent.json"
    agent.write_text(
        json.dumps(
            {
                "channels": {
                    "mqtt": {"enabled": True},
                    "slack": {"enabled": True},
                }
            }
        )
    )
    original = agent.read_bytes()
    upgrade.save(
        {
            "channels": {"mqtt": {"enabled": True}},
            "plugins": {"dingtalk": {"enabled": True}},
            "agents": {
                "profiles": {
                    "saved": {
                        "name": "saved",
                        "workspace_dir": str(workspace),
                    }
                }
            },
        }
    )
    assert await upgrade.official.prepare_channel_upgrade() == {}
    assert {path.name for path in (upgrade.host / "plugins").iterdir()} == {
        "mqtt",
        "slack",
    }
    assert agent.read_bytes() == original
    assert installed_bytes(upgrade.runtime.dependency_install_target) == {}


@pytest.mark.asyncio
async def test_upgrade_preparation_preserves_custom_installed_source(upgrade):
    import shutil

    upgrade.save({"channels": {"mqtt": {"enabled": True}}})
    installed = upgrade.host / "plugins/mqtt"
    with upgrade.official.bundled_channel_source("mqtt") as source:
        shutil.copytree(source, installed)
    (installed / "README.md").write_text("user maintained source\n")
    before = installed_bytes(installed)
    for _ in range(2):
        assert await upgrade.official.prepare_channel_upgrade() == {}
        assert installed_bytes(installed) == before
    assert installed_bytes(upgrade.runtime.dependency_install_target) == {}


def test_upgrade_cli_reports_real_probe_failure_without_secret_text(upgrade):
    import shutil
    from click.testing import CliRunner
    from qwenpaw.cli.main import cli

    upgrade.save(
        {
            "channels": {
                "mqtt": {
                    "enabled": True,
                    "password": "never-echo-this-secret",
                }
            }
        }
    )
    installed = upgrade.host / "plugins/mqtt"
    with upgrade.official.bundled_channel_source("mqtt") as source:
        shutil.copytree(source, installed)
    (installed / "qwenpaw_channel_mqtt/driver.py").unlink()
    result = CliRunner().invoke(cli, ["plugins", "prepare-upgrade"])
    assert result.exit_code != 0
    assert "ENTRYPOINT" in result.output
    assert "never-echo-this-secret" not in result.output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row", OFFICIAL_CHANNELS, ids=lambda row: row["channel_key"]
)
@pytest.mark.parametrize("location", ["global", "workspace"])
async def test_enabled_legacy_source_migrates_and_reboots_once(
    upgrade, row, location
):
    key, owner = row["channel_key"], row["plugin_id"]
    values = {
        "enabled": True,
        "bot_prefix": "upgrade-sentinel",
        "show_thinking": False,
    }
    raw = {"channels": {key: values}}
    workspace_file = None
    if location == "workspace":
        workspace = upgrade.root / "saved-workspace"
        workspace.mkdir()
        workspace_file = workspace / "agent.json"
        workspace_file.write_text(json.dumps(raw))
        original = workspace_file.read_bytes()
        raw = {
            "agents": {
                "profiles": {
                    "old": {
                        "name": "old",
                        "workspace_dir": str(workspace),
                    }
                }
            }
        }
    upgrade.save(raw)
    loader = upgrade.loader()
    await loader.load_all_plugins(
        configs={}, types=["channel"], activate=False
    )
    assert await upgrade.official.provision_bundled_channels(loader) == {}
    target = loader.find_installed_plugin_dir(owner)
    assert target is not None
    with upgrade.official.bundled_channel_source(owner) as bundled:
        assert installed_bytes(target) == installed_bytes(bundled)
    registration = loader.registry.get_channel_catalog_entry(key)
    assert registration.plugin_id == owner
    assert registration.global_enabled is True
    record = loader.get_loaded_plugin(owner)
    assert record.status == "registered"
    assert record.enabled is True
    assert "channel_validation_pending" in record.diagnostics
    snapshot = installed_bytes(target)
    for restart in (False, True):
        if restart:
            loader = upgrade.loader()
            await loader.load_all_plugins(
                configs=upgrade.load().plugins,
                types=["channel"],
                activate=False,
            )
        assert await upgrade.official.provision_bundled_channels(loader) == {}
        assert set(loader.registry.get_channel_catalog()) == {key}
        assert installed_bytes(target) == snapshot
        state = upgrade.load().channel_plugin_state
        assert state.legacy_pending == []
        assert set(state.legacy_captured) == {
            row["channel_key"] for row in OFFICIAL_CHANNELS
        }
        assert len(state.legacy_captured) == len(OFFICIAL_CHANNELS) == 18
    if workspace_file is not None:
        assert workspace_file.read_bytes() == original
    else:
        saved = json.loads(upgrade.path.read_text())["channels"][key]
        assert all(saved[name] == value for name, value in values.items())
    assert not list(upgrade.runtime.dependency_install_target.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row", OFFICIAL_CHANNELS, ids=lambda row: row["channel_key"]
)
async def test_global_plugin_disable_survives_legacy_source_seed(upgrade, row):
    key, owner = row["channel_key"], row["plugin_id"]
    upgrade.save(
        {
            "channels": {key: {"enabled": True}},
            "plugins": {owner: {"enabled": False}},
        }
    )
    loader = upgrade.loader()
    assert await upgrade.official.provision_bundled_channels(loader) == {}
    assert loader.find_installed_plugin_dir(owner) is not None
    assert (
        loader.registry.get_channel_catalog_entry(key).global_enabled is False
    )
    assert loader.get_loaded_plugin(owner).enabled is False
    assert loader.get_loaded_plugin(owner).status == "inactive"
    assert upgrade.load().plugins[owner]["enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["disabled", "uninstalled"])
async def test_disabled_or_uninstalled_sources_are_not_resurrected(
    upgrade, reason
):
    raw = {
        "channels": {
            row["channel_key"]: {"enabled": reason != "disabled"}
            for row in OFFICIAL_CHANNELS
        }
    }
    if reason == "uninstalled":
        raw["channel_plugin_state"] = {
            "version": 1,
            "preset": "channels-full",
            "uninstalled": [row["plugin_id"] for row in OFFICIAL_CHANNELS],
            "legacy_pending": [row["plugin_id"] for row in OFFICIAL_CHANNELS],
        }
    upgrade.save(raw)
    for _ in range(2):
        loader = upgrade.loader()
        assert await upgrade.official.provision_bundled_channels(loader) == {}
        assert loader.registry.get_channel_catalog() == {}
        assert all(
            loader.find_installed_plugin_dir(row["plugin_id"]) is None
            for row in OFFICIAL_CHANNELS
        )
        assert upgrade.load().channel_plugin_state.legacy_pending == []


@pytest.mark.asyncio
async def test_version_one_only_captures_newly_retired_officials(upgrade):
    upgrade.save(
        {
            "channels": {
                row["channel_key"]: {"enabled": True}
                for row in OFFICIAL_CHANNELS
            },
            "channel_plugin_state": {"version": 1, "preset": "light"},
        }
    )
    loader = upgrade.loader()
    assert await upgrade.official.provision_bundled_channels(loader) == {}
    expected = {row["channel_key"] for row in OFFICIAL_CHANNELS} - {
        "feishu",
        "dingtalk",
    }
    assert set(loader.registry.get_channel_catalog()) == expected
    assert len(expected) == 16


@pytest.mark.asyncio
async def test_same_owner_across_global_and_two_workspaces_is_seeded_once(
    upgrade,
):
    channels = {
        row["channel_key"]: {"enabled": True} for row in OFFICIAL_CHANNELS
    }
    profiles, originals = {}, {}
    for agent_id in ("first", "second"):
        workspace = upgrade.root / agent_id
        workspace.mkdir()
        saved = workspace / "agent.json"
        saved.write_text(json.dumps({"channels": channels}))
        originals[saved] = saved.read_bytes()
        profiles[agent_id] = {
            "name": agent_id,
            "workspace_dir": str(workspace),
        }
    upgrade.save({"channels": channels, "agents": {"profiles": profiles}})
    loader = upgrade.loader()
    for _ in range(2):
        assert await upgrade.official.provision_bundled_channels(loader) == {}
        assert len(loader.get_all_loaded_plugins()) == 18
        assert len(loader.registry.get_channel_catalog()) == 18
        assert {
            path.name for path in (upgrade.host / "plugins").iterdir()
        } == {row["plugin_id"] for row in OFFICIAL_CHANNELS}
        assert all(
            saved.read_bytes() == original
            for saved, original in originals.items()
        )
        assert upgrade.load().channel_plugin_state.legacy_pending == []


@pytest.mark.asyncio
async def test_environment_only_enable_is_outside_persisted_capture(
    upgrade, monkeypatch
):
    from qwenpaw.config.channel_env import read_channel_env

    monkeypatch.setenv("TELEGRAM_CHANNEL_ENABLED", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-not-a-credential")
    assert read_channel_env("telegram", {"TELEGRAM_CHANNEL_ENABLED": "1"})[
        "enabled"
    ]
    loader = upgrade.loader()
    assert await upgrade.official.provision_bundled_channels(loader) == {}
    assert loader.find_installed_plugin_dir("telegram") is None
    assert "telegram" in upgrade.load().channel_plugin_state.legacy_captured


@pytest.mark.asyncio
async def test_missing_sdk_stays_pending_without_dependency_install(
    upgrade, monkeypatch
):
    from dataclasses import replace
    import os
    import packaging
    import shutil
    import venv

    from qwenpaw.plugins.dependency_gate import SharedDependencyError
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    # A genuine empty interpreter makes absence deterministic even on developer
    # machines with every channel SDK installed. Copy only bootstrap packaging.
    empty_python = upgrade.root / "empty-python"
    venv.EnvBuilder(with_pip=False).create(empty_python)
    support_site = upgrade.root / "bootstrap-site"
    shutil.copytree(
        Path(packaging.__file__).parent, support_site / "packaging"
    )
    executable = empty_python / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    runtime = replace(
        upgrade.runtime,
        python_executable=str(executable),
        dependency_paths=(
            support_site,
            upgrade.runtime.dependency_install_target,
        ),
    )
    upgrade.save({"channels": {"slack": {"enabled": True}}})
    loader = upgrade.loader(runtime)
    assert await upgrade.official.provision_bundled_channels(loader) == {}
    # Restore the real preparation seam; dependency download remains forbidden.
    monkeypatch.setattr(
        loader,
        "_prepare_channel_candidate",
        type(loader)._prepare_channel_candidate.__get__(loader),
    )

    class EmptyManager:
        async def get_channel(self, _key):
            return None

    workspace = NS(_config=upgrade.load(), channel_manager=EmptyManager())
    loader.registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace]
    )
    from qwenpaw.plugins.api import channel_passes_gates

    assert channel_passes_gates(workspace, "slack")
    backend = loader.get_loaded_plugin("slack").backend_binding.backend
    assert backend.services.workspaces() == [workspace]
    assert backend.services.record("slack").enabled
    assert (
        "channel_validation_passed"
        not in backend.services.record("slack").diagnostics
    )
    before = installed_bytes(upgrade.runtime.dependency_install_target)
    with pytest.raises(SharedDependencyError) as error:
        await loader.lifecycle.activate("slack")
    assert any(
        requirement.startswith("slack-sdk")
        for requirement in error.value.decision.missing
    )
    record = loader.get_loaded_plugin("slack")
    assert "channel_validation_pending" in record.diagnostics
    assert "channel_validation_passed" not in record.diagnostics
    assert record.status != "active"
    assert (
        installed_bytes(upgrade.runtime.dependency_install_target)
        == before
        == {}
    )
    assert loader.find_installed_plugin_dir("slack") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("canonical_disabled", [False, True])
@pytest.mark.parametrize("operation", ["boot", "prepare"])
async def test_docker_upgrade_captures_weixin_alias_before_workspace_load(
    upgrade, monkeypatch, canonical_disabled, operation
):
    """A prior light policy must retain newly retired legacy WeChat intent."""
    monkeypatch.setenv("QWENPAW_CHANNEL_PRESET", "channels-full")
    workspace = upgrade.root / "saved-workspace"
    workspace.mkdir()
    channels = {"weixin": {"enabled": True, "bot_prefix": "historic-alias"}}
    if canonical_disabled:
        channels["wechat"] = {"enabled": False}
    agent = workspace / "agent.json"
    agent.write_text(
        json.dumps({
            "id": "saved", "name": "Saved Agent",
            "workspace_dir": str(workspace), "channels": channels,
        })
    )
    original = agent.read_bytes()
    upgrade.save(
        {
            "agents": {"profiles": {
                "saved": {"id": "saved", "workspace_dir": str(workspace)},
            }},
            "channel_plugin_state": {"version": 1, "preset": "light"},
        }
    )
    loader = upgrade.loader()
    if operation == "boot":
        assert await upgrade.official.provision_bundled_channels(loader) == {}
    else:
        assert await upgrade.official.prepare_channel_upgrade() == {}
    target = loader.find_installed_plugin_dir("wechat")
    assert (target is not None) is (not canonical_disabled)
    assert agent.read_bytes() == original
    if operation == "boot":
        assert "wechat" in upgrade.load().channel_plugin_state.legacy_captured
    assert upgrade.load().channel_plugin_state.preset == "light"
