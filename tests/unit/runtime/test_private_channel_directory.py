"""Only server-bound channel identities may select private task directories."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.schemas import AgentRequest


def test_client_cannot_inject_trusted_channel_identity():
    request = AgentRequest.model_validate({"_trusted_channel_user_id": str(uuid4())})
    assert request._trusted_channel_user_id is None


@pytest.mark.asyncio
async def test_bound_channel_uses_verified_conversation_directory(monkeypatch, tmp_path):
    user_id, conversation_id = uuid4(), uuid4()
    request = AgentRequest(user_id="external-id")
    request._trusted_channel_user_id = user_id
    ctx = SimpleNamespace(
        request=request, agent_id="qa",
        workspace=SimpleNamespace(chat_manager=SimpleNamespace(conversation_repository=object())),
    )
    context = {"conversation_id": str(conversation_id), "project_dir": str(tmp_path), "user_id": "forged"}
    check = AsyncMock()
    monkeypatch.setattr("qwenpaw.app.chats.access.require_conversation_access", check)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.services.workspace_files.WORKING_DIR", tmp_path)
    await AgentBuilder._bind_private_channel_task(ctx, context)
    expected = tmp_path / "user_workspaces" / str(user_id) / "qa" / "artifacts" / str(conversation_id)
    assert context["project_dir"] == str(expected)
    assert context["task_output_dir"] == str(expected)
    assert context["user_id"] == str(user_id)
    assert check.await_args.kwargs["write"] is True


@pytest.mark.asyncio
async def test_channel_cannot_select_other_users_conversation(monkeypatch, tmp_path):
    from qwenpaw.app.chats.access import ChatAccessDeniedError

    request = AgentRequest()
    request._trusted_channel_user_id = uuid4()
    ctx = SimpleNamespace(request=request, agent_id="qa", workspace=None)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.services.workspace_files.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        "qwenpaw.app.chats.access.require_conversation_access",
        AsyncMock(side_effect=ChatAccessDeniedError()),
    )
    with pytest.raises(ChatAccessDeniedError):
        await AgentBuilder._bind_private_channel_task(ctx, {"conversation_id": str(uuid4())})
    assert not (tmp_path / "user_workspaces").exists()
