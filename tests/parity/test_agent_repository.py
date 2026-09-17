# -*- coding: utf-8 -*-
"""Agent 文件目录与 PostgreSQL 归属元数据的组合契约。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AgentMembershipService
from qwenpaw.access.agent_repository import (
    AgentAccessRecord,
    AgentResourceRole,
    AgentVisibility,
    LegacyAgentRecord,
    LegacyAgentRepository,
    PostgresAgentRepository,
    agent_database_id,
)
from qwenpaw.identity.models import PlatformRole
from qwenpaw.identity.repository import PostgresUserRepository
from qwenpaw.identity.service import UserService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(postgres_test_schema) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    return config


class FakeMetadataRepository:
    """只保存测试所需的归属读取结果。"""

    def __init__(
        self,
        *,
        first_admin_id: UUID,
        access_by_user: dict[UUID, dict[str, AgentAccessRecord]],
        historical_by_user: dict[UUID, dict[str, AgentAccessRecord]] | None = None,
    ) -> None:
        self.first_admin_id = first_admin_id
        self.access_by_user = access_by_user
        self.historical_by_user = historical_by_user or {}

    async def get_first_admin_id(self) -> UUID | None:
        return self.first_admin_id

    async def list_accessible(
        self,
        *,
        agent_keys: list[str],
        user_id: UUID,
    ) -> dict[str, AgentAccessRecord]:
        allowed = self.access_by_user.get(user_id, {})
        return {key: allowed[key] for key in agent_keys if key in allowed}

    async def list_registered_keys(self, agent_keys: list[str]) -> set[str]:
        registered = {key for access in self.access_by_user.values() for key in access}
        return registered.intersection(agent_keys)

    async def list_historical_accessible(
        self,
        *,
        agent_keys: list[str],
        user_id: UUID,
    ) -> dict[str, AgentAccessRecord]:
        allowed = self.historical_by_user.get(user_id, {})
        return {key: allowed[key] for key in agent_keys if key in allowed}


def _actor(user_id: UUID, role: PlatformRole) -> ActorContext:
    return ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="req-agent-repository",
    )


def _legacy_agents() -> list[LegacyAgentRecord]:
    return [
        LegacyAgentRecord(
            key="default",
            name="Default Agent",
            description="",
            workspace_key="workspaces/default",
            status="active",
        ),
        LegacyAgentRecord(
            key="member-agent",
            name="Member Agent",
            description="",
            workspace_key="workspaces/member-agent",
            status="active",
        ),
        LegacyAgentRecord(
            key="other-agent",
            name="Other Agent",
            description="",
            workspace_key="workspaces/other-agent",
            status="active",
        ),
    ]


def test_legacy_repository_preserves_file_order_without_writing() -> None:
    records = _legacy_agents()
    repository = LegacyAgentRepository(lambda: records)

    assert repository.list_agents() == records
    assert [record.key for record in repository.list_agents()] == [
        "default",
        "member-agent",
        "other-agent",
    ]


@pytest.mark.asyncio
async def test_unregistered_legacy_agents_are_previewed_only_for_first_admin() -> None:
    first_admin_id = uuid4()
    second_admin_id = uuid4()
    repository = FakeMetadataRepository(
        first_admin_id=first_admin_id,
        access_by_user={},
    )
    service = AgentMembershipService(repository)

    first_admin_agents = await service.list_accessible(
        actor=_actor(first_admin_id, PlatformRole.ADMIN),
        legacy_agents=_legacy_agents(),
    )
    second_admin_agents = await service.list_accessible(
        actor=_actor(second_admin_id, PlatformRole.ADMIN),
        legacy_agents=_legacy_agents(),
    )

    assert [item.agent.key for item in first_admin_agents] == [
        "default",
        "member-agent",
        "other-agent",
    ]
    assert all(item.role is AgentResourceRole.OWNER for item in first_admin_agents)
    assert all(
        item.registration_state == "legacy_preview" for item in first_admin_agents
    )
    assert second_admin_agents == []


@pytest.mark.asyncio
async def test_list_filters_owner_collaborator_and_user_without_admin_bypass() -> None:
    first_admin_id = uuid4()
    member_id = uuid4()
    other_admin_id = uuid4()
    member_owner = AgentAccessRecord(
        agent_key="member-agent",
        owner_user_id=member_id,
        role=AgentResourceRole.OWNER,
        status="active",
    )
    member_user = AgentAccessRecord(
        agent_key="other-agent",
        owner_user_id=other_admin_id,
        role=AgentResourceRole.USER,
        status="active",
    )
    repository = FakeMetadataRepository(
        first_admin_id=first_admin_id,
        access_by_user={
            member_id: {
                "member-agent": member_owner,
                "other-agent": member_user,
            },
            other_admin_id: {
                "other-agent": AgentAccessRecord(
                    agent_key="other-agent",
                    owner_user_id=other_admin_id,
                    role=AgentResourceRole.OWNER,
                    status="active",
                ),
            },
        },
    )
    service = AgentMembershipService(repository)

    member_agents = await service.list_accessible(
        actor=_actor(member_id, PlatformRole.MEMBER),
        legacy_agents=_legacy_agents(),
    )
    other_admin_agents = await service.list_accessible(
        actor=_actor(other_admin_id, PlatformRole.ADMIN),
        legacy_agents=_legacy_agents(),
    )

    assert [(item.agent.key, item.role.value) for item in member_agents] == [
        ("member-agent", "owner"),
        ("other-agent", "user"),
    ]
    assert [(item.agent.key, item.role.value) for item in other_admin_agents] == [
        ("other-agent", "owner"),
    ]

    first_admin_agents = await service.list_accessible(
        actor=_actor(first_admin_id, PlatformRole.ADMIN),
        legacy_agents=_legacy_agents(),
    )
    assert [item.agent.key for item in first_admin_agents] == ["default"]


@pytest.mark.asyncio
async def test_historical_agent_is_listed_read_only_but_cannot_run() -> None:
    admin_id = uuid4()
    member_id = uuid4()
    historical = AgentAccessRecord(
        agent_key="other-agent",
        owner_user_id=admin_id,
        role=AgentResourceRole.USER,
        status="active",
        visibility=AgentVisibility.PRIVATE,
        historical_read_only=True,
    )
    service = AgentMembershipService(
        FakeMetadataRepository(
            first_admin_id=admin_id,
            access_by_user={},
            historical_by_user={member_id: {"other-agent": historical}},
        )
    )
    actor = _actor(member_id, PlatformRole.MEMBER)

    listed = await service.list_accessible(
        actor=actor,
        legacy_agents=_legacy_agents(),
    )

    assert [(item.agent.key, item.historical_read_only) for item in listed] == [
        ("other-agent", True)
    ]
    with pytest.raises(Exception, match="forbidden"):
        await service.require_role(
            actor=actor,
            agent=_legacy_agents()[2],
            allowed_roles={AgentResourceRole.USER},
        )
    allowed = await service.require_role(
        actor=actor,
        agent=_legacy_agents()[2],
        allowed_roles={AgentResourceRole.USER},
        allow_historical_read_only=True,
    )
    assert allowed.historical_read_only is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_repository_keeps_preview_read_only_and_filters_members(
    postgres_test_schema,
) -> None:
    """真实 PostgreSQL 证明预览零写入、owner/成员过滤和软删除。"""
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

    users = UserService(
        PostgresUserRepository(
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
    )
    repository = PostgresAgentRepository(
        schema=postgres_test_schema.name,
        session_factory=session_factory,
    )
    service = AgentMembershipService(repository)
    legacy_agents = _legacy_agents()

    try:
        admin = await users.create_user(
            "admin",
            "admin-password",
            PlatformRole.ADMIN,
        )
        member = await users.create_user(
            "member",
            "member-password",
            PlatformRole.MEMBER,
        )

        preview = await service.list_accessible(
            actor=_actor(admin.id, PlatformRole.ADMIN),
            legacy_agents=legacy_agents,
        )
        assert [item.registration_state for item in preview] == [
            "legacy_preview",
            "legacy_preview",
            "legacy_preview",
        ]
        async with session_factory() as session:
            count = await session.scalar(
                text(f'SELECT count(*) FROM "{postgres_test_schema.name}".agents')
            )
        assert count == 0

        member_agent = legacy_agents[1]
        await repository.register_owner(
            agent=member_agent,
            owner_user_id=member.id,
        )
        async with session_factory() as session:
            await session.execute(
                text(
                    f'INSERT INTO "{postgres_test_schema.name}".agent_members '
                    "(agent_id, user_id, role, granted_by) "
                    "VALUES (:agent_id, :user_id, 'user', :granted_by)"
                ),
                {
                    "agent_id": agent_database_id(member_agent.key),
                    "user_id": admin.id,
                    "granted_by": member.id,
                },
            )

        member_visible = await service.list_accessible(
            actor=_actor(member.id, PlatformRole.MEMBER),
            legacy_agents=legacy_agents,
        )
        admin_visible = await service.list_accessible(
            actor=_actor(admin.id, PlatformRole.ADMIN),
            legacy_agents=legacy_agents,
        )
        assert [(item.agent.key, item.role.value) for item in member_visible] == [
            ("member-agent", "owner")
        ]
        assert [(item.agent.key, item.role.value) for item in admin_visible] == [
            ("default", "owner"),
            ("member-agent", "user"),
            ("other-agent", "owner"),
        ]

        await repository.set_status("member-agent", "deleted")
        assert (
            await service.list_accessible(
                actor=_actor(member.id, PlatformRole.MEMBER),
                legacy_agents=legacy_agents,
            )
            == []
        )
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_repository_public_share_transfer_and_audit_are_atomic(
    postgres_test_schema,
) -> None:
    """真实 PostgreSQL 覆盖公用可见性、成员恢复、转移和审计事实。"""
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

    users = UserService(
        PostgresUserRepository(
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
    )
    repository = PostgresAgentRepository(
        schema=postgres_test_schema.name,
        session_factory=session_factory,
    )
    agent = _legacy_agents()[1]

    try:
        admin = await users.create_user("admin", "password", PlatformRole.ADMIN)
        owner = await users.create_user("owner", "password", PlatformRole.MEMBER)
        collaborator = await users.create_user(
            "collaborator",
            "password",
            PlatformRole.MEMBER,
        )
        public_user = await users.create_user(
            "public-user",
            "password",
            PlatformRole.MEMBER,
        )
        await repository.register_owner(agent=agent, owner_user_id=owner.id)

        await repository.grant_member(
            agent_key=agent.key,
            user_id=collaborator.id,
            role=AgentResourceRole.COLLABORATOR,
            actor=_actor(owner.id, PlatformRole.MEMBER),
        )
        assert (await repository.get_governance(agent.key)).visibility is (
            AgentVisibility.SHARED
        )

        await repository.set_publication(
            agent_key=agent.key,
            published=True,
            actor=_actor(admin.id, PlatformRole.ADMIN),
        )
        public_access = await repository.get_accessible(
            agent_key=agent.key,
            user_id=public_user.id,
        )
        assert public_access is not None
        assert public_access.role is AgentResourceRole.USER
        assert public_access.visibility is AgentVisibility.PUBLIC

        await repository.record_chat_created(
            agent_key=agent.key,
            user_id=public_user.id,
        )
        await repository.set_publication(
            agent_key=agent.key,
            published=False,
            actor=_actor(admin.id, PlatformRole.ADMIN),
        )
        assert await repository.get_accessible(
            agent_key=agent.key,
            user_id=public_user.id,
        ) is None
        historical_access = await repository.list_historical_accessible(
            agent_keys=[agent.key],
            user_id=public_user.id,
        )
        assert historical_access[agent.key].historical_read_only is True

        await repository.transfer_owner(
            agent_key=agent.key,
            new_owner_user_id=collaborator.id,
            actor=_actor(owner.id, PlatformRole.MEMBER),
        )
        governance = await repository.get_governance(agent.key)
        assert governance.owner_user_id == collaborator.id
        members = await repository.list_members(agent.key)
        assert [(member.user_id, member.role) for member in members] == [
            (owner.id, AgentResourceRole.COLLABORATOR),
        ]

        async with session_factory() as session:
            audit_actions = (
                await session.execute(
                    text(
                        f'SELECT action FROM "{postgres_test_schema.name}".audit_logs '
                        "ORDER BY created_at, action"
                    )
                )
            ).scalars().all()
        assert set(audit_actions) == {
            "agent.member.grant",
            "agent.owner.transfer",
            "agent.publication.publish",
            "agent.publication.revoke",
        }
    finally:
        await engine.dispose()
