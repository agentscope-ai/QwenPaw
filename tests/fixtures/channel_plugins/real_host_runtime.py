"""Bind a real Runtime/Builder/Executor/Agent to an existing host fixture.

Only the model provider boundary is controlled. Config, hooks, agent,
session storage, manager, projection, IPC and platform Driver stay real.
"""

import os
from types import SimpleNamespace as NS

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import TextBlock


class LocalModel(ChatModelBase):
    def __init__(self, calls, text):
        super().__init__(
            credential=None,
            model="local-network",
            parameters=ChatModelBase.Parameters(),
            stream=False,
            context_size=32768,
        )
        self.calls, self.text = calls, text
        self.formatter = OpenAIChatFormatter()

    async def __call__(self, *args, **kwargs):
        self.calls.append(
            {"pid": os.getpid(), "messages": kwargs.get("messages")}
        )
        return ChatResponse(content=[TextBlock(text=self.text)], is_last=True)

    async def count_tokens(self, **kwargs):
        return len(str(kwargs)) // 4


async def bind_real_runtime(rt, monkeypatch, *, reply="actual agent answer"):
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

    calls, builds, events = [], [], []
    model = LocalModel(calls, reply)
    monkeypatch.setattr(
        model_factory,
        "create_model_and_formatter",
        lambda **kwargs: (model, model.formatter),
    )
    config = load_config()
    config.agents.profiles[rt.ws.agent_id] = AgentProfileRef(
        id=rt.ws.agent_id, workspace_dir=str(rt.ws.workspace_dir)
    )
    save_config(config)
    profile = AgentProfileConfig(
        id=rt.ws.agent_id,
        name="Actual Agent",
        workspace_dir=str(rt.ws.workspace_dir),
        active_model=ModelSlotConfig(
            provider_id="local-network", model="local-network"
        ),
    )
    profile.running.max_iters = 2
    profile.running.auto_title_config.enabled = False
    profile.running.light_context_config.strategy = "native"
    profile.running.light_context_config.visual_compact_config.enabled = False
    profile.coding_mode.enabled = False
    save_agent_config(rt.ws.agent_id, profile)

    class ObserveAgent(LifecycleHook):
        phase, name = Phase.POST_AGENT_BUILD, "test_observe_real_agent"

        async def run(self, ctx):
            assert isinstance(ctx.agent, QwenPawAgent)
            builds.append(
                {
                    "pid": os.getpid(),
                    "session_id": ctx.session_id,
                    "agent": type(ctx.agent).__name__,
                }
            )
            return HookResult()

    await rt.loader.lifecycle.set_enabled(rt.record.manifest.id, False)
    await rt.manager.stop_all()
    rt.ws.plugins = WorkspacePlugins()
    for hook in (SessionLoadHook(), SessionSaveHook(), ObserveAgent()):
        rt.ws.plugins.hook_registry.register(hook)
    rt.ws.session = SafeJSONSession(str(rt.ws.workspace_dir / "sessions"))
    host = Runtime(workspace=rt.ws, app_services=None)

    async def process(request):
        rt.ws.requests.append(request)
        async for event in host.run(request):
            events.append(
                event.model_dump(mode="json")
                if hasattr(event, "model_dump")
                else repr(event)
            )
            yield event

    rt.ws.stream_query = process
    manager = ChannelManager.from_config(
        process, rt.ws._config, workspace_dir=rt.ws.workspace_dir
    )
    manager.set_workspace(rt.ws)
    rt.ws.channel_manager = manager
    rt.manager = manager
    await manager.start_all()
    await rt.loader.lifecycle.set_enabled(rt.record.manifest.id, True)
    rt.channel = await manager.get_channel(rt.key)
    rt.process = rt.channel.channel_process
    return NS(
        runtime=host,
        calls=calls,
        builds=builds,
        events=events,
        session=rt.ws.session,
    )
