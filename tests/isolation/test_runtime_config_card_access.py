# -*- coding: utf-8 -*-
"""Task 4.5-B/6：运行配置卡片的角色和副作用隔离。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.access.agent_repository import AgentResourceRole, AgentVisibility
from qwenpaw.app.routers.workspace import (
    RunningConfigAccess,
    _runtime_config_access,
    put_agents_running_config,
)
from qwenpaw.config import AgentsRunningConfig


@pytest.mark.parametrize(
    ("role", "can_edit"),
    [
        (AgentResourceRole.OWNER, True),
        (AgentResourceRole.COLLABORATOR, True),
        (AgentResourceRole.USER, False),
    ],
)
def test_runtime_card_role_matrix(role, can_edit) -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=role,
                visibility=AgentVisibility.PUBLIC,
                owner_user_id="owner-1",
                historical_read_only=False,
            ),
        ),
    )

    access = _runtime_config_access(request, "shared-agent")

    assert access == RunningConfigAccess(
        agent_id="shared-agent",
        access_role=role.value,
        can_view=True,
        can_edit=can_edit,
        can_edit_project_files=True,
        can_edit_workspace_files=can_edit,
        visibility=AgentVisibility.PUBLIC,
        owner_user_id="owner-1",
    )


def test_admin_governance_is_explicit_and_editable() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_governance=SimpleNamespace(
                agent_key="managed-agent",
                owner_user_id="owner-2",
                visibility=AgentVisibility.PRIVATE,
            ),
        ),
    )

    access = _runtime_config_access(request, "managed-agent")

    assert access.access_role == "admin_governance"
    assert access.is_governance is True
    assert access.can_edit is True


@pytest.mark.asyncio
async def test_read_only_runtime_config_cannot_persist_or_reload() -> None:
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=AgentResourceRole.USER,
                visibility=AgentVisibility.PUBLIC,
            ),
        ),
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(side_effect=AssertionError("resolved too early")),
        ) as resolve,
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
        ) as persist,
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
            new_callable=AsyncMock,
        ) as reload,
    ):
        with pytest.raises(HTTPException) as error:
            await put_agents_running_config(
                AgentsRunningConfig(),
                request,
                MagicMock(),
            )

    assert error.value.status_code == 403
    resolve.assert_not_awaited()
    persist.assert_not_called()
    reload.assert_not_awaited()


def test_historical_read_only_owner_cannot_edit() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=AgentResourceRole.OWNER,
                historical_read_only=True,
            ),
        ),
    )

    access = _runtime_config_access(request, "archived-agent")

    assert access.can_view is True
    assert access.can_edit is False


def test_administrator_ordinary_path_does_not_gain_governance() -> None:
    """平台管理员只有显式代管时才获得治理写权限。"""
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=AgentResourceRole.USER,
                visibility=AgentVisibility.PUBLIC,
                historical_read_only=False,
            ),
        ),
    )

    access = _runtime_config_access(request, "someone-elses-agent")

    assert access.access_role == "user"
    assert access.is_governance is False
    assert access.can_edit is False
