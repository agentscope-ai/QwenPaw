"""Conversation file previews must use the runtime's authorized task root."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.app import agent_context
from qwenpaw.access.agent_repository import AgentResourceRole, agent_database_id


@pytest.fixture
def context(tmp_path, monkeypatch):
    user = UUID("33333333-3333-4333-8333-333333333333")
    chat = UUID("44444444-4444-4444-8444-444444444444")
    request = Request({"type": "http", "headers": [(b"x-chat-id", str(chat).encode())]})
    request.state.agent_access = SimpleNamespace(role=AgentResourceRole.OWNER, historical_read_only=False)
    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_context, "get_actor", lambda _: SimpleNamespace(user_id=user))
    monkeypatch.setattr("qwenpaw.services.workspace_files.WORKING_DIR", tmp_path)
    monkeypatch.setattr("qwenpaw.config.config.load_agent_config", lambda _: SimpleNamespace(project_dir=None))
    access = SimpleNamespace(
        conversation=SimpleNamespace(
            id=chat,
            owner_user_id=user,
            agent_id=agent_database_id("files-agent"),
            shared_app_id=None,
            publication_id=None,
        ),
        read_only=False,
    )
    spec = SimpleNamespace(id=str(chat), meta={})
    conversation_lookup = AsyncMock(return_value=access.conversation)
    repository = SimpleNamespace(
        with_user=lambda _: SimpleNamespace(
            get_conversation=conversation_lookup,
        ),
    )
    workspace = SimpleNamespace(agent_id="files-agent", workspace_dir=tmp_path / "shared", chat_manager=SimpleNamespace(get_chat=AsyncMock(return_value=spec), conversation_repository=repository))
    expected = tmp_path / "user_workspaces" / str(user) / "files-agent" / "artifacts" / str(chat)
    return request, workspace, spec, conversation_lookup, expected


@pytest.mark.asyncio
async def test_normal_chat_preview_uses_private_task(context):
    request, workspace, _, conversation_lookup, expected = context
    assert await agent_context.get_project_dir_for_request(request, workspace) == expected
    conversation_lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_session_project_is_preserved(context, tmp_path):
    request, workspace, spec, _, _ = context
    spec.meta = {"runtime_context": {"project_dir": str(tmp_path)}}
    assert await agent_context.get_project_dir_for_request(request, workspace) == tmp_path


@pytest.mark.asyncio
async def test_use_only_role_ignores_session_project(context, tmp_path):
    request, workspace, spec, _, expected = context
    request.state.agent_access.role = AgentResourceRole.USER
    spec.meta = {"runtime_context": {"project_dir": str(tmp_path)}}
    assert await agent_context.get_project_dir_for_request(request, workspace) == expected


@pytest.mark.asyncio
async def test_foreign_conversation_fails_closed(context):
    request, workspace, _, conversation_lookup, _ = context
    conversation_lookup.return_value = None
    with pytest.raises(HTTPException) as error:
        await agent_context.get_project_dir_for_request(request, workspace)
    assert error.value.status_code == 404
