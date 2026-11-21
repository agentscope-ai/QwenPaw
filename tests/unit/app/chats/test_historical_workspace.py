"""本人历史读取不依赖 Agent runtime，且不能借此读取他人或继续写入。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AgentAccessDeniedError
from qwenpaw.access.agent_repository import LegacyAgentRecord, agent_database_id
from qwenpaw.app import agent_context
from qwenpaw.app.chats.historical_workspace import (
    OwnerHistoryRepository,
    create_historical_workspace,
)
from qwenpaw.app.chats.repo.conversation import (
    ConversationAccessRecord,
    ConversationRecord,
)
from qwenpaw.app.routers import agent_scoped
from qwenpaw.identity.models import PlatformRole


def _request(path, *, method="GET", agent="old-agent"):
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [(b"x-agent-id", agent.encode())],
            "scheme": "http",
            "server": ("test", 80),
            "app": FastAPI(),
        }
    )
    request.state.actor = ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="history",
    )
    request.app.state.multi_agent_manager = SimpleNamespace(get_agent=AsyncMock())
    return request


@pytest.mark.parametrize(
    "path",
    [
        "/api/chats",
        "/api/chats/page",
        "/api/chats/id",
        "/api/chats/id/spec",
        "/api/chats/id/status",
        "/api/chats/id/summary",
        "/api/agents/old-agent/chats/id/messages/m/tool-output",
    ],
)
def test_history_whitelist(path):
    assert agent_context.allows_historical_chat_read(_request(path), "old-agent")


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/chats/id/project-dir", "GET"),
        ("/api/chats/id/members", "GET"),
        ("/api/chats/id/share-candidates", "GET"),
        ("/api/chats/id", "DELETE"),
        ("/api/chats", "POST"),
        ("/api/chats/id", "OPTIONS"),
        ("/api/agents/old-agent/config", "GET"),
        ("/api/chats-evil", "GET"),
    ],
)
def test_runtime_configuration_and_writes_are_not_history(path, method):
    assert not agent_context.allows_historical_chat_read(
        _request(path, method=method),
        "old-agent",
    )


@pytest.mark.asyncio
async def test_disabled_agent_history_is_lightweight_and_cached(monkeypatch, tmp_path):
    request = _request("/api/agents/old-agent/chats/id")
    request.state.agent_id = "old-agent"
    profile = SimpleNamespace(enabled=False, workspace_dir=str(tmp_path))
    config = SimpleNamespace(agents=SimpleNamespace(profiles={"old-agent": profile}))
    membership = SimpleNamespace(
        require_historical_read=AsyncMock(
            return_value=SimpleNamespace(historical_read_only=True)
        )
    )
    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_context, "load_config", lambda: config)
    monkeypatch.setattr(
        agent_context, "_get_agent_membership_service", lambda: membership
    )
    workspace = await agent_context.get_agent_for_request(request)
    assert await agent_context.get_agent_for_request(request) is workspace
    assert workspace.agent_id == "old-agent"
    assert workspace.chat_manager.conversation_repository is not None
    request.app.state.multi_agent_manager.get_agent.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []
    assert await workspace.task_tracker.get_status("id") == "idle"
    assert (
        await workspace.session.get_session_state_dict("old-session", "user", "console")
        == {}
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_disabled_owner_cannot_continue_or_read_config(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        agent_context,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={
                    "old-agent": SimpleNamespace(
                        enabled=False,
                        workspace_dir=str(tmp_path),
                    )
                }
            ),
        ),
    )
    for path, method in (
        ("/api/agents/old-agent/console/chat", "POST"),
        ("/api/agents/old-agent/chats/id/project-dir", "GET"),
    ):
        request = _request(path, method=method)
        with pytest.raises(HTTPException) as denied:
            await agent_context.get_agent_for_request(request)
        assert denied.value.status_code == 403
        request.app.state.multi_agent_manager.get_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_profile_and_wrong_header_recover_only_owned_chat(
    monkeypatch, tmp_path
):
    from qwenpaw.access import agent_repository

    root = tmp_path / "old-agent"
    root.mkdir()
    owned = LegacyAgentRecord(
        key="old-agent",
        name="Old",
        description="",
        workspace_key=str(root),
        status="deleted",
    )
    resolver = AsyncMock(return_value=owned)
    monkeypatch.setattr(
        agent_repository.PostgresAgentRepository, "get_owned_history_agent", resolver
    )
    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        agent_context,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(profiles={}),
        ),
    )
    monkeypatch.setattr(
        agent_context,
        "_get_agent_membership_service",
        lambda: SimpleNamespace(
            require_historical_read=AsyncMock(
                return_value=SimpleNamespace(historical_read_only=True)
            ),
        ),
    )
    request = _request(f"/api/chats/{uuid4()}", agent="unrelated-agent")
    workspace = await agent_context.get_agent_for_request(request)
    assert workspace.agent_id == "old-agent"
    request.app.state.multi_agent_manager.get_agent.assert_not_awaited()
    assert resolver.await_args.kwargs["user_id"] == request.state.actor.user_id

    # Explicit Agent-scoped routes may never resolve another Agent's chat.
    request = _request(
        f"/api/agents/unrelated-agent/chats/{uuid4()}", agent="unrelated-agent"
    )
    with pytest.raises(HTTPException) as denied:
        await agent_context.get_agent_for_request(request)
    assert denied.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["live", "disabled", "deleted", "revoked"])
async def test_wrong_agent_header_preserves_current_runtime_eligibility(
    monkeypatch,
    tmp_path,
    state,
):
    from qwenpaw.access import agent_repository

    status = "deleted" if state == "deleted" else "active"
    record = LegacyAgentRecord(
        key="old-agent",
        name="Old",
        description="",
        workspace_key=str(tmp_path),
        status=status,
    )
    monkeypatch.setattr(
        agent_repository.PostgresAgentRepository,
        "get_owned_history_agent",
        AsyncMock(return_value=record),
    )
    profile = SimpleNamespace(enabled=state != "disabled", workspace_dir=str(tmp_path))
    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        agent_context,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(profiles={"old-agent": profile}),
        ),
    )
    access = SimpleNamespace(agent=record, historical_read_only=state != "live")
    membership = SimpleNamespace(
        require_role=AsyncMock(return_value=access),
        require_historical_read=AsyncMock(return_value=access),
    )
    monkeypatch.setattr(
        agent_context, "_get_agent_membership_service", lambda: membership
    )
    request = _request(f"/api/chats/{uuid4()}/spec", agent="another-agent")
    live_workspace = SimpleNamespace(agent_id="old-agent")
    request.app.state.multi_agent_manager.get_agent.return_value = live_workspace
    workspace = await agent_context.get_agent_for_request(request)
    assert workspace.agent_id == "old-agent"
    assert request.state.agent_access.historical_read_only is (state != "live")
    if state == "live":
        assert workspace is live_workspace
        membership.require_role.assert_awaited_once()
        membership.require_historical_read.assert_not_awaited()
        request.app.state.multi_agent_manager.get_agent.assert_awaited_once_with(
            "old-agent"
        )
    else:
        request.app.state.multi_agent_manager.get_agent.assert_not_awaited()


def _access(user_id, agent_id):
    now = datetime.now(UTC)
    return ConversationAccessRecord(
        conversation=ConversationRecord(
            id=uuid4(),
            agent_id=agent_id,
            owner_user_id=user_id,
            title="History",
            status="active",
            created_at=now,
            updated_at=now,
        ),
        access_role="owner",
    )


@pytest.mark.asyncio
async def test_owner_history_repository_rejects_viewers_cross_agent_and_writes():
    user, agent = uuid4(), uuid4()
    bound = SimpleNamespace(
        get_conversation_for_user=AsyncMock(), list_messages=AsyncMock()
    )
    repository = OwnerHistoryRepository(
        SimpleNamespace(with_user=lambda _: bound), user_id=user, agent_id=agent
    )
    access = _access(user, agent)
    bound.get_conversation_for_user.return_value = access
    result = await repository.get_conversation_for_user(
        conversation_id=access.conversation.id, user_id=user
    )
    assert result.access_role == "owner" and result.read_only
    assert not hasattr(repository, "create_message")
    assert not hasattr(repository, "update_conversation")
    for wrong in (_access(uuid4(), agent), _access(user, uuid4())):
        bound.get_conversation_for_user.return_value = wrong
        assert (
            await repository.get_conversation_for_user(
                conversation_id=wrong.conversation.id, user_id=user
            )
            is None
        )
        with pytest.raises(RuntimeError, match="chat_not_found"):
            await repository.list_messages(wrong.conversation.id)
    bound.list_messages.assert_not_awaited()
    with pytest.raises(ValueError, match="historical_owner_mismatch"):
        repository.with_user(uuid4())


@pytest.mark.asyncio
async def test_disabled_scoped_route_still_requires_owned_history(
    monkeypatch, tmp_path
):
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "old-agent": SimpleNamespace(
                    enabled=False,
                    workspace_dir=str(tmp_path),
                )
            }
        )
    )
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_scoped, "load_config", lambda: config)
    membership = SimpleNamespace(
        require_historical_read=AsyncMock(side_effect=AgentAccessDeniedError)
    )
    monkeypatch.setattr(
        agent_scoped, "_get_agent_membership_service", lambda: membership
    )
    request = _request("/api/agents/old-agent/chats/id")
    with pytest.raises(HTTPException) as denied:
        await agent_scoped.require_agent_scoped_access(
            request, "old-agent", request.state.actor
        )
    assert denied.value.status_code == 403
