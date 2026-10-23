# -*- coding: utf-8 -*-
"""Run reused channel process acceptance against extracted wheel files."""

# pylint: disable=redefined-outer-name,protected-access,too-many-statements

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

import psutil

import pytest


CHANNEL = os.environ["QWENPAW_C7_CHANNEL"]
RELEASE_ROOT = Path(os.environ["QWENPAW_C7_RELEASE_ROOT"]).resolve()
SITE = RELEASE_ROOT / "src"
contracts = importlib.import_module(f"{CHANNEL}_process_suite")
contracts.ROOT = RELEASE_ROOT
os.environ["QWENPAW_B5_CHANNEL"] = CHANNEL
installed_suite = importlib.import_module("installation_process_suite")
os.environ["QWENPAW_C2_CHANNEL"] = CHANNEL
workspace_suite = importlib.import_module("workspace_runtime_suite")
workspace_suite.ROOT = RELEASE_ROOT
runtime = contracts.runtime
proxy_api = contracts.proxy_api


@pytest.mark.asyncio
async def test_c7_extracted_wheel_receive_send_restart_stop(
    runtime,
    monkeypatch,
) -> None:
    import qwenpaw

    assert Path(qwenpaw.__file__).resolve().is_relative_to(SITE)
    await installed_suite.test_installed_layout_receive_send_restart_stop(
        runtime,
        monkeypatch,
    )


@pytest.mark.asyncio
async def test_c7_extracted_wheel_resolver_and_offline_full_seed() -> None:
    from qwenpaw.config import utils as config_utils
    from qwenpaw.plugins.channel_bootstrap import (
        default_channel_preset,
        resolve_default_channel_runtime,
    )
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.official_channels import provision_bundled_channels

    assert default_channel_preset() == "channels-full"
    settings = resolve_default_channel_runtime()
    assert settings.support_root == SITE
    assert (
        Path(settings.python_executable).resolve()
        == Path(os.sys.executable).resolve()
    )
    assert settings.selected_channels is None
    assert settings.allows("sample_chat")
    assert settings.dependency_install_target.is_relative_to(
        config_utils.WORKING_DIR,
    )
    loader = PluginLoader(
        [config_utils.get_plugins_dir()],
        channel_runtime=settings,
    )
    assert await provision_bundled_channels(loader) == {}
    for channel in ("dingtalk", "feishu"):
        source = loader.find_installed_plugin_dir(channel)
        assert source is not None
        assert source.is_relative_to(config_utils.WORKING_DIR)
        assert (source / channel / "driver.py").is_file()


@pytest.mark.asyncio
async def test_c7_extracted_wheel_light_keeps_bundles_dormant() -> None:
    from qwenpaw.config import utils as config_utils
    from qwenpaw.plugins.channel_bootstrap import default_channel_preset
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.official_channels import provision_bundled_channels

    assert default_channel_preset() == "light"
    loader = PluginLoader([config_utils.get_plugins_dir()])
    assert await provision_bundled_channels(loader) == {}
    assert loader.find_installed_plugin_dir("feishu") is None
    assert loader.find_installed_plugin_dir("dingtalk") is None


@pytest.mark.asyncio
async def test_c7_initial_boot_loader_manager_child_uses_product_timeout(
    tmp_path,
    monkeypatch,
) -> None:
    """Join C6 boot steps to C2's real Manager and controlled child I/O."""
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.app.chats.manager import ChatManager
    from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
    from qwenpaw.app.task_tracker import TaskTracker
    from qwenpaw.config import utils as config_utils
    from qwenpaw.config.config import Config
    from qwenpaw.plugins import official_channels
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector
    from qwenpaw.schemas import Message, RunStatus, TextContent

    settings = resolve_default_channel_runtime()
    assert settings.support_root == SITE
    assert settings.startup_timeout == 10.0
    assert settings.dependency_install_target.is_relative_to(
        config_utils.WORKING_DIR,
    )
    config_utils.mutate_config(
        lambda config: config.plugins.update({CHANNEL: {"enabled": True}}),
    )
    instrumented, network = workspace_suite.installed_artifact(tmp_path)
    original_bundle = official_channels.bundled_channel_source

    @contextmanager
    def controlled_bundle(plugin_id, **kwargs):
        with original_bundle(plugin_id, **kwargs) as source:
            if plugin_id == CHANNEL:
                shutil.copy2(
                    instrumented / CHANNEL / "boundary.py",
                    source / CHANNEL / "boundary.py",
                )
                shutil.copy2(
                    instrumented / "channel.json",
                    source / "channel.json",
                )
            yield source

    monkeypatch.setattr(
        official_channels,
        "bundled_channel_source",
        controlled_bundle,
    )
    old_registry = PluginRegistry._instance
    PluginRegistry._instance = None
    loader = PluginLoader(
        [config_utils.get_plugins_dir()],
        channel_runtime=settings,
    )
    workspace = workspace_suite.Workspace()
    workspace.agent_id = "c7-release"
    workspace.workspace_dir = tmp_path / "workspace"
    workspace.workspace_dir.mkdir()
    creds = (
        {"app_id": "cli_test", "app_secret": "test-only"}
        if CHANNEL == "feishu"
        else {"client_id": "client-one", "client_secret": "test-only"}
    )
    workspace._config = Config.model_validate(
        {"channels": {CHANNEL: {"enabled": True, **creds}}},
    )
    workspace.started = asyncio.Event()
    workspace.requests = []

    async def agent(request):
        workspace.requests.append(request)
        workspace.started.set()
        yield Message(
            object="message",
            status=RunStatus.Completed,
            role="assistant",
            content=[TextContent(text="c7-release-answer")],
        )

    workspace.stream_query = agent
    workspace.chat_manager = ChatManager(
        repo=JsonChatRepository(workspace.workspace_dir / "chats.json"),
    )
    workspace.task_tracker = TaskTracker()
    workspace.on_last_dispatch = None
    loader.registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    manager = None
    metrics = None
    try:
        await loader.load_all_plugins(
            configs={},
            types=["channel"],
            activate=False,
        )
        assert await official_channels.provision_bundled_channels(loader) == {}
        source = loader.find_installed_plugin_dir(CHANNEL)
        assert source is not None and source.is_relative_to(
            config_utils.WORKING_DIR,
        )
        manager = ChannelManager.from_config(
            agent,
            workspace._config,
            workspace_dir=workspace.workspace_dir,
        )
        workspace.channel_manager = manager
        manager.set_workspace(workspace)
        start_at = time.perf_counter()
        await manager.start_all()
        console = await manager.get_channel("console")
        assert console is not None
        console_output = [
            item
            async for item in console.stream_one(
                {
                    "sender_id": "c7-console-user",
                    "content_parts": [TextContent(text="core ready")],
                },
            )
        ]
        assert any("c7-release-answer" in item for item in console_output)
        console_ready_seconds = time.perf_counter() - start_at
        workspace.started.clear()
        workspace.requests.clear()
        await loader.activate_all_loaded()
        channel = await manager.get_channel(CHANNEL)
        assert channel is not None
        assert channel._launch_spec.startup_timeout == settings.startup_timeout
        first_pid = channel.channel_process.health_snapshot()["pid"]
        assert first_pid and first_pid != os.getpid()
        work = network / str(first_pid)
        await contracts.eventually(
            lambda: workspace_suite.rows(work, "connected"),
        )
        if os.environ.get("QWENPAW_C7_METRICS_PATH"):
            parent_rss = psutil.Process().memory_info().rss
            child_rss = psutil.Process(first_pid).memory_info().rss
            metrics = {
                "channel": CHANNEL,
                "scope": "Manager and controlled child; not Console HTTP",
                "console_stream_ready_seconds": console_ready_seconds,
                "ready_seconds": time.perf_counter() - start_at,
                "parent_rss_bytes": parent_rss,
                "child_rss_bytes": child_rss,
                "summed_current_rss_bytes": parent_rss + child_rss,
                "parent_sdk_modules": sum(
                    name == prefix or name.startswith(prefix + ".")
                    for name in sys.modules
                    for prefix in (
                        ("lark_oapi",)
                        if CHANNEL == "feishu"
                        else ("dingtalk_stream", "alibabacloud_dingtalk")
                    )
                ),
            }
        workspace_suite.emit(work, contracts.message("c7-first", group=True))
        await asyncio.wait_for(workspace.started.wait(), 8)
        await contracts.eventually(lambda: workspace_suite.sent(work))
        assert workspace.requests
        assert workspace_suite.sent(work)[0]["pid"] == first_pid
        stop_at = time.perf_counter()
        assert (await manager.stop_one(CHANNEL)).stopped
        assert not psutil.pid_exists(first_pid)
        if metrics is not None:
            metrics["stop_seconds"] = time.perf_counter() - stop_at
            metrics["child_alive_after_stop"] = psutil.pid_exists(
                first_pid,
            )
            metrics["parent_rss_after_stop_bytes"] = (
                psutil.Process().memory_info().rss
            )
            Path(os.environ["QWENPAW_C7_METRICS_PATH"]).write_text(
                json.dumps(metrics, indent=2),
                encoding="utf-8",
            )
        replacement = (
            await manager.start_one(CHANNEL, workspace._config)
        ).channel
        assert replacement is not None
        second_pid = replacement.channel_process.health_snapshot()["pid"]
        assert second_pid != first_pid
        assert (
            replacement._launch_spec.startup_timeout
            == settings.startup_timeout
        )
        await manager.stop_one(CHANNEL)
        assert not psutil.pid_exists(second_pid)
        assert (
            json.loads((source / "plugin.json").read_text())["publish"]
            is False
        )
    finally:
        if manager is not None:
            await manager.stop_all()
        if loader.get_loaded_plugin(CHANNEL) is not None:
            await loader.unload_plugin(CHANNEL)
        PluginRegistry._instance = old_registry
