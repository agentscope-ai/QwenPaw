# -*- coding: utf-8 -*-
"""Task 13.2 关键资源 IDOR 攻击矩阵。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AgentAccessDeniedError, AgentMembershipService
from qwenpaw.access.agent_repository import AgentResourceRole, LegacyAgentRecord
from qwenpaw.app import auth
from qwenpaw.app.approvals.service import ApprovalService, PendingApproval
from qwenpaw.app.chats.repo import PostgresConversationRepository
from qwenpaw.app.channels.user_bindings import bind_process_identity
from qwenpaw.app.routers import approval, backup, console, envs
from qwenpaw.identity.models import PlatformRole, UserRecord
from qwenpaw.identity.sessions import AuthenticatedSession, SessionRecord
from qwenpaw.workspaces.resolver import WorkspaceKind, WorkspaceResolutionDenied, WorkspaceResolver


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
RUN_ID = UUID("33333333-3333-4333-8333-333333333333")
CONVERSATION_ID = UUID("44444444-4444-4444-8444-444444444444")


def _actor(user_id: UUID, role: PlatformRole = PlatformRole.MEMBER) -> ActorContext:
    return ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="task-13-2",
    )


@pytest.mark.asyncio
async def test_agent_id_is_denied_without_membership() -> None:
    class Repository:
        async def list_accessible(self, **_kwargs):
            return {}

        async def list_historical_accessible(self, **_kwargs):
            return {}

        async def list_registered_keys(self, keys):
            return set(keys)

        async def get_first_admin_id(self):
            return USER_A

    agent = LegacyAgentRecord(
        key="foreign-agent",
        name="Foreign",
        description="",
        workspace_key="workspaces/foreign-agent",
        status="active",
    )

    with pytest.raises(AgentAccessDeniedError):
        await AgentMembershipService(Repository()).require_role(
            actor=_actor(USER_B),
            agent=agent,
            allowed_roles={AgentResourceRole.USER},
        )


def test_file_id_and_path_traversal_cannot_escape_user_runtime(tmp_path) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)

    with pytest.raises(WorkspaceResolutionDenied):
        resolver.resolve(
            kind=WorkspaceKind.USER_RUNTIME,
            resource_id="../foreign-agent",
            actor_user_id=USER_A,
            workspace_key=f"user_workspaces/{USER_B}/foreign-agent",
        )


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _RunScopeSession:
    """模拟数据库，并要求 Run 查询携带请求用户访问条件。"""

    def __init__(self, method: str) -> None:
        self.method = method

    async def execute(self, statement, params):
        sql = str(statement)
        if "set_config('qwenpaw.user_id'" in sql:
            assert params["user_id"] == str(USER_B)
            return _Result([])
        assert "request_user_id" in sql
        assert params["request_user_id"] == USER_B
        assert "conversation_members" in sql
        assert "agent_members" in sql
        return _Result([])


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_run", "list_events", "list_tool_calls"])
async def test_run_id_cannot_cross_authenticated_repository_scope(method: str) -> None:
    session = _RunScopeSession(method)

    @asynccontextmanager
    async def session_factory():
        yield session

    repository = PostgresConversationRepository(
        schema="public",
        session_factory=session_factory,
    ).with_user(USER_B)

    result = await getattr(repository, method)(RUN_ID)

    if method == "get_run":
        assert result is None
    else:
        assert result == []


@pytest.mark.asyncio
async def test_conversation_batch_is_all_or_nothing_before_delete(monkeypatch) -> None:
    deleted = False

    class Manager:
        async def delete_chats(self, *, chat_ids):
            nonlocal deleted
            deleted = True
            return True

    async def require_writable(_request, _manager, _workspace, chat_id):
        if chat_id == "foreign":
            raise console.HTTPException(status_code=404, detail="Chat not found")
        return SimpleNamespace(
            id=chat_id,
            session_id=chat_id,
            user_id=str(USER_A),
            channel="console",
        )

    from qwenpaw.app.chats import api as chats_api

    monkeypatch.setattr(chats_api, "_require_writable_chat", require_writable)
    request = Request({"type": "http", "headers": []})
    request.state.actor = _actor(USER_A)

    with pytest.raises(chats_api.HTTPException, match="Chat not found"):
        await chats_api.batch_delete_chats(
            ["mine", "foreign"],
            request,
            Manager(),
            SimpleNamespace(),
        )

    assert deleted is False


@pytest.mark.asyncio
async def test_notification_batch_ignores_foreign_event_ids(monkeypatch) -> None:
    captured = {}

    async def delete_events(event_ids, *, recipient_user_id=None):
        captured.update(ids=event_ids, recipient=recipient_user_id)
        return 1

    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.app.inbox_store.delete_events", delete_events)
    request = Request({"type": "http", "headers": []})
    request.state.actor = _actor(USER_A)

    result = await console.delete_inbox_events(
        console.DeleteInboxEventsRequest(event_ids=["mine", "foreign"]),
        request,
    )

    assert result == {"deleted": 1}
    assert captured == {"ids": ["mine", "foreign"], "recipient": str(USER_A)}


@pytest.mark.asyncio
async def test_approval_id_cannot_be_resolved_by_another_user(monkeypatch) -> None:
    service = ApprovalService()
    pending = PendingApproval(
        request_id="approval-a",
        session_id="console:a",
        root_session_id="console:a",
        owner_agent_id="agent-a",
        user_id=str(USER_A),
        channel="console",
        agent_id="agent-a",
        tool_name="execute_shell_command",
        created_at=0,
        future=asyncio.get_running_loop().create_future(),
        approval_user_id=str(USER_A),
    )
    service._pending[pending.request_id] = pending
    monkeypatch.setattr(approval, "get_approval_service", lambda: service)
    monkeypatch.setattr(approval, "is_multi_user_enabled", lambda: True)
    request = Request({"type": "http", "headers": []})
    request.state.actor = _actor(USER_B)

    with pytest.raises(approval.HTTPException) as exc_info:
        await approval.post_approval_approve(
            request,
            approval.ApprovalActionRequest(
                request_id=pending.request_id,
                session_id=pending.root_session_id,
            ),
        )

    assert exc_info.value.status_code == 404
    assert pending.request_id in service._pending


def test_secret_resource_rejects_member() -> None:
    app = FastAPI()
    app.include_router(envs.router, prefix="/api")
    app.dependency_overrides[envs.get_actor] = lambda: _actor(USER_A)

    response = TestClient(app).get("/api/envs")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_external_identity_cannot_select_platform_owner() -> None:
    captured = {}

    async def process(request):
        captured["runtime_user_id"] = request.user_id
        yield {"type": "done"}

    async def record(**kwargs):
        captured.update(kwargs)

    request = SimpleNamespace(
        user_id=str(USER_B),
        session_id="telegram:foreign",
        channel="telegram",
        channel_meta={"username": "foreign"},
        request_context={"user_id": str(USER_B)},
    )
    binding_id = uuid4()
    wrapped = bind_process_identity(
        process,
        owner_user_id=USER_A,
        binding_id=binding_id,
        record_external_identity=record,
    )

    assert [event async for event in wrapped(request)] == [{"type": "done"}]
    assert captured["runtime_user_id"] == str(USER_A)
    assert captured["platform_user_id"] == USER_A
    assert captured["external_subject_id"] == str(USER_B)


def test_backup_and_log_resources_reject_member_even_with_guessed_ids(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(backup, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(console, "LOG_FILE_PATH", tmp_path / "qwenpaw.log")
    (tmp_path / "qwenpaw.log").write_text("private", encoding="utf-8")
    app = FastAPI()

    @app.middleware("http")
    async def attach_actor(request: Request, call_next):
        request.state.actor = _actor(USER_A)
        return await call_next(request)

    app.include_router(backup.router, prefix="/api")
    app.include_router(console.router, prefix="/api")
    client = TestClient(app)

    assert client.get("/api/backups/guessed-backup").status_code == 403
    assert client.get("/api/backups/guessed-backup/export").status_code == 403
    assert client.get("/api/console/debug/backend-logs").status_code == 403


def test_forged_identity_headers_do_not_replace_authenticated_actor(monkeypatch) -> None:
    now = datetime.now(UTC)
    user = UserRecord(
        id=USER_A,
        username="owner",
        platform_role=PlatformRole.MEMBER,
        status="active",
    )
    authenticated = AuthenticatedSession(
        user=user,
        session=SessionRecord(
            id=uuid4(),
            user_id=USER_A,
            client_info={},
            created_at=now,
            last_seen_at=None,
            access_expires_at=now,
            refresh_expires_at=now,
            revoked_at=None,
        ),
    )

    class Sessions:
        async def authenticate_access(self, token):
            return authenticated if token == "valid" else None

    monkeypatch.setattr(auth, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        auth,
        "get_identity_runtime",
        lambda: SimpleNamespace(sessions=Sessions()),
    )
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)

    @app.get("/api/whoami")
    async def whoami(request: Request):
        return {"user_id": str(request.state.actor.user_id)}

    response = TestClient(app).get(
        "/api/whoami",
        headers={
            "Authorization": "Bearer valid",
            "X-User-Id": str(USER_B),
            "X-Owner-User-Id": str(USER_B),
        },
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": str(USER_A)}
