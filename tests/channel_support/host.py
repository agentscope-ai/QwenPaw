# -*- coding: utf-8 -*-
"""Minimal loader and workspace wiring for a synthetic platform."""

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import zipfile

from tests.channel_support.process import ROOT, alive, eventually

KEY = "feishu"


def rows(path, kind=None):
    values = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    return [row for row in values if kind is None or row["kind"] == kind]


def texts(value):
    if isinstance(value, dict):
        if value.get("type") == "text":
            yield value["text"]
        for child in value.values():
            yield from texts(child)
    elif isinstance(value, list):
        for child in value:
            yield from texts(child)


def session_path(ws, room, user="alice"):
    from qwenpaw.app.chats.session import session_filename

    return ws.workspace_dir / "sessions" / KEY / session_filename(room, user)


async def saved_texts(ws, room, user="alice"):
    from qwenpaw.app.chats.session import SafeJSONSession
    from qwenpaw.runtime._state_utils import StateProxy

    proxy = StateProxy()
    await SafeJSONSession(
        str(ws.workspace_dir / "sessions"),
    ).load_session_state(
        session_id=room,
        user_id=user,
        channel=KEY,
        allow_not_exist=False,
        agent=proxy,
    )
    return list(texts(proxy.data))


class Host:
    @classmethod
    async def create(cls, directory, monkeypatch):
        self = cls()
        from qwenpaw.__version__ import __version__
        from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
        from qwenpaw.plugins.loader import PluginLoader
        from qwenpaw.plugins.registry import PluginRegistry
        from qwenpaw.plugins.workspace_projector import WorkspaceProjector

        self.root, self.patch = directory, monkeypatch
        self.installed = directory / "installed" / KEY
        self.ledger = directory / "platform.jsonl"
        self.site = directory / "site"
        self.site.mkdir()
        self.config_path = directory / "config.json"
        monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", directory / "host")
        monkeypatch.setattr(
            "qwenpaw.constant.PLUGINS_DIR",
            self.installed.parent,
        )
        monkeypatch.setattr(
            "qwenpaw.config.utils.WORKING_DIR",
            directory / "host",
        )
        monkeypatch.setattr("qwenpaw.config.utils._config_cache", None)
        monkeypatch.setattr("qwenpaw.config.utils._config_mtime", None)
        monkeypatch.setattr("qwenpaw.config.utils._agent_config_cache", {})
        monkeypatch.setattr(
            "qwenpaw.config.utils.get_config_path",
            lambda: self.config_path,
        )
        self.previous = PluginRegistry._instance
        PluginRegistry._instance = None
        self.registry = PluginRegistry()
        self.workspaces, self.models = [], {}
        self.loader = await PluginLoader.create(
            [self.installed.parent],
            channel_runtime=ChannelRuntimeSettings(
                python_executable=sys.executable,
                support_root=ROOT / "src",
                qwenpaw_version=__version__,
                selected_channels=frozenset({KEY}),
                startup_timeout=5,
                shutdown_timeout=0.4,
                admission_timeout=2,
                dependency_paths=(self.site,),
                dependency_install_target=self.site,
            ),
        )
        self.loader.registry = self.registry
        self.registry.projector = WorkspaceProjector(
            live_workspaces=lambda: self.workspaces,
        )
        return self

    def artifact(self, version="1.0.0", *, sdk=False, fail_start=False):
        source = self.root / ("incoming-" + version) / KEY
        source.mkdir(parents=True)
        manifest = json.loads(
            (ROOT / "plugins/channel/feishu/plugin.json").read_text(
                encoding="utf-8",
            ),
        )
        manifest["version"] = version
        (source / "plugin.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        descriptor = json.loads(
            (ROOT / "plugins/channel/feishu/channel.json").read_text(
                encoding="utf-8",
            ),
        )
        descriptor["entrypoint"] = {
            "scope": "runner",
            "module": "sample",
            "qualname": "Driver",
        }
        (source / "channel.json").write_text(
            json.dumps(descriptor),
            encoding="utf-8",
        )
        (source / "requirements.txt").write_text(
            "sample-shared-sdk==1.0\n" if sdk else "",
        )
        prefix = f"LEDGER={str(self.ledger)!r}\nVERSION={version!r}\n"
        (source / "sample.py").write_text(
            f"FAIL_START={fail_start!r}\n"
            + prefix
            + Path(__file__)
            .with_name("sample_channel.py")
            .read_text(
                encoding="utf-8",
            ),
            encoding="utf-8",
        )
        return source

    async def workspace(self, name, **settings):
        from qwenpaw.app.channels.manager import ChannelManager
        from qwenpaw.app.chats.manager import ChatManager
        from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
        from qwenpaw.app.task_tracker import TaskTracker
        from qwenpaw.config.config import (
            Config,
            AgentProfileConfig,
            AgentProfileRef,
            save_agent_config,
        )
        from qwenpaw.config.utils import load_config, save_config
        from qwenpaw.schemas import Message, RunStatus, TextContent

        directory = self.root / name
        directory.mkdir()
        ws = NS(
            agent_id=name,
            workspace_dir=directory,
            requests=[],
            model_calls=[],
            builds=[],
        )
        ws._config = Config.model_validate(
            {
                "channels": {
                    KEY: {
                        "enabled": True,
                        "app_id": name,
                        "app_secret": "local-only",
                        "no_text_debounce": True,
                        **settings,
                    },
                },
            },
        )

        async def process(request):
            ws.requests.append(request)
            yield Message(
                object="message",
                status=RunStatus.Completed,
                role="assistant",
                content=[TextContent(text="answer:" + name)],
            )

        root = load_config()
        root.agents.profiles[name] = AgentProfileRef(
            id=name,
            workspace_dir=str(directory),
        )
        save_config(root)
        save_agent_config(
            name,
            AgentProfileConfig(
                id=name,
                name=name,
                workspace_dir=str(directory),
                channels=ws._config.channels,
            ),
        )
        ws.stream_query = process
        ws.chat_manager = ChatManager(
            repo=JsonChatRepository(directory / "chats.json"),
        )
        ws.task_tracker = TaskTracker()
        ws.channel_manager = ChannelManager.from_config(
            process,
            ws._config,
            workspace_dir=directory,
        )
        ws.channel_manager.set_workspace(ws)
        self.workspaces.append(ws)
        await ws.channel_manager.start_all()
        return ws

    async def identity(self, ws):
        channel = await ws.channel_manager.get_channel(KEY)
        value = await channel.channel_process.call("sample.identity", {})
        return channel, value

    async def emit(self, ws, event_id="one", **values):
        channel, _ = await self.identity(ws)
        return await channel.channel_process.call(
            "sample.emit",
            {"id": event_id, **values},
        )

    async def close(self):
        from qwenpaw.plugins.registry import PluginRegistry

        try:
            if self.loader.get_loaded_plugin(KEY):
                await self.loader.unload_plugin(KEY)
            for ws in self.workspaces:
                await ws.channel_manager.stop_all()
            for row in rows(self.ledger, "connected"):
                assert not alive(row["pid"]), "Host left an owned worker alive"
        finally:
            PluginRegistry._instance = self.previous

    async def real_agent(self, ws, *, reply="actual agent answer"):
        from agentscope.formatter import OpenAIChatFormatter
        from agentscope.message import TextBlock
        from agentscope.model import ChatModelBase
        from agentscope.model._model_response import ChatResponse
        from qwenpaw.agents import model_factory
        from qwenpaw.agents.react_agent import QwenPawAgent
        from qwenpaw.app.channels.manager import ChannelManager
        from qwenpaw.app.chats.session import SafeJSONSession
        from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
        from qwenpaw.config.config import (
            AgentProfileConfig,
            AgentProfileRef,
            ModelSlotConfig,
            save_agent_config,
        )
        from qwenpaw.config.utils import load_config, save_config
        from qwenpaw.hooks.base import LifecycleHook
        from qwenpaw.hooks.session.session_hook import (
            SessionLoadHook,
            SessionSaveHook,
        )
        from qwenpaw.runtime.hooks import HookResult
        from qwenpaw.runtime.phases import Phase
        from qwenpaw.runtime.runtime import Runtime

        class Model(ChatModelBase):
            def __init__(self):
                super().__init__(
                    credential=None,
                    model="local-model",
                    parameters=ChatModelBase.Parameters(),
                    stream=True,
                    context_size=32768,
                )
                self.formatter = OpenAIChatFormatter()

            async def __call__(self, *args, **kwargs):
                ws.model_calls.append(
                    {"pid": os.getpid(), "messages": kwargs.get("messages")},
                )

                async def stream():
                    yield ChatResponse(
                        content=[TextBlock(id="answer", text=reply[:6])],
                        is_last=False,
                    )
                    yield ChatResponse(
                        content=[TextBlock(id="answer", text=reply[6:])],
                        is_last=False,
                    )
                    yield ChatResponse(
                        content=[TextBlock(id="answer", text=reply)],
                        is_last=True,
                    )

                return stream()

            async def count_tokens(self, **kwargs):
                return len(str(kwargs)) // 4

        model = Model()
        self.models[ws.agent_id] = model
        self.patch.setattr(
            model_factory,
            "create_model_and_formatter",
            lambda *, agent_id, **kwargs: (
                self.models[agent_id],
                self.models[agent_id].formatter,
            ),
        )
        config = load_config()
        config.agents.profiles[ws.agent_id] = AgentProfileRef(
            id=ws.agent_id,
            workspace_dir=str(ws.workspace_dir),
        )
        save_config(config)
        profile = AgentProfileConfig(
            id=ws.agent_id,
            name="Actual Agent",
            workspace_dir=str(ws.workspace_dir),
            active_model=ModelSlotConfig(
                provider_id="local-model",
                model="local-model",
            ),
        )
        profile.running.max_iters = 2
        profile.running.auto_title_config.enabled = False
        profile.running.light_context_config.strategy = "native"
        profile.running.light_context_config.visual_compact_config.enabled = (
            False
        )
        profile.coding_mode.enabled = False
        save_agent_config(ws.agent_id, profile)

        class Observe(LifecycleHook):
            phase, name = Phase.POST_AGENT_BUILD, "observe_real_agent"

            async def run(self, ctx):
                assert isinstance(ctx.agent, QwenPawAgent)
                ws.builds.append(
                    {"pid": os.getpid(), "session_id": ctx.session_id},
                )
                return HookResult()

        await ws.channel_manager.stop_all()
        ws.plugins = WorkspacePlugins()
        for hook in (SessionLoadHook(), SessionSaveHook(), Observe()):
            ws.plugins.hook_registry.register(hook)
        ws.session = SafeJSONSession(str(ws.workspace_dir / "sessions"))
        runtime = Runtime(workspace=ws, app_services=None)
        ws.events = []

        async def process(request):
            ws.requests.append(request)
            async for event in runtime.run(request):
                ws.events.append(event)
                yield event

        ws.stream_query = process
        ws.channel_manager = ChannelManager.from_config(
            process,
            ws._config,
            workspace_dir=ws.workspace_dir,
        )
        ws.channel_manager.set_workspace(ws)
        await ws.channel_manager.start_all()


def _local_dependency_wheel(directory, name, version, payload):
    directory.mkdir(parents=True, exist_ok=True)
    module = name.replace("-", "_")
    info = f"{module}-{version}.dist-info"
    files = {
        **payload,
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        ).encode(),
        f"{info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\n"
            b"Tag: py3-none-any\n"
        ),
    }
    records = []
    for filename, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
        records.append(
            f"{filename},sha256={digest.decode().rstrip('=')},{len(data)}\n",
        )
    files[f"{info}/RECORD"] = (
        "".join(records) + f"{info}/RECORD,,\n"
    ).encode()
    path = directory / f"{module}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for filename, data in files.items():
            archive.writestr(filename, data)
    return path


def local_wheel(directory, version="1.0", value="offline-sdk"):
    _local_dependency_wheel(
        directory,
        "sample-shared-sdk",
        version,
        {"sample_shared_sdk.py": f"VALUE = {value!r}\n".encode()},
    )
    return directory


def local_certifi_wheel(directory):
    """Synthetic dependency transaction data; this does not test TLS."""
    from importlib.metadata import version as installed_version
    from packaging.version import Version

    # pip wheel collects explicitly requested roots even when installed.
    # Match any newer installed pin as well as the minimum security floor.
    version = str(
        max(
            Version(installed_version("certifi")),
            Version("2026.10.19"),
        ),
    )
    return _local_dependency_wheel(
        directory,
        "certifi",
        version,
        {"certifi_fixture.txt": b"Synthetic transaction fixture; not TLS.\n"},
    )
