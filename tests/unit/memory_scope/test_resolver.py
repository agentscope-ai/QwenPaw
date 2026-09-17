# -*- coding: utf-8 -*-
"""记忆公共/私有作用域与受控目录解析契约。"""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole
from qwenpaw.memory_scope.models import MemoryScope, MemoryScopeDenied
from qwenpaw.memory_scope.resolver import MemoryScopeResolver


def _actor(user_id: UUID | None = None) -> ActorContext:
    return ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="req-memory-scope",
    )


def test_private_workspaces_are_isolated_by_user_and_agent(tmp_path: Path) -> None:
    user_a = uuid4()
    user_b = uuid4()
    resolver = MemoryScopeResolver(working_dir=tmp_path)

    context_a = resolver.resolve_private(
        actor=_actor(user_a),
        agent_id="shared-agent",
        session_id="session-a",
        run_id="run-a",
    )
    context_b = resolver.resolve_private(
        actor=_actor(user_b),
        agent_id="shared-agent",
        session_id="session-b",
        run_id="run-b",
    )

    assert context_a.scope is MemoryScope.PRIVATE
    assert context_a.actor_user_id == user_a
    assert context_a.session_id == "session-a"
    assert resolver.workspace_path(context_a) == (
        tmp_path / "user_workspaces" / str(user_a) / "shared-agent"
    )
    assert resolver.workspace_path(context_a) != resolver.workspace_path(
        context_b
    )


def test_public_workspace_uses_existing_agent_workspace(tmp_path: Path) -> None:
    resolver = MemoryScopeResolver(working_dir=tmp_path)

    context = resolver.resolve_public(
        actor=_actor(uuid4()),
        agent_id="public-agent",
        governance=True,
    )

    assert context.scope is MemoryScope.PUBLIC
    assert context.governance is True
    assert resolver.workspace_path(context) == (
        tmp_path / "workspaces" / "public-agent"
    )


def test_private_scope_requires_authenticated_user(tmp_path: Path) -> None:
    resolver = MemoryScopeResolver(working_dir=tmp_path)

    with pytest.raises(MemoryScopeDenied, match="authenticated_user_required"):
        resolver.resolve_private(actor=_actor(None), agent_id="agent-a")


@pytest.mark.parametrize(
    "agent_id",
    ["", "../escape", "a/b", "a\\b", ".", ".."],
)
def test_scope_rejects_unsafe_agent_id(tmp_path: Path, agent_id: str) -> None:
    resolver = MemoryScopeResolver(working_dir=tmp_path)

    with pytest.raises(MemoryScopeDenied, match="invalid_agent_id"):
        resolver.resolve_private(actor=_actor(uuid4()), agent_id=agent_id)
