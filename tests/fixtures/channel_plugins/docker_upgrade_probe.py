"""Installed-image boot phases; no HTTP server or model provider is started."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import psutil
import qwenpaw
from qwenpaw.app.migration import migrate_legacy_workspace_to_default_agent
from qwenpaw.config.config import load_agent_config
from qwenpaw.config.utils import get_config_path, load_config
from qwenpaw.plugins.channel_bootstrap import resolve_default_channel_runtime
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.official_channels import provision_bundled_channels
from qwenpaw.plugins.workspace_projector import WorkspaceProjector


def tree(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


async def main():
    assert Path(qwenpaw.__file__).is_relative_to(Path(sys.prefix))
    expected = json.loads(Path(sys.argv[1]).read_text())
    assert os.environ["QWENPAW_CHANNEL_PRESET"] == expected["environment_preset"]
    commands = []

    def observe(event, args):
        if event == "subprocess.Popen":
            command = list(map(str, args[1]))
            commands.append(command)
            assert not any(
                word in command
                for word in ("pip", "ensurepip", "repair", "prepare-upgrade")
            ), command

    sys.addaudithook(observe)
    # Same conversion and ordering as app.lifespan, before channel discovery.
    migrated = migrate_legacy_workspace_to_default_agent()
    root = get_config_path().parent
    settings = resolve_default_channel_runtime()
    dependencies = tree(settings.dependency_install_target)
    loader = PluginLoader([root / "plugins"], channel_runtime=settings)
    workspaces = []
    loader.registry.projector = WorkspaceProjector(live_workspaces=lambda: workspaces)
    await loader.load_all_plugins(
        configs=load_config().plugins, types=["channel"], activate=False
    )
    assert await provision_bundled_channels(loader) == {}
    config = load_agent_config("default")
    catalog = loader.registry.get_channel_catalog()
    assert set(catalog) == set(expected["installed"])
    for key, owner in expected["owners"].items():
        source = loader.find_installed_plugin_dir(owner)
        if key not in expected["installed"]:
            assert source is None
        else:
            assert source == root / "plugins" / owner
            assert catalog[key].plugin_id == owner
            assert catalog[key].global_enabled is (owner not in expected["disabled"])
    state = load_config().channel_plugin_state
    assert state.preset == expected["preset"] and state.legacy_pending == []
    assert set(state.legacy_captured) == set(expected["owners"])
    sources = tree(root / "plugins")
    child_pid = None
    if expected["transport"]:
        from qwenpaw.app.channels.manager import ChannelManager
        from qwenpaw.app.chats.manager import ChatManager
        from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
        from qwenpaw.app.task_tracker import TaskTracker
        from qwenpaw.schemas import Message, RunStatus, TextContent

        requests = []
        delivered = asyncio.Event()

        async def on_reply_sent(*_args):
            delivered.set()

        async def agent(request):
            requests.append(request)
            assert request.channel == "mqtt"
            assert request.user_id == "client17"
            assert request.session_id == "mqtt:client17"
            assert request.input[0].content == [TextContent(text="historic inbound")]
            yield Message(
                object="message",
                status=RunStatus.Completed,
                role="assistant",
                content=[TextContent(text="docker-upgrade-answer")],
            )

        workspace_dir = Path(config.workspace_dir)
        workspace = SimpleNamespace(
            agent_id="default",
            workspace_dir=workspace_dir,
            _config=config,
            stream_query=agent,
            task_tracker=TaskTracker(),
            on_last_dispatch=None,
            chat_manager=ChatManager(
                repo=JsonChatRepository(workspace_dir / "chats.json")
            ),
        )
        manager = ChannelManager.from_config(
            agent,
            config,
            workspace_dir=workspace_dir,
            defer_process_channels=True,
            on_last_dispatch=on_reply_sent,
        )
        workspace.channel_manager = manager
        manager.set_workspace(workspace)
        workspaces.append(workspace)
        try:
            await manager.start_all()
            # Dependency checking and child construction happen automatically.
            await loader.activate_all_loaded()
            channel = await manager.get_channel("mqtt")
            assert channel is not None
            assert channel._launch_spec.config["port"] == expected["mqtt"]["port"]
            assert all(
                channel._launch_spec.config[key] == value
                for key, value in expected["mqtt"].items()
            )
            assert (
                "channel_validation_passed"
                in loader.get_loaded_plugin("mqtt").diagnostics
            )
            child_pid = channel.channel_process.health_snapshot()["pid"]
            assert child_pid and child_pid != os.getpid()
            await asyncio.wait_for(delivered.wait(), 10)
            assert len(requests) == 1
            assert len(await workspace.chat_manager.list_chats(channel="mqtt")) == 1
            from importlib.metadata import distribution

            assert Path(distribution("paho-mqtt")._path).is_relative_to(
                Path(sys.prefix)
            )
        finally:
            await manager.stop_all()
            assert child_pid is None or not psutil.pid_exists(child_pid)
    assert tree(root / "plugins") == sources
    assert tree(settings.dependency_install_target) == dependencies == {}
    print(
        json.dumps(
            {
                "pid": os.getpid(),
                "child": child_pid,
                "migrated": migrated,
                "sources": sources,
                "commands": commands,
            }
        )
    )


asyncio.run(main())
