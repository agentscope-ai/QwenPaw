# -*- coding: utf-8 -*-
"""Heartbeat 后台主体与目标的多用户隔离契约。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qwenpaw.app.crons import heartbeat
from qwenpaw.app.crons import manager as cron_manager
from qwenpaw.config.config import HeartbeatConfig, LastDispatchConfig
from qwenpaw.constant import HEARTBEAT_FILE


def test_build_identity_uses_authorized_user_and_dedicated_session() -> None:
    user_id = uuid4()

    identity = heartbeat.build_heartbeat_run_identity(
        agent_id="shared-agent",
        authorized_user_id=user_id,
    )

    assert identity.authorized_user_id == user_id
    assert identity.session_id == f"heartbeat:shared-agent:{user_id}:main"
    assert identity.request_context == {
        "source": "heartbeat",
        "actor_type": "automation",
        "automation_kind": "agent_automation",
        "authorized_by_user_id": str(user_id),
        "agent_id": "shared-agent",
        "actor_context": {
            "user_id": str(user_id),
            "actor_type": "automation",
            "admin_mode": False,
        },
    }


def test_multi_user_scheduler_requires_authorized_heartbeat(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.identity.runtime.is_multi_user_enabled",
        lambda: True,
    )

    assert not cron_manager.heartbeat_can_schedule(
        HeartbeatConfig(enabled=True)
    )
    assert cron_manager.heartbeat_can_schedule(
        HeartbeatConfig(enabled=True, authorizedByUserId=uuid4())
    )


@pytest.mark.asyncio
async def test_multi_user_run_requires_saved_authorization(
    monkeypatch,
    tmp_path,
) -> None:
    (tmp_path / HEARTBEAT_FILE).write_text("check", encoding="utf-8")
    monkeypatch.setattr(heartbeat, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        heartbeat,
        "get_heartbeat_config",
        lambda _agent_id: HeartbeatConfig(enabled=True),
    )

    with pytest.raises(
        heartbeat.HeartbeatIdentityError,
        match="heartbeat_authorization_required",
    ):
        await heartbeat.run_heartbeat_once(
            workspace=SimpleNamespace(stream_query=AsyncMock()),
            channel_manager=SimpleNamespace(),
            agent_id="shared-agent",
            workspace_dir=tmp_path,
        )


@pytest.mark.asyncio
async def test_last_uses_only_authorized_users_target(monkeypatch, tmp_path) -> None:
    user_a = uuid4()
    user_b = uuid4()
    (tmp_path / HEARTBEAT_FILE).write_text("check", encoding="utf-8")
    requests = []

    class Workspace:
        async def stream_query(self, request):
            requests.append(request)
            yield {"type": "done"}

    send_event = AsyncMock()
    monkeypatch.setattr(heartbeat, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        heartbeat,
        "get_heartbeat_config",
        lambda _agent_id: HeartbeatConfig(
            enabled=True,
            target="last",
            authorizedByUserId=user_a,
        ),
    )
    monkeypatch.setattr(
        heartbeat,
        "validate_heartbeat_authorization",
        AsyncMock(),
    )
    monkeypatch.setattr(
        heartbeat,
        "validate_heartbeat_last_target",
        AsyncMock(return_value=True),
    )
    targets = {
        str(user_a): LastDispatchConfig(
            channel="console",
            user_id=str(user_a),
            session_id="session-a",
        ),
        str(user_b): LastDispatchConfig(
            channel="console",
            user_id=str(user_b),
            session_id="session-b",
        ),
    }
    monkeypatch.setattr(
        heartbeat,
        "get_last_dispatch_for_user",
        lambda *, agent_id, platform_user_id: targets.get(platform_user_id),
    )

    await heartbeat.run_heartbeat_once(
        workspace=Workspace(),
        channel_manager=SimpleNamespace(send_event=send_event),
        agent_id="shared-agent",
        workspace_dir=tmp_path,
    )

    assert requests[0]["user_id"] == str(user_a)
    assert requests[0]["session_id"] == (
        f"heartbeat:shared-agent:{user_a}:main"
    )
    assert requests[0]["request_context"]["automation_kind"] == (
        "agent_automation"
    )
    assert send_event.await_args.kwargs["session_id"] == "session-a"
    assert send_event.await_args.kwargs["user_id"] == str(user_a)


@pytest.mark.asyncio
async def test_last_without_own_target_notifies_authorized_user(
    monkeypatch,
    tmp_path,
) -> None:
    user_id = uuid4()
    (tmp_path / HEARTBEAT_FILE).write_text("check", encoding="utf-8")
    append_event = AsyncMock()
    stream_query = AsyncMock()
    monkeypatch.setattr(heartbeat, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        heartbeat,
        "get_heartbeat_config",
        lambda _agent_id: HeartbeatConfig(
            enabled=True,
            target="last",
            authorizedByUserId=user_id,
        ),
    )
    monkeypatch.setattr(
        heartbeat,
        "validate_heartbeat_authorization",
        AsyncMock(),
    )
    monkeypatch.setattr(
        heartbeat,
        "get_last_dispatch_for_user",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(heartbeat, "append_inbox_event", append_event)

    await heartbeat.run_heartbeat_once(
        workspace=SimpleNamespace(stream_query=stream_query),
        channel_manager=SimpleNamespace(send_event=AsyncMock()),
        agent_id="shared-agent",
        workspace_dir=tmp_path,
    )

    stream_query.assert_not_awaited()
    assert append_event.await_args.kwargs["recipient_user_id"] == str(user_id)
    assert append_event.await_args.kwargs["event_type"] == (
        "heartbeat_last_target_unavailable"
    )
