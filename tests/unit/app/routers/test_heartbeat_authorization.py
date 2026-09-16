# -*- coding: utf-8 -*-
"""Heartbeat 配置路由必须使用可信请求主体授权。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.dependencies import get_actor
from qwenpaw.app.routers.config import router
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.identity.models import PlatformRole


def test_put_heartbeat_saves_authenticated_user_not_client_value() -> None:
    actor_user_id = uuid4()
    forged_user_id = uuid4()
    workspace = SimpleNamespace(
        agent_id="shared-agent",
        config=AgentProfileConfig(id="shared-agent", name="Shared Agent"),
        cron_manager=None,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_actor] = lambda: ActorContext(
        user_id=actor_user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="request-1",
    )

    with (
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            new=AsyncMock(return_value=workspace),
        ),
        patch("qwenpaw.app.routers.config.is_multi_user_enabled", return_value=True),
        patch("qwenpaw.config.config.save_agent_config") as save_config,
    ):
        response = TestClient(app).put(
            "/api/config/heartbeat",
            json={
                "enabled": True,
                "target": "inbox",
                "authorizedByUserId": str(forged_user_id),
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["authorizedByUserId"] == str(actor_user_id)
    assert workspace.config.heartbeat.authorized_by_user_id == str(actor_user_id)
    save_config.assert_called_once_with("shared-agent", workspace.config)
