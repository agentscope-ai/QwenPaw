# -*- coding: utf-8 -*-
"""个人频道绑定运行时的身份与生命周期契约。"""

from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_bound_process_replaces_external_sender_with_platform_user() -> None:
    """外部频道身份直接成为平台 user_id 时，本测试必须失败。"""
    runtime = import_module("qwenpaw.app.channels.user_bindings")
    owner_user_id = uuid4()
    binding_id = uuid4()
    observed = []

    async def process(request):
        observed.append(request)
        yield {"type": "done"}

    request = SimpleNamespace(
        user_id="telegram-external-user",
        channel_meta={"chat_id": "chat-1"},
        request_context={},
    )
    wrapped = runtime.bind_process_identity(
        process,
        owner_user_id=owner_user_id,
        binding_id=binding_id,
    )

    events = [event async for event in wrapped(request)]

    assert events == [{"type": "done"}]
    assert observed[0].user_id == str(owner_user_id)
    assert observed[0].channel_meta == {
        "chat_id": "chat-1",
        "external_user_id": "telegram-external-user",
        "channel_binding_id": str(binding_id),
    }
    assert observed[0].request_context["user_id"] == str(owner_user_id)
    assert observed[0].request_context["channel_binding_id"] == str(binding_id)
    assert observed[0].request_context["actor_context"]["user_id"] == str(owner_user_id)
    assert observed[0].request_context["actor_context"]["actor_type"] == "external"


@pytest.mark.asyncio
async def test_bound_process_records_external_identity_before_agent_run() -> None:
    """外部身份只存在请求内而未形成绑定事实时，本测试必须失败。"""
    runtime = import_module("qwenpaw.app.channels.user_bindings")
    owner_user_id = uuid4()
    binding_id = uuid4()
    recorded = []

    async def record_external_identity(**kwargs):
        recorded.append(kwargs)

    async def process(request):
        assert len(recorded) == 1
        yield {"type": "done"}

    request = SimpleNamespace(
        user_id="telegram-user-42",
        session_id="telegram:chat-7",
        channel="telegram",
        channel_meta={
            "chat_id": "chat-7",
            "username": "alice",
            "bot_token": "must-not-be-persisted",
        },
        request_context={},
    )
    wrapped = runtime.bind_process_identity(
        process,
        owner_user_id=owner_user_id,
        binding_id=binding_id,
        record_external_identity=record_external_identity,
    )

    assert [event async for event in wrapped(request)] == [{"type": "done"}]
    assert recorded == [
        {
            "binding_id": binding_id,
            "external_subject_id": "telegram-user-42",
            "platform_user_id": owner_user_id,
            "metadata": {
                "channel": "telegram",
                "session_id": "telegram:chat-7",
                "chat_id": "chat-7",
                "username": "alice",
            },
        }
    ]


def test_personal_binding_records_last_target_for_binding_owner(monkeypatch) -> None:
    runtime = import_module("qwenpaw.app.channels.user_bindings")
    owner_user_id = uuid4()
    binding_id = uuid4()
    callbacks = []
    saved = []

    class Manager:
        channels = []

        def set_workspace(self, _workspace):
            return None

    def from_config(**kwargs):
        callbacks.append(kwargs["on_last_dispatch"])
        return Manager()

    from qwenpaw.app.channels.manager import ChannelManager

    monkeypatch.setattr(ChannelManager, "from_config", from_config)
    monkeypatch.setattr(runtime, "update_last_dispatch", lambda **kwargs: saved.append(kwargs))
    workspace = SimpleNamespace(
        agent_id="shared-agent",
        workspace_dir="workspace",
        stream_query=lambda request: request,
        _config=SimpleNamespace(language="zh"),
    )

    runtime._build_channel_manager(
        workspace=workspace,
        binding_repository=SimpleNamespace(upsert_external_identity=AsyncMock()),
        channel_type="telegram",
        config={"enabled": True},
        owner_user_id=owner_user_id,
        binding_id=binding_id,
    )
    callbacks[0]("telegram", "external-user", "telegram:chat-1")

    assert saved == [
        {
            "channel": "telegram",
            "user_id": "external-user",
            "session_id": "telegram:chat-1",
            "agent_id": "shared-agent",
            "platform_user_id": str(owner_user_id),
            "binding_id": str(binding_id),
        }
    ]


class FakeManager:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    async def start_all(self) -> None:
        self.started += 1

    async def stop_all(self) -> None:
        self.stopped += 1


class FailingManager(FakeManager):
    async def start_all(self) -> None:
        self.started += 1
        raise RuntimeError("channel_start_failed")


@pytest.mark.asyncio
async def test_reconcile_replaces_binding_without_touching_agent_manager(
) -> None:
    """更新个人绑定未停止旧监听器或复用 Agent manager 时，本测试必须失败。"""
    runtime = import_module("qwenpaw.app.channels.user_bindings")
    binding_id = uuid4()
    owner_user_id = uuid4()
    old_manager = FakeManager()
    new_manager = FakeManager()
    built = []

    class Repository:
        async def get_runtime_config(self, **kwargs):
            assert kwargs == {
                "binding_id": binding_id,
                "owner_user_id": owner_user_id,
            }
            return {"bot_prefix": "mine"}

    class WorkspaceManager:
        async def get_agent(self, agent_key):
            assert agent_key == "public-agent"
            return SimpleNamespace(agent_id=agent_key)

    def manager_factory(**kwargs):
        built.append(kwargs)
        return new_manager

    registry = runtime.UserChannelBindingRuntimeRegistry(
        workspace_manager=WorkspaceManager(),
        binding_repository=Repository(),
        manager_factory=manager_factory,
    )
    registry._managers[binding_id] = old_manager
    record = SimpleNamespace(
        id=binding_id,
        agent_key="public-agent",
        owner_user_id=owner_user_id,
        channel_type="console",
        enabled=True,
    )

    await registry.reconcile(record)

    assert old_manager.stopped == 1
    assert new_manager.started == 1
    assert registry._managers[binding_id] is new_manager
    assert built[0]["config"] == {"bot_prefix": "mine", "enabled": True}
    assert isinstance(built[0]["binding_repository"], Repository)


@pytest.mark.asyncio
async def test_reconcile_cleans_up_manager_when_start_fails() -> None:
    """启动失败时必须停止半启动 manager，且不能登记为运行中。"""
    runtime = import_module("qwenpaw.app.channels.user_bindings")
    binding_id = uuid4()
    owner_user_id = uuid4()
    failed_manager = FailingManager()

    class Repository:
        async def get_runtime_config(self, **kwargs):
            return {"bot_prefix": "mine"}

    class WorkspaceManager:
        async def get_agent(self, agent_key):
            return SimpleNamespace(agent_id=agent_key)

    registry = runtime.UserChannelBindingRuntimeRegistry(
        workspace_manager=WorkspaceManager(),
        binding_repository=Repository(),
        manager_factory=lambda **kwargs: failed_manager,
    )
    record = SimpleNamespace(
        id=binding_id,
        agent_key="public-agent",
        owner_user_id=owner_user_id,
        channel_type="console",
        enabled=True,
    )

    with pytest.raises(RuntimeError, match="channel_start_failed"):
        await registry.reconcile(record)

    assert failed_manager.started == 1
    assert failed_manager.stopped == 1
    assert binding_id not in registry._managers
