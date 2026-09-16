# -*- coding: utf-8 -*-
"""Private task execution is independent of Agent administration rights."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.app.routers import console


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(AgentResourceRole))
async def test_every_role_defaults_to_private_conversation_directory(
    tmp_path, monkeypatch, role,
):
    user_id = UUID("12345678-1234-1234-1234-123456789abc")
    conversation_id = "22345678-1234-1234-1234-123456789abc"
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(console, "get_actor", lambda request: SimpleNamespace(user_id=user_id))
    monkeypatch.setattr(console, "get_agent_access_state", lambda request: (role, False))
    monkeypatch.setattr("qwenpaw.services.workspace_files.WORKING_DIR", tmp_path)
    workspace = SimpleNamespace(agent_id="agent-a", workspace_dir=tmp_path / "shared")

    path, source = await console._resolve_console_runtime_project(
        object(), workspace, project_dir=workspace.workspace_dir,
        project_source="agent", conversation_id=conversation_id,
    )

    assert path == tmp_path / "user_workspaces" / str(user_id) / "agent-a" / "artifacts" / conversation_id
    assert path.is_dir()
    assert source == "user_task"


def test_task_directory_rejects_conversation_path_injection(tmp_path):
    from qwenpaw.services.workspace_files import resolve_private_task_directory

    with pytest.raises(ValueError):
        resolve_private_task_directory(
            actor_user_id=UUID("12345678-1234-1234-1234-123456789abc"),
            agent_id="agent-a", conversation_id="../other", working_dir=tmp_path,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("outside", [False, True])
async def test_explicit_project_is_bounded_by_authorized_root(tmp_path, monkeypatch, outside):
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(console, "get_agent_access_state", lambda request: (AgentResourceRole.OWNER, False))
    allowed = tmp_path / "authorized"
    selected = tmp_path / "other-user" if outside else allowed / "src"
    selected.mkdir(parents=True)
    call = console._resolve_console_runtime_project(
        object(), SimpleNamespace(workspace_dir=allowed),
        project_dir=selected, project_source="session",
        authorized_project_dir=allowed,
        conversation_id="22345678-1234-1234-1234-123456789abc",
    )
    if outside:
        with pytest.raises(console.HTTPException) as error:
            await call
        assert error.value.status_code == 403
    else:
        assert await call == (selected, "session")
