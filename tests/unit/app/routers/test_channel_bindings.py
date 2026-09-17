# -*- coding: utf-8 -*-
"""个人频道绑定 API 契约。"""

from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole


def _actor() -> ActorContext:
    return ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="req-channel-bindings-router",
    )


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def upsert(self, **kwargs):
        self.calls.append(("upsert", kwargs))
        return SimpleNamespace(
            id=uuid4(),
            channel_type=kwargs["channel_type"],
            display_name=kwargs["display_name"],
            enabled=kwargs["enabled"],
            config=kwargs["config"],
            configured_secret_fields=tuple(sorted(kwargs["secrets"])),
        )

    async def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return True

    async def list_bindings(self, **kwargs):
        self.calls.append(("list", kwargs))
        return []

    async def has_bot_conflict(self, **kwargs):
        self.calls.append(("conflict", kwargs))
        return True


class RecordingRuntime:
    def __init__(self) -> None:
        self.reconciled = []
        self.removed = []

    async def reconcile(self, record):
        self.reconciled.append(record)

    async def remove(self, binding_id):
        self.removed.append(binding_id)


@pytest.mark.asyncio
async def test_put_binding_extracts_secrets_and_uses_authenticated_actor() -> None:
    """密钥进入普通 config 或主体来自请求体时，本测试必须失败。"""
    channel_bindings = import_module("qwenpaw.app.routers.channel_bindings")
    actor = _actor()
    service = RecordingService()
    runtime = RecordingRuntime()

    response = await channel_bindings.put_user_channel_binding(
        agentId="public-agent",
        channel_type="telegram",
        body=channel_bindings.ChannelBindingUpsertRequest(
            display_name="我的 Telegram",
            enabled=True,
            config={
                "bot_prefix": "paw",
                "bot_token": "secret-token",
            },
        ),
        actor=actor,
        service=service,
        runtime=runtime,
    )

    assert response.config == {"bot_prefix": "paw"}
    assert response.configured_secret_fields == ["bot_token"]
    assert service.calls == [
        (
            "upsert",
            {
                "actor": actor,
                "agent_key": "public-agent",
                "channel_type": "telegram",
                "display_name": "我的 Telegram",
                "enabled": True,
                "config": {"bot_prefix": "paw"},
                "secrets": {"bot_token": "secret-token"},
            },
        )
    ]
    assert len(runtime.reconciled) == 1
    assert runtime.reconciled[0].channel_type == "telegram"


def test_empty_secret_placeholder_is_not_treated_as_rotation() -> None:
    """编辑时空密码覆盖既有密钥，本测试必须失败。"""
    channel_bindings = import_module("qwenpaw.app.routers.channel_bindings")
    public_config, secrets = channel_bindings.partition_channel_config(
        "slack",
        {
            "bot_token": "",
            "app_token": "new-app-token",
            "bot_prefix": "team",
        },
    )

    assert public_config == {"bot_prefix": "team"}
    assert secrets == {"app_token": "new-app-token"}


@pytest.mark.asyncio
async def test_personal_conflict_check_uses_full_proposed_config() -> None:
    channel_bindings = import_module("qwenpaw.app.routers.channel_bindings")
    actor = _actor()
    service = RecordingService()

    response = await channel_bindings.check_user_channel_binding_conflict(
        request=SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(multi_agent_manager=None)
            )
        ),
        agentId="public-agent",
        channel_type="telegram",
        body=channel_bindings.ChannelBindingConfigRequest(
            config={"bot_token": "secret-token", "bot_prefix": "paw"},
        ),
        actor=actor,
        service=service,
    )

    assert response.conflict is True
    assert service.calls == [
        (
            "conflict",
            {
                "actor": actor,
                "agent_key": "public-agent",
                "channel_type": "telegram",
                "config": {
                    "bot_token": "secret-token",
                    "bot_prefix": "paw",
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_personal_conflict_check_includes_running_agent_channels() -> None:
    """只检查个人绑定而漏掉 Agent 原频道时，本测试必须失败。"""
    channel_bindings = import_module("qwenpaw.app.routers.channel_bindings")
    actor = _actor()
    service = RecordingService()

    async def no_personal_conflict(**kwargs):
        service.calls.append(("conflict", kwargs))
        return False

    service.has_bot_conflict = no_personal_conflict
    workspace = SimpleNamespace(
        config=SimpleNamespace(
            channels=SimpleNamespace(
                telegram=SimpleNamespace(bot_token="same-token")
            )
        ),
        channel_manager=SimpleNamespace(
            channels=[SimpleNamespace(channel="telegram")]
        ),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                multi_agent_manager=SimpleNamespace(
                    agents={"agent-with-running-bot": workspace}
                )
            )
        )
    )

    response = await channel_bindings.check_user_channel_binding_conflict(
        request=request,
        agentId="public-agent",
        channel_type="telegram",
        body=channel_bindings.ChannelBindingConfigRequest(
            config={"bot_token": "same-token"}
        ),
        actor=actor,
        service=service,
    )

    assert response.conflict is True


@pytest.mark.asyncio
async def test_delete_binding_returns_not_found_without_leaking_other_users() -> None:
    """删除不存在的本人绑定返回 404，不能退化为跨用户查询。"""
    channel_bindings = import_module("qwenpaw.app.routers.channel_bindings")
    actor = _actor()
    service = RecordingService()
    runtime = RecordingRuntime()

    async def missing_delete(**kwargs):
        service.calls.append(("delete", kwargs))
        return False

    service.delete = missing_delete
    with pytest.raises(channel_bindings.HTTPException) as exc_info:
        await channel_bindings.delete_user_channel_binding(
            agentId="public-agent",
            channel_type="telegram",
            actor=actor,
            service=service,
            runtime=runtime,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "channel_binding_not_found"
    assert service.calls == [
        (
            "list",
            {
                "actor": actor,
                "agent_key": "public-agent",
            },
        ),
        (
            "delete",
            {
                "actor": actor,
                "agent_key": "public-agent",
                "channel_type": "telegram",
            },
        )
    ]
