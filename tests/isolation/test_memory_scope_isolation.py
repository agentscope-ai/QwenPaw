# -*- coding: utf-8 -*-
"""记忆运行空间的文件系统隔离边界。"""

from pathlib import Path
from uuid import UUID

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole
from qwenpaw.memory_scope.resolver import MemoryScopeResolver


def _actor(user_id: UUID) -> ActorContext:
    return ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="req-memory-isolation",
    )


def test_same_agent_private_directories_do_not_share_files(tmp_path: Path) -> None:
    user_a = UUID("11111111-1111-4111-8111-111111111111")
    user_b = UUID("22222222-2222-4222-8222-222222222222")
    resolver = MemoryScopeResolver(working_dir=tmp_path)
    path_a = resolver.workspace_path(
        resolver.resolve_private(actor=_actor(user_a), agent_id="agent-a")
    )
    path_b = resolver.workspace_path(
        resolver.resolve_private(actor=_actor(user_b), agent_id="agent-a")
    )

    path_a.mkdir(parents=True)
    path_b.mkdir(parents=True)
    (path_a / "MEMORY.md").write_text("user-a-secret", encoding="utf-8")
    (path_b / "MEMORY.md").write_text("user-b-secret", encoding="utf-8")

    assert (path_a / "MEMORY.md").read_text(encoding="utf-8") == ("user-a-secret")
    assert (path_b / "MEMORY.md").read_text(encoding="utf-8") == ("user-b-secret")
    assert path_a.parent != path_b.parent


def test_public_directory_is_separate_from_every_private_directory(
    tmp_path: Path,
) -> None:
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    resolver = MemoryScopeResolver(working_dir=tmp_path)
    public_path = resolver.workspace_path(
        resolver.resolve_public(actor=_actor(user_id), agent_id="agent-a")
    )
    private_path = resolver.workspace_path(
        resolver.resolve_private(actor=_actor(user_id), agent_id="agent-a")
    )

    assert public_path == tmp_path / "workspaces" / "agent-a"
    assert private_path == (tmp_path / "user_workspaces" / str(user_id) / "agent-a")
    assert public_path != private_path
