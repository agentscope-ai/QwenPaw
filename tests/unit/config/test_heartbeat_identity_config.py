# -*- coding: utf-8 -*-
"""Heartbeat 授权用户和最近目标配置契约。"""

from __future__ import annotations

from uuid import uuid4

from qwenpaw.config.config import AgentProfileConfig, HeartbeatConfig


def test_heartbeat_authorized_user_round_trips_with_alias() -> None:
    user_id = uuid4()

    config = HeartbeatConfig.model_validate(
        {"enabled": True, "authorizedByUserId": str(user_id)}
    )

    assert config.authorized_by_user_id == str(user_id)
    assert config.model_dump(mode="json", by_alias=True)[
        "authorizedByUserId"
    ] == str(user_id)


def test_agent_profile_keeps_last_dispatches_separate_by_platform_user() -> None:
    user_a = str(uuid4())
    user_b = str(uuid4())
    profile = AgentProfileConfig.model_validate(
        {
            "id": "shared-agent",
            "name": "Shared Agent",
            "last_dispatch": {
                "channel": "legacy",
                "user_id": "legacy-user",
                "session_id": "legacy-session",
            },
            "last_dispatch_by_user": {
                user_a: {
                    "channel": "console",
                    "user_id": user_a,
                    "session_id": "session-a",
                },
                user_b: {
                    "channel": "telegram",
                    "user_id": "external-b",
                    "session_id": "session-b",
                },
            },
        }
    )

    assert profile.last_dispatch_by_user[user_a].session_id == "session-a"
    assert profile.last_dispatch_by_user[user_b].session_id == "session-b"
    assert profile.last_dispatch.session_id == "legacy-session"
