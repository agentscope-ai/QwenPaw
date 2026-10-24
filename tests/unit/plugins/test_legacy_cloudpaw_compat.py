# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Installed legacy CloudPaw cannot intercept native lifecycle operations."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import pawapps, plugins
from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.provision import provisions_dir

# Exact old wrapper from origin/main; do not execute its external startup.
_LEGACY_PATCH = '''
def _patch_plugin_loader_unload() -> None:
    """Monkeypatch PluginLoader.unload_plugin to clean up CloudPaw agents
    when the plugin is uninstalled.
    """
    try:
        from qwenpaw.plugins.loader import PluginLoader
    except ImportError:
        logger.warning(
            "Cannot import PluginLoader; uninstall patch skipped",
        )
        return

    if getattr(PluginLoader.unload_plugin, "_cloudpaw_patched", False):
        logger.debug("unload_plugin already patched; skip")
        return

    _original_unload_plugin = PluginLoader.unload_plugin

    async def _patched_unload_plugin(
        self,
        plugin_id: str,
        delete_files: bool = False,
    ) -> None:
        if plugin_id == "cloudpaw":
            logger.info(
                "[CloudPaw] Uninstall detected, cleaning up agents...",
            )
            try:
                from .agents_setup import uninstall_agents

                uninstall_agents()
                logger.info("[CloudPaw] Agent cleanup completed")
            except Exception as exc:
                logger.warning(
                    "[CloudPaw] Agent cleanup failed: %s",
                    exc,
                )

        return await _original_unload_plugin(self, plugin_id, delete_files)

    _patched_unload_plugin._cloudpaw_patched = True
    _patched_unload_plugin._original = _original_unload_plugin
    PluginLoader.unload_plugin = _patched_unload_plugin
    logger.info("[CloudPaw] Patched PluginLoader.unload_plugin")
'''


@pytest.fixture()
def legacy_cloudpaw(tmp_path, monkeypatch, fresh_registry):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", work)
    monkeypatch.setattr("qwenpaw.config.utils.WORKING_DIR", work)
    monkeypatch.setattr(
        PluginLoader,
        "unload_plugin",
        PluginLoader.unload_plugin,
    )
    root = tmp_path / "plugins" / "cloudpaw"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "cloudpaw",
                "version": "1.0.0",
                "name": "CloudPaw",
                "entry": {"backend": "plugin.py"},
            },
        ),
        encoding="utf-8",
    )
    (root / "plugin.py").write_text(
        "import logging\nlogger = logging.getLogger(__name__)\n"
        + _LEGACY_PATCH
        + "\nclass Plugin:\n"
        "    def register(self, api):\n"
        "        api.register_startup_hook(\n"
        "            'patch', _patch_plugin_loader_unload)\n"
        "plugin = Plugin()\n",
        encoding="utf-8",
    )
    # Calling the old blanket cleanup is a test failure.
    (root / "agents_setup.py").write_text(
        "def uninstall_agents():\n"
        "    raise AssertionError('unsafe legacy blanket cleanup invoked')\n",
        encoding="utf-8",
    )
    loader = PluginLoader([root.parent])
    loader.registry = fresh_registry
    return loader, root, work


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["plugins", "pawapps"])
async def test_other_uninstall_bypasses_installed_cloudpaw_wrapper(
    legacy_cloudpaw,
    endpoint,
):
    loader, root, work = legacy_cloudpaw
    await loader.load_plugin(
        PluginManifest.model_validate_json((root / "plugin.json").read_text()),
        root,
    )
    other = root.parent / "other"
    other.mkdir()
    (other / "plugin.json").write_text(
        json.dumps(
            {
                "id": "other",
                "version": "1.0.0",
                "name": "Other",
                "entry": {"backend": "main.py"},
            },
        ),
        encoding="utf-8",
    )
    (other / "main.py").write_text(
        "class Plugin:\n    def register(self, api):\n        pass\n"
        "plugin = Plugin()\n",
        encoding="utf-8",
    )
    await loader.load_plugin(
        PluginManifest.model_validate_json(
            (other / "plugin.json").read_text(),
        ),
        other,
    )
    user_data = work / "cloud-user-data"
    user_data.mkdir()
    (user_data / "keep.txt").write_text("keep", encoding="utf-8")
    app = FastAPI()
    app.state.plugin_loader = loader
    app.include_router(plugins.router, prefix="/api")
    app.include_router(pawapps.router, prefix="/api")
    with TestClient(app) as client:
        response = client.delete(f"/api/{endpoint}/other")
    assert response.status_code == 200, response.text
    assert not other.exists()
    assert loader.get_loaded_plugin("other") is None
    assert loader.get_loaded_plugin("cloudpaw").status == "active"
    assert (user_data / "keep.txt").read_text(encoding="utf-8") == "keep"
    await loader.lifecycle.unload("cloudpaw", UnloadMode.SHUTDOWN)


def _manager(agent_ids):
    manager = MultiAgentManager()
    manager.agents.update(dict.fromkeys(agent_ids, object()))
    return manager


def _seed_cloud_agents(work):
    from qwenpaw.config.config import AgentProfileRef, AgentsConfig, Config
    from qwenpaw.config.utils import save_config

    profiles = {}
    for agent_id, name in (
        ("cloud-orchestrator", "CloudPaw-Master"),
        ("cloud-executor", "CloudPaw-Executor"),
    ):
        workspace = work / "workspaces" / agent_id
        workspace.mkdir(parents=True)
        (workspace / "agent.json").write_text(
            json.dumps(
                {
                    "id": agent_id,
                    "name": name,
                },
            ),
            encoding="utf-8",
        )
        (workspace / "history.txt").write_text(
            "user history",
            encoding="utf-8",
        )
        profiles[agent_id] = AgentProfileRef(
            id=agent_id,
            workspace_dir=str(workspace),
        )
    save_config(
        Config(
            agents=AgentsConfig(
                profiles=profiles,
                active_agent="cloud-orchestrator",
                agent_order=list(profiles),
            ),
        ),
    )
    return profiles


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded", [False, True])
async def test_legacy_uninstall_stops_all_agents_preserves_history(
    legacy_cloudpaw,
    loaded,
):
    from qwenpaw.config.utils import load_config

    loader, root, work = legacy_cloudpaw
    profiles = _seed_cloud_agents(work)
    factory = root / "agents" / "orchestration" / "en" / "AGENTS.md"
    factory.parent.mkdir(parents=True)
    factory.write_text("factory persona", encoding="utf-8")
    for agent_id in profiles:
        text = (
            "factory persona"
            if agent_id == "cloud-orchestrator"
            else "user persona"
        )
        (work / "workspaces" / agent_id / "AGENTS.md").write_text(
            text,
            encoding="utf-8",
        )
    events = []
    manager = _manager(profiles)

    async def stop(agent_id):
        assert root.exists()
        assert agent_id in load_config().agents.profiles
        events.append(agent_id)
        manager.agents.pop(agent_id)
        return True

    manager.stop_agent = AsyncMock(side_effect=stop)
    loader.registry.set_workspace_manager(manager)
    if loaded:
        await loader.load_plugin(
            PluginManifest.model_validate_json(
                (root / "plugin.json").read_text(),
            ),
            root,
        )
    report = await loader.lifecycle.unload(
        "cloudpaw",
        UnloadMode.UNINSTALL,
        delete_files=True,
    )
    assert report.clean and report.quiescent, report.errors
    assert set(events) == set(profiles)
    assert not manager.agents
    assert not root.exists()
    assert not (
        work / "workspaces" / "cloud-orchestrator" / "AGENTS.md"
    ).exists()
    assert (
        work / "workspaces" / "cloud-executor" / "AGENTS.md"
    ).read_text() == "user persona"
    assert not set(profiles).intersection(load_config().agents.profiles)
    assert load_config().agents.active_agent == "default"
    assert not (provisions_dir() / "compat" / "cloudpaw.json").exists()
    for agent_id in profiles:
        assert (
            work / "workspaces" / agent_id / "history.txt"
        ).read_text() == "user history"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [UnloadMode.UNLOAD, UnloadMode.SHUTDOWN, "reload"],
)
async def test_legacy_non_uninstall_keeps_agents(legacy_cloudpaw, mode):
    from qwenpaw.config.utils import load_config

    loader, root, work = legacy_cloudpaw
    profiles = _seed_cloud_agents(work)
    await loader.load_plugin(
        PluginManifest.model_validate_json(
            (root / "plugin.json").read_text(),
        ),
        root,
    )
    if mode == "reload":
        report = await loader.lifecycle.reload("cloudpaw")
        assert report.ok, report.errors
    else:
        report = await loader.lifecycle.unload("cloudpaw", mode)
        assert report.clean and report.quiescent, report.errors
    assert set(profiles).issubset(load_config().agents.profiles)
    assert root.exists()
    for agent_id in profiles:
        assert (work / "workspaces" / agent_id / "history.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stop", "save"])
async def test_legacy_cleanup_failure_keeps_retry_marker(
    legacy_cloudpaw,
    monkeypatch,
    failure,
):
    from qwenpaw.config import utils as config_utils

    loader, root, work = legacy_cloudpaw
    profiles = _seed_cloud_agents(work)
    manager = _manager(profiles)

    async def stop(agent_id):
        if failure == "stop":
            raise RuntimeError("connection still running")
        manager.agents.pop(agent_id)
        return True

    manager.stop_agent = AsyncMock(side_effect=stop)
    loader.registry.set_workspace_manager(manager)
    await loader.load_plugin(
        PluginManifest.model_validate_json(
            (root / "plugin.json").read_text(),
        ),
        root,
    )
    real_save = config_utils.save_config
    if failure == "save":
        monkeypatch.setattr(
            config_utils,
            "save_config",
            Mock(side_effect=OSError("config disk write failed")),
        )
    report = await loader.lifecycle.unload(
        "cloudpaw",
        UnloadMode.UNINSTALL,
        delete_files=True,
    )
    assert not report.clean
    assert report.quiescent is (failure == "save")
    assert report.errors
    assert root.exists()
    marker = provisions_dir() / "compat" / "cloudpaw.json"
    assert set(json.loads(marker.read_text())["agents"]) == set(profiles)
    disk_config = json.loads((work / "config.json").read_text())
    assert set(profiles).issubset(disk_config["agents"]["profiles"])
    for agent_id in profiles:
        assert (work / "workspaces" / agent_id / "history.txt").exists()

    original_code = (root / "plugin.py").read_bytes()
    retry = PluginLoader([root.parent])
    retry.registry = loader.registry
    for target in (loader, retry):
        update = await target.lifecycle.reload("cloudpaw")
        assert not update.ok
        assert update.errors
        assert any("uninstall" in error.lower() for error in update.errors)
        assert (root / "plugin.py").read_bytes() == original_code
        assert marker.exists()
        with pytest.raises(RuntimeError, match="being uninstalled"):
            await manager.get_agent("cloud-orchestrator")

    async def successful_stop(agent_id):
        manager.agents.pop(agent_id, None)
        return True

    manager.stop_agent.side_effect = successful_stop
    monkeypatch.setattr(config_utils, "save_config", real_save)
    # A new loader replays the persisted cleanup without a running plugin.
    report = await retry.lifecycle.unload(
        "cloudpaw",
        UnloadMode.UNINSTALL,
        delete_files=True,
    )
    assert report.clean and report.quiescent, report.errors
    assert not marker.exists()
    assert not root.exists()
    assert not manager.agents


@pytest.mark.asyncio
async def test_legacy_same_id_foreign_workspace_is_not_claimed(
    legacy_cloudpaw,
):
    from qwenpaw.config.config import AgentProfileRef, AgentsConfig, Config
    from qwenpaw.config.utils import load_config, save_config

    loader, _root, work = legacy_cloudpaw
    foreign = work / "personal-workspace"
    foreign.mkdir()
    (foreign / "agent.json").write_text(
        json.dumps(
            {
                "id": "cloud-orchestrator",
                "name": "CloudPaw-Master",
            },
        ),
        encoding="utf-8",
    )
    user_file = foreign / "private.txt"
    user_file.write_text("private", encoding="utf-8")
    save_config(
        Config(
            agents=AgentsConfig(
                profiles={
                    "cloud-orchestrator": AgentProfileRef(
                        id="cloud-orchestrator",
                        workspace_dir=str(foreign),
                    ),
                },
            ),
        ),
    )
    manager = _manager(["cloud-orchestrator"])
    manager.stop_agent = AsyncMock()
    loader.registry.set_workspace_manager(manager)
    report = await loader.lifecycle.unload(
        "cloudpaw",
        UnloadMode.UNINSTALL,
        delete_files=True,
    )
    assert report.clean and report.quiescent, report.errors
    manager.stop_agent.assert_not_awaited()
    assert "cloud-orchestrator" in load_config().agents.profiles
    assert user_file.read_text() == "private"


@pytest.mark.asyncio
async def test_legacy_stop_timeout_reuses_pending_task(
    legacy_cloudpaw,
    monkeypatch,
):
    loader, root, work = legacy_cloudpaw
    profiles = _seed_cloud_agents(work)
    manager = MultiAgentManager()
    release = asyncio.Event()
    calls = []

    async def stop():
        calls.append("cloud-orchestrator")
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue

    manager.agents.update(
        {
            agent_id: SimpleNamespace(
                agent_id=agent_id,
                task_tracker=None,
                stop=(
                    stop if agent_id == "cloud-orchestrator" else AsyncMock()
                ),
            )
            for agent_id in profiles
        },
    )
    other = SimpleNamespace(stop=AsyncMock())
    manager.agents["other"] = other
    loader.registry.set_workspace_manager(manager)
    monkeypatch.setattr(
        "qwenpaw.plugins.custody.CONNECTION_STOP_SECONDS",
        0.01,
    )
    try:
        for _ in range(2):
            report = await asyncio.wait_for(
                loader.lifecycle.unload(
                    "cloudpaw",
                    UnloadMode.UNINSTALL,
                    delete_files=True,
                ),
                0.2,
            )
            assert not report.clean and not report.quiescent
            assert report.errors
            assert root.exists()
        assert await asyncio.wait_for(manager.stop_agent("other"), 0.2)
        other.stop.assert_awaited_once()
        assert "other" not in manager.agents
        assert len(calls) == 1
        assert (provisions_dir() / "compat" / "cloudpaw.json").exists()
    finally:
        release.set()
        await asyncio.sleep(0)
    update = await loader.lifecycle.reload("cloudpaw")
    assert not update.ok and update.errors
    with pytest.raises(RuntimeError, match="being uninstalled"):
        await manager.get_agent("cloud-orchestrator")
    report = await loader.lifecycle.unload(
        "cloudpaw",
        UnloadMode.UNINSTALL,
        delete_files=True,
    )
    assert report.clean and report.quiescent, report.errors
    assert len(calls) == 1
    assert not root.exists()


@pytest.mark.asyncio
async def test_uninstall_reservation_blocks_cached_workspace_requests(
    legacy_cloudpaw,
    monkeypatch,
):
    from qwenpaw.app.workspace.workspace import Workspace

    _loader, _root, work = legacy_cloudpaw
    manager = MultiAgentManager()
    workspace = Workspace("cloud-orchestrator", str(work / "cloud-agent"))
    workspace.set_manager(manager)
    other = object()
    manager.agents.update({"cloud-orchestrator": workspace, "other": other})
    manager.reserve_agent_uninstall(["cloud-orchestrator"])
    load_config = Mock(
        side_effect=AssertionError("request crossed reservation"),
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        load_config,
    )
    with pytest.raises(RuntimeError, match="being uninstalled"):
        await manager.get_agent("cloud-orchestrator")
    with pytest.raises(RuntimeError, match="being uninstalled"):
        await anext(workspace.stream_query(object()))
    load_config.assert_not_called()
    assert await manager.get_agent("other") is other
    manager.release_agent_uninstall(["cloud-orchestrator"])
    assert await manager.get_agent("cloud-orchestrator") is workspace
