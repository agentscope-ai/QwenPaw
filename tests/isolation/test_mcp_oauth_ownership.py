# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from copy import deepcopy
from unittest.mock import AsyncMock
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.app.mcp.oauth_repository import (
    OAuthSessionConflictError,
    OAuthSessionRecord,
    PostgresOAuthRepository,
)
from qwenpaw.app.routers.mcp_oauth import (
    OAuthStartRequest,
    OAuthSession,
    _legacy_session_status,
    _completion_store,
    _purge_expired,
    _oauth_target_is_unchanged,
    _popup_html,
    _state_store,
    oauth_revoke,
    oauth_start,
    oauth_status,
)
from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.mcp.postgres_repository import (
    _attach_oauth_config,
    _detach_oauth_config,
)


class _Rows:
    def __init__(self, row=None) -> None:
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class _ProtocolSession:
    """Exercise repository SQL state transitions without replacing its behavior."""

    def __init__(self, *, user_status="active", role="owner") -> None:
        self.rows: dict[str, dict] = {}
        self.user_status = user_status
        self.role = role

    async def execute(self, statement, params):
        sql = re.sub(r"\s+", " ", str(statement)).strip()
        if sql.startswith("INSERT INTO"):
            if params["state_hash"] in self.rows:
                raise AssertionError("duplicate state")
            self.rows[params["state_hash"]] = dict(params, status="pending")
            return _Rows()
        if "UPDATE" in sql and "status = 'consumed'" in sql:
            row = self.rows.get(params["state_hash"])
            valid = (
                row is not None
                and row["status"] == "pending"
                and row["expires_at"] > datetime.now(UTC)
                and self.user_status == "active"
                and self.role in {"owner", "collaborator"}
                and row["driver_id"] == params["driver_id"]
            )
            if not valid:
                return _Rows()
            row["status"] = "consumed"
            return _Rows(
                {
                    "id": row["id"],
                    "driver_id": row["driver_id"],
                    "initiated_by": row["initiated_by"],
                    "expires_at": row["expires_at"],
                }
            )
        if sql.startswith("UPDATE") and "status = 'failed'" in sql:
            row = self.rows.get(params["state_hash"])
            if (
                row is None
                or row["status"] != "pending"
                or row["driver_id"] != params["driver_id"]
                or row["initiated_by"] != params["initiated_by"]
            ):
                return _Rows()
            row["status"] = "failed"
            return _Rows({"id": row["id"]})
        if sql.startswith("SELECT"):
            row = self.rows.get(params["state_hash"])
            if (
                row is None
                or row["driver_id"] != params["driver_id"]
                or row["initiated_by"] != params["initiated_by"]
            ):
                return _Rows()
            return _Rows(
                {"status": row["status"], "expires_at": row["expires_at"]}
            )
        raise AssertionError(sql)


@pytest.mark.asyncio
async def test_postgres_state_is_single_use_and_owned_by_initiator() -> None:
    repo = PostgresOAuthRepository(schema="qwenpaw_test_aaaaaaaaaaaaaaaaaaaa")
    db = _ProtocolSession()
    driver_id, user_id = uuid4(), uuid4()
    state = "browser-state"
    expires_at = datetime.now(UTC) + timedelta(minutes=10)

    await repo.create(
        session=db,
        state=state,
        driver_id=driver_id,
        initiated_by=user_id,
        expires_at=expires_at,
    )
    consumed = await repo.consume(
        session=db,
        state=state,
        driver_id=driver_id,
        initiated_by=user_id,
    )

    assert consumed == OAuthSessionRecord(
        id=consumed.id,
        driver_id=driver_id,
        initiated_by=user_id,
        expires_at=expires_at,
    )
    with pytest.raises(OAuthSessionConflictError):
        await repo.consume(
            session=db,
            state=state,
            driver_id=driver_id,
            initiated_by=user_id,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_status", "role"),
    [("disabled", "owner"), ("active", "user"), ("active", "revoked")],
)
async def test_postgres_consume_rechecks_active_editor(user_status, role) -> None:
    repo = PostgresOAuthRepository(schema="qwenpaw_test_aaaaaaaaaaaaaaaaaaaa")
    db = _ProtocolSession(user_status=user_status, role=role)
    driver_id, user_id = uuid4(), uuid4()
    await repo.create(
        session=db,
        state="state",
        driver_id=driver_id,
        initiated_by=user_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    with pytest.raises(OAuthSessionConflictError):
        await repo.consume(
            session=db,
            state="state",
            driver_id=driver_id,
            initiated_by=user_id,
        )


@pytest.mark.asyncio
async def test_failed_callback_terminates_pending_state() -> None:
    repo = PostgresOAuthRepository(schema="qwenpaw_test_aaaaaaaaaaaaaaaaaaaa")
    db = _ProtocolSession()
    driver_id, user_id = uuid4(), uuid4()
    await repo.create(
        session=db,
        state="failed",
        driver_id=driver_id,
        initiated_by=user_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    assert await repo.fail(
        session=db,
        state="failed",
        driver_id=driver_id,
        initiated_by=user_id,
    ) is True
    assert db.rows[repo.state_hash("failed")]["status"] == "failed"


@pytest.mark.asyncio
async def test_correlated_status_rejects_other_user_and_client() -> None:
    repo = PostgresOAuthRepository(schema="qwenpaw_test_aaaaaaaaaaaaaaaaaaaa")
    db = _ProtocolSession()
    driver_id, user_id = uuid4(), uuid4()
    await repo.create(
        session=db,
        state="session",
        driver_id=driver_id,
        initiated_by=user_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    assert (
        await repo.status(
            session=db,
            state="session",
            driver_id=driver_id,
            initiated_by=user_id,
        )
    ).status == "pending"
    assert await repo.status(
        session=db,
        state="session",
        driver_id=uuid4(),
        initiated_by=user_id,
    ) is None
    assert await repo.status(
        session=db,
        state="session",
        driver_id=driver_id,
        initiated_by=uuid4(),
    ) is None


def test_popup_uses_same_origin_and_contains_correlation_without_storage() -> None:
    page = _popup_html(
        "success",
        "ok",
        extra_data={
            "session_id": "s1",
            "client_key": "client",
            "agent_id": "agent",
        },
    )

    assert "mcp-oauth-success" in page
    assert 'postMessage(data, window.location.origin)' in page
    assert "localStorage" not in page
    assert '"session_id": "s1"' in page


def test_expired_memory_session_cannot_be_reused_after_lookup() -> None:
    session = OAuthSession(
        agent_id="agent",
        client_key="client",
        code_verifier="verifier",
        client_id="client-id",
        auth_endpoint="https://idp.test/auth",
        token_endpoint="https://idp.test/token",
        redirect_uri="https://app.test/api/mcp/oauth/callback",
        scope="tools",
    )
    session.created_at -= 601

    assert session.is_expired() is True


def test_replaced_driver_revision_is_rejected_before_token_binding() -> None:
    driver_id = uuid4()
    oauth = OAuthSession(
        agent_id="agent",
        client_key="client",
        code_verifier="verifier",
        client_id="client-id",
        auth_endpoint="https://idp.test/auth",
        token_endpoint="https://idp.test/token",
        redirect_uri="https://app.test/api/mcp/oauth/callback",
        scope="tools",
        driver_id=driver_id,
        driver_revision=7,
        postgres=True,
    )

    assert _oauth_target_is_unchanged(
        oauth,
        SimpleNamespace(driver_id=driver_id, revision=8, enabled=True),
    ) is False
    assert _oauth_target_is_unchanged(
        oauth,
        SimpleNamespace(driver_id=uuid4(), revision=7, enabled=True),
    ) is False


def test_reauthorization_with_old_token_remains_pending() -> None:
    session_id = "new-authorization"
    session = OAuthSession(
        agent_id="agent",
        client_key="client",
        code_verifier="verifier",
        client_id="client-id",
        auth_endpoint="https://idp.test/auth",
        token_endpoint="https://idp.test/token",
        redirect_uri="https://app.test/api/mcp/oauth/callback",
        scope="tools",
    )
    _state_store[session_id] = session
    try:
        assert _legacy_session_status(
            session_id, "agent", "client", None
        ) == "pending"
        assert _legacy_session_status(
            session_id, "agent", "other-client", None
        ) is None
    finally:
        _state_store.pop(session_id, None)


class _Transaction:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return False


class _UnknownTargetRepository:
    def __init__(self, **_kwargs) -> None:
        pass

    def transaction(self):
        return _Transaction()

    async def get_oauth_target(self, **_kwargs):
        return None


class _RevisionRepository(_UnknownTargetRepository):
    async def get_oauth_target(self, **_kwargs):
        return SimpleNamespace(
            driver_id=uuid4(),
            agent_id=uuid4(),
            client_key="client",
            revision=7,
            enabled=True,
            endpoint_url="https://mcp.invalid",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["start", "status", "revoke"])
async def test_postgres_agent_unknown_client_never_reads_legacy(
    monkeypatch,
    operation,
) -> None:
    import qwenpaw.app.agent_context as agent_context
    import qwenpaw.app.mcp.postgres_repository as pg_module
    import qwenpaw.app.routers.mcp_oauth as oauth_module

    workspace = SimpleNamespace(agent_id="pg-agent")

    async def get_agent(_request):
        return workspace

    async def uses_pg(_workspace, **_kwargs):
        return True

    async def legacy_forbidden(*_args, **_kwargs):
        raise AssertionError("PG Agent must not access Legacy DriverCard")

    monkeypatch.setattr(agent_context, "get_agent_for_request", get_agent)
    monkeypatch.setattr(pg_module, "is_postgres_mcp_enabled", lambda: True)
    monkeypatch.setattr(pg_module, "workspace_uses_postgres", uses_pg)
    monkeypatch.setattr(pg_module, "PostgresMCPRepository", _UnknownTargetRepository)
    monkeypatch.setattr(
        oauth_module, "_load_mcp_card_for_oauth", legacy_forbidden
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/mcp/oauth",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )
    request.state.actor = ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=None,
        admin_mode=False,
        request_id="test",
    )

    with pytest.raises(HTTPException) as captured:
        if operation == "start":
            await oauth_start(
                "ghost",
                OAuthStartRequest(
                    url="https://legacy.invalid",
                    auth_endpoint="https://idp.invalid/auth",
                    token_endpoint="https://idp.invalid/token",
                    expected_revision=1,
                ),
                request,
            )
        elif operation == "status":
            await oauth_status("ghost", request, session_id="unknown")
        else:
            await oauth_revoke("ghost", request, expected_revision=1)
    assert captured.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "revision", "detail"),
    [
        ("start", None, "expected_revision_required"),
        ("start", 6, "mcp_revision_conflict"),
        ("revoke", None, "expected_revision_required"),
        ("revoke", 6, "mcp_revision_conflict"),
    ],
)
async def test_postgres_oauth_requires_current_revision(
    monkeypatch, operation, revision, detail
) -> None:
    import qwenpaw.app.agent_context as agent_context
    import qwenpaw.app.mcp.postgres_repository as pg_module

    async def get_agent(_request):
        return SimpleNamespace(agent_id="pg-agent")

    async def uses_pg(_workspace, **_kwargs):
        return True

    monkeypatch.setattr(agent_context, "get_agent_for_request", get_agent)
    monkeypatch.setattr(pg_module, "is_postgres_mcp_enabled", lambda: True)
    monkeypatch.setattr(pg_module, "workspace_uses_postgres", uses_pg)
    monkeypatch.setattr(pg_module, "PostgresMCPRepository", _RevisionRepository)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/mcp/oauth",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )
    request.state.actor = ActorContext(
        user_id=uuid4(), actor_type=ActorType.USER, platform_role=None,
        admin_mode=False, request_id="test",
    )
    with pytest.raises(HTTPException) as captured:
        if operation == "start":
            await oauth_start(
                "client",
                OAuthStartRequest(
                    url="https://ignored.invalid",
                    auth_endpoint="https://idp.invalid/auth",
                    token_endpoint="https://idp.invalid/token",
                    expected_revision=revision,
                ),
                request,
            )
        else:
            await oauth_revoke("client", request, expected_revision=revision)
    assert captured.value.status_code == 409
    assert captured.value.detail == detail


@pytest.mark.asyncio
async def test_legacy_start_captures_authenticated_initiator(monkeypatch) -> None:
    import qwenpaw.app.agent_context as agent_context
    import qwenpaw.app.mcp.postgres_repository as pg_module
    import qwenpaw.app.routers.mcp_oauth as oauth_module

    user_id = uuid4()

    async def get_agent(_request):
        return SimpleNamespace(agent_id="legacy-agent")

    async def load_card(*_args, **_kwargs):
        return SimpleNamespace(endpoint={"url": "https://mcp.invalid"})

    async def no_credential(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_context, "get_agent_for_request", get_agent)
    monkeypatch.setattr(pg_module, "is_postgres_mcp_enabled", lambda: False)
    monkeypatch.setattr(oauth_module, "_load_mcp_card_for_oauth", load_card)
    monkeypatch.setattr(
        oauth_module, "_load_optional_oauth_credential", no_credential
    )
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/mcp/oauth", "headers": []}
    )
    request.state.actor = ActorContext(
        user_id=user_id, actor_type=ActorType.USER, platform_role=None,
        admin_mode=False, request_id="test",
    )
    response = await oauth_start(
        "client",
        OAuthStartRequest(
            url="https://ignored.invalid",
            auth_endpoint="https://idp.invalid/auth",
            token_endpoint="https://idp.invalid/token",
        ),
        request,
    )
    try:
        assert _state_store[response.session_id].initiated_by == user_id
    finally:
        _state_store.pop(response.session_id, None)


def test_purge_expired_globally_bounds_unqueried_completions() -> None:
    now = __import__("time").monotonic()
    session = OAuthSession(
        agent_id="agent", client_key="client", code_verifier="v",
        client_id="c", auth_endpoint="https://idp.invalid/auth",
        token_endpoint="https://idp.invalid/token", redirect_uri="https://app.invalid/cb",
        scope="",
    )
    _completion_store.clear()
    _completion_store["expired-unqueried"] = (
        session, "completed", now - 601
    )
    for index in range(1100):
        _completion_store[f"fresh-{index:04d}"] = (
            session, "completed", now + index / 10000
        )

    _purge_expired()

    assert "expired-unqueried" not in _completion_store
    assert len(_completion_store) <= 1024
    assert "fresh-0000" not in _completion_store
    _completion_store.clear()


def test_postgres_oauth_binding_materializes_runtime_card_config() -> None:
    original = {
        "endpoint": {
            "transport": "streamable_http",
            "url": "https://mcp.invalid",
            "headers": {"X-Public": {"source": "literal", "value": "ok"}},
        },
        "credentials": {},
        "config": {"display_name": "OAuth"},
    }

    attached = _attach_oauth_config(original)

    assert attached["credentials"]["oauth"] == {
        "kind": "oauth2_auth_code",
        "purpose": "oauth",
    }
    assert attached["endpoint"]["headers"]["Authorization"] == {
        "source": "credential",
        "credential": "oauth",
        "field": "access_token",
        "format": "Bearer {value}",
    }
    assert attached["endpoint"]["headers"]["X-Public"]["value"] == "ok"
    assert "Authorization" not in original["endpoint"]["headers"]

    detached = _detach_oauth_config(attached)
    assert "oauth" not in detached["credentials"]
    assert "Authorization" not in detached["endpoint"]["headers"]
    assert detached["endpoint"]["headers"]["X-Public"]["value"] == "ok"


_CUSTOM_AUTHORIZATIONS = [
    {"source": "literal", "value": "private-user-value"},
    {"source": "credential", "credential": "static", "field": "token"},
    {
        "source": "credential",
        "credential": "oauth",
        "field": "refresh_token",
        "format": "Bearer {value}",
    },
    {
        "source": "credential",
        "credential": "oauth",
        "field": "access_token",
        "format": "Custom {value}",
    },
    {"source": "credential", "credential": "oauth", "field": "access_token"},
]


@pytest.mark.parametrize("authorization", _CUSTOM_AUTHORIZATIONS)
def test_oauth_attach_rejects_custom_authorization_without_mutation(authorization):
    config = {
        "endpoint": {
            "transport": "streamable_http",
            "headers": {"Authorization": authorization},
        }
    }
    before = deepcopy(config)
    with pytest.raises(ValueError, match="oauth_authorization_conflict"):
        _attach_oauth_config(config)
    assert config == before


@pytest.mark.parametrize("authorization", _CUSTOM_AUTHORIZATIONS)
def test_oauth_detach_preserves_custom_authorization(authorization):
    config = {
        "endpoint": {
            "transport": "streamable_http",
            "headers": {"Authorization": authorization},
        }
    }
    before = deepcopy(config)
    assert (
        _detach_oauth_config(config)["endpoint"]["headers"]["Authorization"]
        == authorization
    )
    assert config == before


@pytest.mark.asyncio
async def test_oauth_conflict_rejects_before_credential_or_revision_write():
    from qwenpaw.app.mcp.postgres_repository import (
        PostgresMCPRepository,
        MCPDriverTarget,
    )

    repo = PostgresMCPRepository()
    target = MCPDriverTarget(uuid4(), uuid4(), "client", 7, True, "https://mcp.invalid")
    row = {
        "revision": 7,
        "config": {
            "endpoint": {
                "transport": "streamable_http",
                "headers": {"Authorization": _CUSTOM_AUTHORIZATIONS[0]},
            }
        },
        "tool_allowlist": None,
        "policy": {},
    }
    before = deepcopy(row)
    db = SimpleNamespace(execute=AsyncMock(return_value=_Rows(row)))
    repo._credentials.create_and_bind = AsyncMock(return_value=uuid4())
    repo._insert_revision = AsyncMock()
    with pytest.raises(ValueError, match="oauth_authorization_conflict"):
        await repo.replace_bound_credential(
            session=db,
            target=target,
            actor_user_id=uuid4(),
            purpose="oauth",
            kind="oauth2_auth_code",
            public={},
            secrets={"access_token": "new-token"},
        )
    assert row == before
    repo._credentials.create_and_bind.assert_not_awaited()
    repo._insert_revision.assert_not_awaited()
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_postgres_oauth_start_conflict_is_fixed_400_before_discovery(monkeypatch):
    import qwenpaw.app.agent_context as agent_context
    import qwenpaw.app.mcp.postgres_repository as pg_module
    import qwenpaw.app.routers.mcp_oauth as oauth_module

    class ConflictRepository(_RevisionRepository):
        async def get_oauth_target(self, **kwargs):
            target = await super().get_oauth_target(**kwargs)
            target.oauth_authorization_conflict = True
            return target

    monkeypatch.setattr(
        agent_context,
        "get_agent_for_request",
        AsyncMock(return_value=SimpleNamespace(agent_id="pg-agent")),
    )
    monkeypatch.setattr(pg_module, "is_postgres_mcp_enabled", lambda: True)
    monkeypatch.setattr(
        pg_module, "workspace_uses_postgres", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(pg_module, "PostgresMCPRepository", ConflictRepository)
    discovery = AsyncMock(side_effect=AssertionError("must reject before discovery"))
    monkeypatch.setattr(oauth_module, "_discover_oauth_metadata", discovery)
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/mcp/oauth", "headers": []}
    )
    request.state.actor = ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=None,
        admin_mode=False,
        request_id="test",
    )
    before = dict(_state_store)
    with pytest.raises(HTTPException) as captured:
        await oauth_start(
            "client",
            OAuthStartRequest(url="https://mcp.invalid", expected_revision=7),
            request,
        )
    assert captured.value.status_code == 400
    assert (
        captured.value.detail
        == "Remove the existing Authorization header before starting OAuth."
    )
    discovery.assert_not_awaited()
    assert _state_store == before


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", _CUSTOM_AUTHORIZATIONS)
async def test_oauth_target_reports_conflict_and_revoke_preserves_header(authorization):
    from qwenpaw.app.mcp.postgres_repository import PostgresMCPRepository

    repo = PostgresMCPRepository()
    config = {
        "endpoint": {
            "transport": "streamable_http",
            "url": "https://mcp.invalid",
            "headers": {"Authorization": authorization},
        },
        "credentials": {"oauth": {"kind": "oauth2_auth_code", "purpose": "oauth"}},
    }
    before = deepcopy(config)
    record = SimpleNamespace(
        driver_id=uuid4(),
        agent_id=uuid4(),
        client_key="client",
        revision=7,
        enabled=True,
        config=config,
    )
    repo.get_driver = AsyncMock(return_value=record)
    row = {
        "revision": 7,
        "config": config,
        "credential_id": uuid4(),
        "tool_allowlist": None,
        "policy": {},
    }
    db = SimpleNamespace(execute=AsyncMock(return_value=_Rows(row)))
    repo._credentials.revoke = AsyncMock()
    repo._insert_revision = AsyncMock()
    target = await repo.get_oauth_target(
        session=db, agent_key="agent", client_key="client"
    )
    assert target.oauth_authorization_conflict is True
    assert (
        await repo.revoke_bound_credential(
            session=db, target=target, actor_user_id=uuid4()
        )
        is True
    )
    saved = repo._insert_revision.await_args.kwargs["config"]
    assert saved["endpoint"]["headers"]["Authorization"] == authorization
    assert config == before


def test_exact_oauth_binding_can_be_reattached_and_detached():
    attached = _attach_oauth_config({"endpoint": {"transport": "streamable_http"}})
    assert _attach_oauth_config(attached) == attached
    assert "Authorization" not in _detach_oauth_config(attached)["endpoint"]["headers"]


@pytest.mark.parametrize("header", ["authorization", "AUTHORIZATION", "aUtHoRiZaTiOn"])
@pytest.mark.parametrize("system_binding", [False, True])
def test_oauth_attach_rejects_authorization_aliases(header, system_binding):
    config = _attach_oauth_config({"endpoint": {"transport": "streamable_http"}})
    binding = config["endpoint"]["headers"].pop("Authorization")
    config["endpoint"]["headers"][header] = (
        binding if system_binding else _CUSTOM_AUTHORIZATIONS[0]
    )
    before = deepcopy(config)
    with pytest.raises(ValueError, match="oauth_authorization_conflict"):
        _attach_oauth_config(config)
    assert config == before
    assert (
        _detach_oauth_config(config)["endpoint"]["headers"]
        == before["endpoint"]["headers"]
    )
