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
    tmp_path,
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
    # 管理员登录时登记智能体也必须使用本测试的 PostgreSQL，不读取开发机的数据库。
    from qwenpaw.access import agent_repository
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sqlalchemy import text
    from qwenpaw.access.actor import ActorContext, ActorType
    from qwenpaw.access.agent_membership import AgentMembershipService
    from qwenpaw.access.agent_repository import AgentResourceRole, LegacyAgentRecord
    from qwenpaw.app import agent_context
    from qwenpaw.app.routers import personal_library
    from qwenpaw.config import Config
    from qwenpaw.personal_library.repository import PostgresPersonalLibraryRepository
    from qwenpaw.personal_library.service import PersonalLibraryService

    agents = agent_repository.PostgresAgentRepository(
        schema=postgres_test_schema.name, session_factory=session_factory,
    )
    monkeypatch.setattr(agent_repository, "PostgresAgentRepository", lambda **_: agents)
    config = Config.model_validate({"agents": {"active_agent": "office", "profiles": {
        "office": {"id": "office", "workspace_dir": str(tmp_path)}
    }}})
    monkeypatch.setattr(auth_middleware, "_auth_config_cache", (0, None, []))
    monkeypatch.setattr("qwenpaw.config.load_config", lambda: config)
    monkeypatch.setattr(agent_context, "load_config", lambda: config)
    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_context, "_get_agent_membership_service", lambda: AgentMembershipService(agents))

    @asynccontextmanager
    async def library_session():
        async with factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE qwenpaw_runtime"))
            yield session

    library = PersonalLibraryService(repository=PostgresPersonalLibraryRepository(
        schema=postgres_test_schema.name, session_factory=library_session,
    ), working_dir=tmp_path)
    monkeypatch.setattr(personal_library, "_get_service", lambda: library)
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
    app.include_router(personal_library.router, prefix="/api")
    app.state.multi_agent_manager = SimpleNamespace(get_agent=AsyncMock(return_value=SimpleNamespace(agent_id="office")))

    import asyncio

    async def seed_users():
        admin = await runtime.users.create_user(
            "admin",
            "admin-password",
            PlatformRole.ADMIN,
        )
        first = await runtime.users.create_user(
            "member",
            "member-password",
            PlatformRole.MEMBER,
        )
        second = await runtime.users.create_user("member-b", "member-b-password", PlatformRole.MEMBER)
        await agents.register_owner(
            agent=LegacyAgentRecord("office", "Office", "", str(tmp_path), "active"), owner_user_id=admin.id,
        )
        actor = ActorContext(admin.id, ActorType.USER, PlatformRole.ADMIN, True, "test-seed")
        for member in (first, second):
            await agents.grant_member(agent_key="office", user_id=member.id, role=AgentResourceRole.USER, actor=actor)
        async with factory.begin() as session:
            await session.execute(text(f'GRANT USAGE ON SCHEMA "{postgres_test_schema.name}" TO qwenpaw_runtime'))
        return actor, second.id

    admin_actor, second_id = asyncio.run(seed_users())

    async def concurrent_members():
        from httpx import ASGITransport, AsyncClient

        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as first,
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as second,
        ):
            async def login_then_read(client, name):
                reply = await client.post("/api/auth/login", json={
                    "username": name, "password": f"{name}-password",
                })
                assert reply.status_code == 200
                headers = {"Authorization": f"Bearer {reply.json()['token']}", "X-Agent-Id": "office"}
                me = await client.get("/api/me", headers=headers)
                assert me.json()["user"]["username"] == name
                return headers

            first_headers, second_headers = await asyncio.gather(
                login_then_read(first, "member"), login_then_read(second, "member-b"),
            )
            path = "/api/console/personal-library/documents"
            async def create(client, headers, content, filename="shared-name.txt"):
                return await client.post(f"{path}/text", headers=headers, json={"path": filename, "content": content})

            clients = [(first, first_headers, "A"), (second, second_headers, "B")]
            saved = await asyncio.gather(*(create(*params) for params in clients))
            assert [reply.status_code for reply in saved] == [201, 201]
            assert saved[0].json()["id"] != saved[1].json()["id"]
            for (client, headers, content), reply in zip(clients, saved):
                listed = await client.get(path, headers=headers)
                assert [item["id"] for item in listed.json()] == [reply.json()["id"]]
                opened = await client.get(f"{path}/{reply.json()['id']}/text", headers=headers)
                assert opened.json()["content"] == content
            concurrent = await asyncio.gather(*(
                create(first, first_headers, content, "one-writer.txt") for content in ("first", "second")
            ))
            assert sorted(reply.status_code for reply in concurrent) == [201, 409]
            winner = next(i for i, reply in enumerate(concurrent) if reply.status_code == 201)
            opened = await first.get(f"{path}/{concurrent[winner].json()['id']}/text", headers=first_headers)
            assert opened.json()["content"] == ("first", "second")[winner]

            await agents.revoke_member(agent_key="office", user_id=second_id, actor=admin_actor)
            assert (await second.get(path, headers=second_headers)).status_code == 403
            assert (await first.get(path, headers=first_headers)).status_code == 200
            logout, still_active = await asyncio.gather(
                first.post("/api/auth/logout"), second.get("/api/me", headers=second_headers),
            )
            assert logout.status_code == 200
            assert still_active.json()["user"]["username"] == "member-b"
            assert (await first.get("/api/me", headers=first_headers)).status_code == 401

    asyncio.run(concurrent_members())

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
