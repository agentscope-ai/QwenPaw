# -*- coding: utf-8 -*-
"""Upgrade and lifecycle coverage through the real plugin loading path."""

# pylint: disable=redefined-outer-name,protected-access,unused-argument

import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.channels.registry import get_available_keys, get_channel_class
from qwenpaw.app.routers.config import router
from qwenpaw.config.config import AgentProfileConfig, ChannelConfig
from qwenpaw.plugins.bundled_channels import ensure_bundled_channel_plugins
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    return PluginRegistry()


def test_migration_preserves_user_files_and_does_not_resurrect(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in [
        "agent.json",
        "dingtalk_session_webhooks.json",
        "dingtalk-active-cards.json",
    ]:
        (workspace / name).write_text('{"existing": "untouched"}')
    before = {p.name: p.read_bytes() for p in workspace.iterdir()}
    plugins = tmp_path / "plugins"
    unrelated = plugins / "malformed-plugin"
    unrelated.mkdir(parents=True)
    (unrelated / "plugin.json").write_text("[]")
    ensure_bundled_channel_plugins(plugins)
    installed = plugins / "dingtalk"
    assert (installed / "channel.py").is_file()
    (installed / "user-note.txt").write_text("keep")
    ensure_bundled_channel_plugins(plugins)
    assert (installed / "user-note.txt").read_text() == "keep"
    assert before == {p.name: p.read_bytes() for p in workspace.iterdir()}
    shutil.rmtree(installed)
    ensure_bundled_channel_plugins(plugins)
    assert not installed.exists()


def test_migration_preserves_existing_disabled_plugin(tmp_path):
    installed = tmp_path / "dingtalk.disabled"
    installed.mkdir()
    (installed / "plugin.json").write_text(
        '{"id": "dingtalk", "version": "custom"}',
    )
    ensure_bundled_channel_plugins(tmp_path)
    assert not (tmp_path / "dingtalk").exists()
    assert (
        json.loads((installed / "plugin.json").read_text())["version"]
        == "custom"
    )


def test_registration_and_discovery_do_not_import_dingtalk_sdk(tmp_path):
    # Separate interpreter: other DingTalk unit tests may already import SDKs.
    script = """
import asyncio, sys
from pathlib import Path
from qwenpaw.plugins.bundled_channels import ensure_bundled_channel_plugins
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.app.channels.registry import get_available_keys
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.config.config import ChannelConfig
from types import SimpleNamespace
p = Path(sys.argv[1])
ensure_bundled_channel_plugins(p)
loader = PluginLoader([p])
asyncio.run(loader.load_all_plugins(types=["channel"]))
assert loader.registry.get_channel_registration("dingtalk") is not None
assert "dingtalk" in get_available_keys()
ChannelManager.from_config(
    lambda *a: None, SimpleNamespace(channels=ChannelConfig())
)
for prefix in ("dingtalk_stream", "alibabacloud_dingtalk"):
    assert not any(
        x == prefix or x.startswith(prefix + ".") for x in sys.modules
    )
"""
    env = dict(os.environ, QWENPAW_WORKING_DIR=str(tmp_path / "state"))
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "plugins")],
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_old_enabled_config_loads_real_plugin_and_keeps_workspace_state(
    tmp_path,
    registry,
):
    plugins = tmp_path / "plugins"
    ensure_bundled_channel_plugins(plugins)
    loader = PluginLoader([plugins])
    await loader.load_all_plugins(types=["channel"])
    old = {
        "id": "old",
        "name": "Old workspace",
        "channels": {
            "dingtalk": {
                "enabled": True,
                "client_id": "existing-id",
                "client_secret": "existing-secret",
                "message_type": "card",
                "card_template_id": "existing-template",
                "share_session_in_group": True,
            },
        },
    }
    config = AgentProfileConfig.model_validate(old)
    before = config.model_dump()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = workspace / "dingtalk_session_webhooks.json"
    store.write_text('{"legacy": "https://example.invalid/webhook"}')
    manager = ChannelManager.from_config(
        AsyncMock(),
        config,
        workspace_dir=workspace,
    )
    channel = await manager.get_channel("dingtalk")
    assert channel is not None
    assert channel.__class__.__module__.startswith("plugin_dingtalk.")
    assert channel.client_id == "existing-id"
    assert channel.client_secret == "existing-secret"
    assert channel.card_template_id == "existing-template"
    assert channel._session_webhook_store_path() == store
    channel._load_session_webhook_store_from_disk()
    assert "legacy" in channel._session_webhook_store
    assert config.model_dump() == before
    # The other workspace doesn't acquire a DingTalk connection or credentials.
    other = ChannelManager.from_config(
        AsyncMock(),
        SimpleNamespace(channels=ChannelConfig()),
        workspace_dir=tmp_path / "other",
    )
    assert await other.get_channel("dingtalk") is None
    # Even retired workspaces cannot have their code overwritten in this pilot.
    with pytest.raises(ValueError, match="ALL workspaces"):
        await loader.unload_plugin("dingtalk", delete_files=True)
    assert (plugins / "dingtalk" / "channel.py").exists()
    assert registry.get_channel_registration("dingtalk") is not None


@pytest.mark.asyncio
async def test_disabled_plugin_can_be_removed_and_reinstalled(
    tmp_path,
    registry,
):
    plugins = tmp_path / "plugins"
    ensure_bundled_channel_plugins(plugins)
    loader = PluginLoader([plugins])
    await loader.load_all_plugins(types=["channel"])
    await loader.unload_plugin("dingtalk", delete_files=True)
    assert get_channel_class("dingtalk") is None
    assert "dingtalk" in get_available_keys()  # Keep old settings accessible.
    ensure_bundled_channel_plugins(plugins)
    assert not (plugins / "dingtalk").exists()
    from qwenpaw.plugins.bundled_channels import bundled_channel_root

    # Explicit reinstall, with the same class/instance identity contract.
    loader._install_requirements_locked = lambda *args: None
    await loader.load_plugin_from_path(
        bundled_channel_root() / "dingtalk",
        install_dir=plugins,
    )
    assert get_channel_class("dingtalk").channel == "dingtalk"


@pytest.mark.asyncio
async def test_missing_dependencies_do_not_trigger_startup_install(
    tmp_path,
    registry,
    monkeypatch,
):
    plugins = tmp_path / "plugins"
    ensure_bundled_channel_plugins(plugins)
    loader = PluginLoader([plugins])
    monkeypatch.setattr(
        loader,
        "_find_unsatisfied_dependencies",
        lambda _: ["missing-sdk"],
    )
    install = AsyncMock(side_effect=AssertionError("startup must be offline"))
    monkeypatch.setattr(loader, "_ensure_dependencies_installed", install)
    await loader.load_all_plugins(types=["channel"])
    install.assert_not_called()
    assert registry.get_channel_registration("dingtalk") is None
    assert "dingtalk" in get_available_keys()


def test_missing_plugin_config_read_disable_and_enable_error(
    tmp_path,
    registry,
    monkeypatch,
):
    config = AgentProfileConfig.model_validate(
        {
            "id": "old",
            "name": "Old",
            "channels": {
                "dingtalk": {
                    "enabled": True,
                    "client_id": "old-id",
                    "client_secret": "old-secret",
                    "card_template_id": "card",
                },
            },
        },
    )
    agent = SimpleNamespace(config=config, agent_id="old")
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_agent_for_request",
        AsyncMock(return_value=agent),
    )
    saves = []
    monkeypatch.setattr(
        "qwenpaw.config.config.save_agent_config",
        lambda *args: saves.append(args),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.config.schedule_agent_reload",
        lambda *args: None,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    response = client.get("/api/config/channels")
    assert response.status_code == 200
    data = response.json()["dingtalk"]
    assert data["pluginInstalled"] is False
    assert data["enabled"] is True
    assert data["isBuiltin"] is False
    response = client.get("/api/config/channels/dingtalk")
    assert response.json()["client_id"] == "old-id"
    payload = config.channels.dingtalk.model_dump()
    assert (
        client.put("/api/config/channels/dingtalk", json=payload).status_code
        == 409
    )
    assert not saves
    payload["enabled"] = False
    response = client.put("/api/config/channels/dingtalk", json=payload)
    assert response.status_code == 200
    assert response.json()["client_secret"] == "old-secret"
    assert response.json()["card_template_id"] == "card"
    assert len(saves) == 1
