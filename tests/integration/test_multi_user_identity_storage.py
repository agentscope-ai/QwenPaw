# -*- coding: utf-8 -*-
"""真实 PostgreSQL 身份、会话和个人偏好闭环。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_migrations import _alembic_config

from qwenpaw.app import auth as auth_middleware
from qwenpaw.app.routers import auth as auth_router
from qwenpaw.app.routers import me as me_router
from qwenpaw.identity.governance import LastActiveAdminError, UserGovernanceService
from qwenpaw.identity.models import PlatformRole
from qwenpaw.identity.preferences import PostgresPreferenceRepository
from qwenpaw.identity.repository import PostgresUserRepository
from qwenpaw.identity.runtime import IdentityRuntime
from qwenpaw.identity.service import UserService
from qwenpaw.identity.session_repository import PostgresSessionRepository
from qwenpaw.identity.sessions import SessionService


def _runtime(schema: str, session_factory) -> IdentityRuntime:
    return IdentityRuntime(
        users=UserService(
            PostgresUserRepository(
                schema=schema,
                session_factory=session_factory,
            )
        ),
        sessions=SessionService(
            PostgresSessionRepository(
                schema=schema,
                session_factory=session_factory,
            )
        ),
        preferences=PostgresPreferenceRepository(
            schema=schema,
            session_factory=session_factory,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_real_postgres_login_refresh_logout_and_preferences(
    postgres_test_schema,
) -> None:
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    engine = create_async_engine(
        postgres_test_schema.async_url(),
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    try:
        users = UserService(
            PostgresUserRepository(
                schema=postgres_test_schema.name,
                session_factory=session_factory,
            )
        )
        admin = await users.create_user(
            "admin",
            "admin-password",
            PlatformRole.MEMBER,
        )
        member = await users.create_user(
            "member",
            "member-password",
            PlatformRole.MEMBER,
        )
        assert admin.platform_role is PlatformRole.ADMIN
        assert member.platform_role is PlatformRole.MEMBER

        sessions = SessionService(
            PostgresSessionRepository(
                schema=postgres_test_schema.name,
                session_factory=session_factory,
            )
        )
        issued = await sessions.issue(member, {"device": "browser-a"})
        assert (await sessions.authenticate_access(issued.access_token)).user == member

        rotated = await sessions.refresh(issued.refresh_token)
        assert rotated is not None
        assert await sessions.authenticate_access(issued.access_token) is None
        assert (await sessions.authenticate_access(rotated.access_token)).user == member

        preferences = PostgresPreferenceRepository(
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        initial = await preferences.get_or_create(member.id)
        assert initial.language == "zh-CN"
        assert initial.timezone == "Asia/Shanghai"
        updated = await preferences.update(
            member.id,
            language="en",
            timezone="UTC",
        )
        assert updated.language == "en"
        assert updated.timezone == "UTC"

        assert await sessions.revoke_current(rotated.refresh_token) is True
        assert await sessions.authenticate_access(rotated.access_token) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_real_postgres_admin_user_governance_and_session_revocation(
    postgres_test_schema,
) -> None:
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    engine = create_async_engine(
        postgres_test_schema.async_url(),
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    repository = PostgresUserRepository(
        schema=postgres_test_schema.name,
        session_factory=session_factory,
    )
    users = UserService(repository)
    sessions = SessionService(
        PostgresSessionRepository(
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
    )
    governance = UserGovernanceService(
        repository=repository,
        user_service=users,
        session_service=sessions,
    )

    try:
        admin = await governance.create_user(
            "admin",
            "admin-password",
            PlatformRole.MEMBER,
        )
        member = await governance.create_user(
            "member",
            "member-password",
            PlatformRole.MEMBER,
        )
        issued = await sessions.issue(member, {"device": "browser-governance"})

        with pytest.raises(LastActiveAdminError, match="last_active_admin"):
            await governance.set_status(admin.id, "disabled")

        promoted = await governance.set_role(member.id, PlatformRole.ADMIN)
        assert promoted.platform_role is PlatformRole.ADMIN
        demoted = await governance.set_role(member.id, PlatformRole.MEMBER)
        assert demoted.platform_role is PlatformRole.MEMBER

        disabled, revoked = await governance.set_status(member.id, "disabled")
        assert disabled.status == "disabled"
        assert revoked == 1
        assert await sessions.authenticate_access(issued.access_token) is None
        assert {user.username for user in await governance.list_users()} == {
            "admin",
            "member",
        }
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_real_postgres_http_two_users_keep_independent_sessions(
    postgres_test_schema,
    monkeypatch,
) -> None:
    command.upgrade(_alembic_config(postgres_test_schema), "head")
    engine = create_async_engine(
        postgres_test_schema.async_url(),
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    runtime = _runtime(postgres_test_schema.name, session_factory)
    monkeypatch.setattr(auth_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(auth_router, "get_identity_runtime", lambda: runtime)
    monkeypatch.setattr(me_router, "get_identity_runtime", lambda: runtime)
    monkeypatch.setattr(auth_middleware, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        auth_middleware,
        "get_identity_runtime",
        lambda: runtime,
    )
    monkeypatch.setenv("QWENPAW_SESSION_COOKIE_SECURE", "false")

    app = FastAPI()
    app.add_middleware(auth_middleware.AuthMiddleware)
    app.include_router(auth_router.router, prefix="/api")
    app.include_router(me_router.router, prefix="/api")

    import asyncio

    async def seed_users() -> None:
        await runtime.users.create_user(
            "admin",
            "admin-password",
            PlatformRole.ADMIN,
        )
        await runtime.users.create_user(
            "member",
            "member-password",
            PlatformRole.MEMBER,
        )

    asyncio.run(seed_users())

    admin_client = TestClient(app)
    member_client = TestClient(app)
    try:
        admin_login = admin_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )
        assert admin_login.status_code == 200
        admin_access = admin_login.json()["token"]
        assert (
            admin_client.get(
                "/api/me",
                headers={"Authorization": f"Bearer {admin_access}"},
            ).json()["user"]["platform_role"]
            == "admin"
        )

        member_login = member_client.post(
            "/api/auth/login",
            json={"username": "member", "password": "member-password"},
        )
        assert member_login.status_code == 200
        member_access = member_login.json()["token"]
        assert (
            member_client.get(
                "/api/me",
                headers={"Authorization": f"Bearer {member_access}"},
            ).json()["user"]["username"]
            == "member"
        )

        assert admin_client.post("/api/auth/logout").status_code == 200
        member_me = member_client.get(
            "/api/me",
            headers={"Authorization": f"Bearer {member_access}"},
        )
        assert member_me.status_code == 200

        refreshed = member_client.post("/api/auth/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["token"] != member_access
    finally:
        admin_client.close()
        member_client.close()
        asyncio.run(engine.dispose())
