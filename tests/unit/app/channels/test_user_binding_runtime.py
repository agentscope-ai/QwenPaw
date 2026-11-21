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


def test_personal_binding_records_last_target_for_binding_owner(monkeypatch, tmp_path) -> None:
    runtime = import_module("qwenpaw.app.channels.user_bindings")
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
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


def test_personal_binding_uses_user_and_binding_scoped_state_paths(
    monkeypatch, tmp_path,
) -> None:
    """同一智能体下两个用户的媒体、凭据和监听器缓存不能共用目录。"""
    runtime = import_module("qwenpaw.app.channels.user_bindings")
    from qwenpaw.app.channels.manager import ChannelManager

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    captured = []

    class Manager:
        channels = []

        def set_workspace(self, workspace):
            pass

    def from_config(**kwargs):
        captured.append(kwargs)
        return Manager()

    monkeypatch.setattr(ChannelManager, "from_config", from_config)
    workspace = SimpleNamespace(
        agent_id="shared-agent", workspace_dir=tmp_path / "workspaces/shared-agent",
        stream_query=lambda request: request, _config=SimpleNamespace(language="zh"),
    )
    owners = [uuid4(), uuid4()]
    bindings = [uuid4(), uuid4()]
    for owner, binding in zip(owners, bindings):
        runtime._build_channel_manager(
            workspace=workspace,
            binding_repository=SimpleNamespace(upsert_external_identity=AsyncMock()),
            channel_type="wechat",
            config={"enabled": True, "media_dir": str(workspace.workspace_dir / "media"),
                    "bot_token_file": str(workspace.workspace_dir / "token.json")},
            owner_user_id=owner, binding_id=binding,
        )

    for kwargs, owner, binding in zip(captured, owners, bindings):
        expected = tmp_path / "user_workspaces" / str(owner) / "shared-agent" / "channels" / str(binding)
        assert kwargs["workspace_dir"] == expected
        assert kwargs["config"].channels.wechat.media_dir == str(expected / "media")
        assert kwargs["config"].channels.wechat.bot_token_file == str(expected / "wechat_bot_token.json")
        assert expected.is_dir()
    assert captured[0]["workspace_dir"] != captured[1]["workspace_dir"]


@pytest.mark.parametrize("channel_type", ["dingtalk", "feishu", "wechat", "wecom", "qq"])
def test_each_personal_connector_instantiates_only_its_scoped_listener(
    monkeypatch, tmp_path, channel_type,
) -> None:
    """五种个人连接器实际构造时不夹带其他默认频道，也不共用状态目录。"""
    runtime = import_module("qwenpaw.app.channels.user_bindings")
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    workspace = SimpleNamespace(
        agent_id="shared-agent", workspace_dir=tmp_path / "workspaces/shared-agent",
        stream_query=lambda request: request, _config=SimpleNamespace(language="zh"),
    )
    managers = []
    for _ in range(2):
        owner, binding = uuid4(), uuid4()
        manager = runtime._build_channel_manager(
            workspace=workspace,
            binding_repository=SimpleNamespace(upsert_external_identity=AsyncMock()),
            channel_type=channel_type, config={"enabled": True},
            owner_user_id=owner, binding_id=binding,
        )
        assert [channel.channel for channel in manager.channels] == [channel_type]
        channel = manager.channels[0]
        expected = tmp_path / "user_workspaces" / str(owner) / "shared-agent" / "channels" / str(binding)
        assert channel._workspace_dir == expected
        assert channel._media_dir == expected / "media"
        assert channel._platform_owner_user_id == owner
        if channel_type == "wechat":
            assert channel._context_tokens_file.parent == expected
            assert channel._bot_token_file.parent == expected
        if channel_type == "feishu":
            assert channel._receive_id_store_path().parent == expected
        if channel_type == "dingtalk":
            assert channel._session_webhook_store_path().parent == expected
        managers.append(manager)
    assert managers[0].channels[0]._workspace_dir != managers[1].channels[0]._workspace_dir


@pytest.mark.asyncio
async def test_same_agent_binding_removal_does_not_stop_another_user() -> None:
    """同一智能体同一频道的两份个人绑定独立启停。"""
    runtime = import_module("qwenpaw.app.channels.user_bindings")
    records = [
        SimpleNamespace(id=uuid4(), agent_key="shared-agent", owner_user_id=uuid4(),
                        channel_type="feishu", enabled=True)
        for _ in range(2)
    ]
    managers = []

    def factory(**kwargs):
        manager = FakeManager()
        managers.append(manager)
        return manager

    registry = runtime.UserChannelBindingRuntimeRegistry(
        workspace_manager=SimpleNamespace(get_agent=AsyncMock(return_value=SimpleNamespace(agent_id="shared-agent"))),
        binding_repository=SimpleNamespace(get_runtime_config=AsyncMock(return_value={"enabled": True})),
        manager_factory=factory,
    )
    for record in records:
        await registry.reconcile(record)
    await registry.remove(records[0].id)

    assert managers[0].stopped == 1
    assert managers[1].started == 1
    assert managers[1].stopped == 0
    assert registry._managers == {records[1].id: managers[1]}


@pytest.mark.parametrize("foreign", [False, True])
def test_personal_connector_media_uses_existing_authenticated_preview_scope(
    monkeypatch, tmp_path, foreign,
) -> None:
    """新监听器媒体路径沿用个人工作区预览规则，本人可见、其他用户不可见。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from qwenpaw.app.routers import files

    runtime = import_module("qwenpaw.app.channels.user_bindings")
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    owner = uuid4()
    manager = runtime._build_channel_manager(
        workspace=SimpleNamespace(
            agent_id="shared-agent", workspace_dir=tmp_path / "workspaces/shared-agent",
            stream_query=lambda request: request, _config=SimpleNamespace(language="zh"),
        ),
        binding_repository=SimpleNamespace(upsert_external_identity=AsyncMock()),
        channel_type="wechat", config={"enabled": True},
        owner_user_id=owner, binding_id=uuid4(),
    )
    target = manager.channels[0]._media_dir / "image.png"
    target.write_bytes(b"private-channel-image")
    monkeypatch.setattr(files, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(files, "_ALLOWED_ROOT", tmp_path)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.access.dependencies.get_actor",
        lambda request: SimpleNamespace(user_id=uuid4() if foreign else owner),
    )
    preview_agent = AsyncMock(return_value=SimpleNamespace(agent_id="shared-agent"))
    monkeypatch.setattr("qwenpaw.app.agent_context.get_agent_for_request", preview_agent)
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    response = TestClient(app).get("/api/files/preview/" + target.as_posix())

    assert response.status_code == (403 if foreign else 200)
    if not foreign:
        assert response.content == b"private-channel-image"
        assert preview_agent.await_args.kwargs == {"agent_id": "shared-agent", "recheck_access": True}
    else:
        assert b"private-channel-image" not in response.content
        preview_agent.assert_not_awaited()
