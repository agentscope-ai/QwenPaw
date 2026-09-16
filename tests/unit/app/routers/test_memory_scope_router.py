# -*- coding: utf-8 -*-
"""记忆作用域安全摘要 API 的角色与数据泄漏契约。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AccessibleAgent
from qwenpaw.access.agent_repository import (
    AgentResourceRole,
    AgentVisibility,
    LegacyAgentRecord,
)
from qwenpaw.identity.models import PlatformRole
from qwenpaw.memory_scope.models import MemoryIndexState, MemoryScope
from qwenpaw.persistence.agent_user_workspaces import AgentUserWorkspaceRecord
from qwenpaw.app.routers.agents import (
    get_memory_scopes,
    rebuild_agent_memory_index,
)

USER_ID = UUID("11111111-1111-4111-8111-111111111111")


def _request(*, governance: bool = False):
    actor = ActorContext(
        user_id=USER_ID,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="req-memory-scopes",
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
        visibility=AgentVisibility.PRIVATE,
    )


def _private_record() -> AgentUserWorkspaceRecord:
    from datetime import UTC, datetime

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
    ("role", "public_can_edit"),
    [
        (AgentResourceRole.OWNER, True),
        (AgentResourceRole.COLLABORATOR, True),
        (AgentResourceRole.USER, False),
    ],
)
async def test_memory_scopes_return_public_and_current_users_private_only(
    tmp_path: Path,
    role: AgentResourceRole,
    public_can_edit: bool,
) -> None:
    repository = SimpleNamespace(
        ensure_private=AsyncMock(return_value=_private_record())
    )
    with (
        patch(
            "qwenpaw.app.routers.agents.is_multi_user_enabled",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.routers.agents._require_agent_role",
            new=AsyncMock(return_value=_access(role)),
        ),
        patch(
            "qwenpaw.app.routers.agents._get_agent_user_workspace_repository",
            return_value=repository,
        ),
        patch(
            "qwenpaw.app.routers.agents._get_memory_scope_resolver"
        ) as resolver_factory,
    ):
        from qwenpaw.memory_scope.resolver import MemoryScopeResolver

        resolver_factory.return_value = MemoryScopeResolver(working_dir=tmp_path)
        response = await get_memory_scopes("agent-a", _request())

    assert [item.scope for item in response.scopes] == [
        MemoryScope.PUBLIC,
        MemoryScope.PRIVATE,
    ]
    assert response.scopes[0].can_edit is public_can_edit
    assert response.scopes[1].can_edit is True
    assert not hasattr(response.scopes[1], "workspace_path")
    assert not hasattr(response.scopes[1], "user_id")
    repository.ensure_private.assert_awaited_once()
    assert (tmp_path / "user_workspaces" / str(USER_ID) / "agent-a").is_dir()


@pytest.mark.asyncio
async def test_governance_admin_never_receives_another_users_private_scope(
    tmp_path: Path,
) -> None:
    repository = SimpleNamespace(ensure_private=AsyncMock())
    with (
        patch(
            "qwenpaw.app.routers.agents.is_multi_user_enabled",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.routers.agents._require_agent_role",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "qwenpaw.app.routers.agents._get_agent_user_workspace_repository",
            return_value=repository,
        ),
    ):
        response = await get_memory_scopes(
            "agent-a",
            _request(governance=True),
        )

    assert [item.scope for item in response.scopes] == [MemoryScope.PUBLIC]
    assert response.scopes[0].can_edit is True
    repository.ensure_private.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_reindex_uses_current_users_runtime() -> None:
    private_runtime = SimpleNamespace(
        rebuild_index=AsyncMock(
            return_value=SimpleNamespace(success=True, answer="ok"),
        ),
    )
    memory_manager = SimpleNamespace(
        get_private_runtime=AsyncMock(return_value=private_runtime),
    )
    workspace = SimpleNamespace(memory_manager=memory_manager)
    manager = SimpleNamespace(get_agent=AsyncMock(return_value=workspace))
    repository = SimpleNamespace(
        ensure_private=AsyncMock(return_value=_private_record()),
        update_index_state=AsyncMock(return_value=_private_record()),
    )
    config = SimpleNamespace(
        agents=SimpleNamespace(profiles={"agent-a": SimpleNamespace()}),
    )
    agent_config = SimpleNamespace(
        running=SimpleNamespace(memory_manager_backend="remelight"),
    )
    request = _request()
    request.app = SimpleNamespace(
        state=SimpleNamespace(multi_agent_manager=manager),
    )

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            "qwenpaw.app.routers.agents._require_agent_role",
            new=AsyncMock(return_value=_access(AgentResourceRole.USER)),
        ),
        patch(
            "qwenpaw.app.routers.agents._get_agent_user_workspace_repository",
            return_value=repository,
        ),
    ):
        response = await rebuild_agent_memory_index(
            "agent-a",
            request,
            scope=MemoryScope.PRIVATE,
        )

    assert response == {"status": "completed"}
    memory_manager.get_private_runtime.assert_awaited_once_with(USER_ID)
    private_runtime.rebuild_index.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_reindex_failure_is_persisted() -> None:
    private_runtime = SimpleNamespace(
        rebuild_index=AsyncMock(return_value=None),
    )
    memory_manager = SimpleNamespace(
        get_private_runtime=AsyncMock(return_value=private_runtime),
    )
    manager = SimpleNamespace(
        get_agent=AsyncMock(
            return_value=SimpleNamespace(memory_manager=memory_manager),
        ),
    )
    repository = SimpleNamespace(
        ensure_private=AsyncMock(return_value=_private_record()),
        update_index_state=AsyncMock(return_value=_private_record()),
    )
    request = _request()
    request.app = SimpleNamespace(
        state=SimpleNamespace(multi_agent_manager=manager),
    )
    config = SimpleNamespace(
        agents=SimpleNamespace(profiles={"agent-a": SimpleNamespace()}),
    )
    agent_config = SimpleNamespace(
        running=SimpleNamespace(memory_manager_backend="remelight"),
    )

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            "qwenpaw.app.routers.agents._require_agent_role",
            new=AsyncMock(return_value=_access(AgentResourceRole.USER)),
        ),
        patch(
            "qwenpaw.app.routers.agents._get_agent_user_workspace_repository",
            return_value=repository,
        ),
    ):
        with pytest.raises(Exception):
            await rebuild_agent_memory_index(
                "agent-a",
                request,
                scope=MemoryScope.PRIVATE,
            )

    assert repository.update_index_state.await_args_list[-1].kwargs[
        "index_state"
    ] is MemoryIndexState.REINDEX_FAILED


@pytest.mark.asyncio
async def test_use_only_user_cannot_reindex_public_memory() -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(profiles={"agent-a": SimpleNamespace()}),
    )
    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch(
            "qwenpaw.app.routers.agents._require_agent_role",
            new=AsyncMock(side_effect=Exception("forbidden")),
        ),
    ):
        with pytest.raises(Exception, match="forbidden"):
            await rebuild_agent_memory_index(
                "agent-a",
                _request(),
                scope=MemoryScope.PUBLIC,
            )
