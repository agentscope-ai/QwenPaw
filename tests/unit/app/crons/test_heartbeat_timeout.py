# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.crons import heartbeat
from qwenpaw.config.config import HeartbeatConfig
from qwenpaw.constant import (
    HEARTBEAT_FILE,
    HEARTBEAT_TARGET_INBOX,
    HEARTBEAT_TARGET_LAST,
)


class _Workspace:
    async def stream_query(self, _req):
        for event in ():
            yield event


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "last_dispatch"),
    [
        ("main", None),
        (
            HEARTBEAT_TARGET_LAST,
            SimpleNamespace(
                channel="console",
                user_id="user-1",
                session_id="session-1",
            ),
        ),
        (HEARTBEAT_TARGET_INBOX, None),
    ],
)
async def test_run_heartbeat_once_uses_configured_timeout(
    monkeypatch,
    tmp_path,
    target,
    last_dispatch,
):
    (tmp_path / HEARTBEAT_FILE).write_text("check status", encoding="utf-8")
    seen_timeouts: list[float] = []

    async def fake_wait_for(awaitable, timeout):
        seen_timeouts.append(timeout)
        return await awaitable

    monkeypatch.setattr(heartbeat.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(
        heartbeat,
        "get_heartbeat_config",
        lambda _agent_id=None: HeartbeatConfig(
            enabled=True,
            target=target,
            timeoutSeconds=240,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(last_dispatch=last_dispatch),
    )
    monkeypatch.setattr(
        heartbeat,
        "read_session_messages",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(heartbeat, "create_trace", AsyncMock())
    monkeypatch.setattr(
        heartbeat,
        "append_trace_from_session_delta",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(heartbeat, "finalize_trace", AsyncMock())
    monkeypatch.setattr(heartbeat, "append_inbox_event", AsyncMock())

    await heartbeat.run_heartbeat_once(
        workspace=_Workspace(),
        channel_manager=SimpleNamespace(send_event=AsyncMock()),
        agent_id="agent-1",
        workspace_dir=tmp_path,
    )

    assert seen_timeouts == [240]


def test_heartbeat_config_supports_timeout_seconds_alias():
    config = HeartbeatConfig(timeoutSeconds=180)

    assert config.timeout_seconds == 180
    assert (
        config.model_dump(mode="json", by_alias=True)["timeoutSeconds"] == 180
    )
    assert HeartbeatConfig().timeout_seconds == 300
