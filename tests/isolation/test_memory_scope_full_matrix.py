# -*- coding: utf-8 -*-
"""Task 4.5-C/1 全角色记忆作用域与生命周期矩阵。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AccessibleAgent
from qwenpaw.access.agent_repository import (
    AgentResourceRole,
    AgentVisibility,
    LegacyAgentRecord,
)
from qwenpaw.app.routers.agents import get_memory_scopes
from qwenpaw.identity.models import PlatformRole
from qwenpaw.memory_scope.models import MemoryIndexState, MemoryScope
from qwenpaw.persistence.agent_user_workspaces import (
    AgentUserWorkspaceRecord,
    AgentUserWorkspaceRepository,
)

USER_ID = UUID("11111111-1111-4111-8111-111111111111")


def _request(*, admin: bool, governance: bool = False):
    actor = ActorContext(
        user_id=USER_ID,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN if admin else PlatformRole.MEMBER,
        admin_mode=False,
        request_id="req-full-memory-matrix",
    )
    headers = {"X-Agent-Governance": "runtime-config"} if governance else {}
    return SimpleNamespace(state=SimpleNamespace(actor=actor), headers=headers)


def _access(role: AgentResourceRole) -> AccessibleAgent:
    return AccessibleAgent(
        agent=LegacyAgentRecord(
            key="agent-a",
            name="Agent A",
            description="",
            workspace_key="workspaces/agent-a",
            status="active",
        ),
        owner_user_id=USER_ID,
        role=role,
        registration_state="registered",
        visibility=AgentVisibility.PUBLIC,
    )


def _private_record() -> AgentUserWorkspaceRecord:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    return AgentUserWorkspaceRecord(
        user_id=USER_ID,
        agent_key="agent-a",
        scope=MemoryScope.PRIVATE,
        workspace_key=f"user_workspaces/{USER_ID}/agent-a",
        status="active",
        index_state=MemoryIndexState.NEEDS_REINDEX,
        index_version=0,
        created_at=now,
        updated_at=now,
        last_accessed_at=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "admin", "governance", "expected"),
    [
        (AgentResourceRole.OWNER, False, False, [("public", True), ("private", True)]),
        (
            AgentResourceRole.COLLABORATOR,
            False,
            False,
            [("public", True), ("private", True)],
        ),
        (AgentResourceRole.USER, False, False, [("public", False), ("private", True)]),
        # 管理员在普通对话路径上仍是普通用户，只处理自己的私有记忆。
        (AgentResourceRole.USER, True, False, [("public", False), ("private", True)]),
        # 只有显式代管路径可以维护公共记忆，且不得暴露管理员私有作用域。
        (AgentResourceRole.USER, True, True, [("public", True)]),
    ],
)
async def test_complete_role_matrix(
    tmp_path: Path,
    role: AgentResourceRole,
    admin: bool,
    governance: bool,
    expected: list[tuple[str, bool]],
) -> None:
    repository = SimpleNamespace(
        ensure_private=AsyncMock(return_value=_private_record())
    )
    with (
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=True),
        patch(
            "qwenpaw.app.routers.agents._require_agent_role",
            new=AsyncMock(return_value=None if governance else _access(role)),
        ),
        patch(
            "qwenpaw.app.routers.agents._get_agent_user_workspace_repository",
            return_value=repository,
        ),
        patch("qwenpaw.app.routers.agents._get_memory_scope_resolver") as factory,
    ):
        from qwenpaw.memory_scope.resolver import MemoryScopeResolver

        factory.return_value = MemoryScopeResolver(working_dir=tmp_path)
        response = await get_memory_scopes(
            "agent-a",
            _request(admin=admin, governance=governance),
        )

    assert [(item.scope.value, item.can_edit) for item in response.scopes] == expected
    if governance:
        repository.ensure_private.assert_not_awaited()
    else:
        repository.ensure_private.assert_awaited_once()


@pytest.mark.asyncio
async def test_unauthorized_user_creates_no_memory_workspace(tmp_path: Path) -> None:
    with (
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=True),
        patch(
            "qwenpaw.app.routers.agents._require_agent_role",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail="forbidden")
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_memory_scopes("agent-a", _request(admin=False))

    assert exc.value.status_code == 403
    assert not (tmp_path / "workspaces").exists()
    assert not (tmp_path / "user_workspaces").exists()


class _Result:
    @staticmethod
    def rowcount() -> int:
        return 2


class _Session:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return SimpleNamespace(rowcount=2)


@pytest.mark.asyncio
async def test_agent_cleanup_marks_private_metadata_without_deleting_files() -> None:
    session = _Session()

    @asynccontextmanager
    async def factory():
        yield session

    repository = AgentUserWorkspaceRepository(
        schema="qwenpaw_test",
        session_factory=factory,
    )

    updated = await repository.mark_agent_cleanup_pending(agent_key="agent-a")

    assert updated == 2
    sql, params = session.calls[0]
    assert "status = 'cleanup_pending'" in sql
    assert "DELETE" not in sql.upper()
    assert "user_id" not in params
    assert params["agent_id"] is not None
