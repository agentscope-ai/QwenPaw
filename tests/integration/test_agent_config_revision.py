# -*- coding: utf-8 -*-
"""Task 4.4-A：Agent 结构化配置修订与并发保护。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.access.agent_repository import (
    LegacyAgentRecord,
    PostgresAgentRepository,
)
from qwenpaw.agents.config_repository import (
    AgentConfigVersionConflict,
    PostgresAgentConfigRepository,
)
from qwenpaw.identity.models import PlatformRole
from qwenpaw.identity.repository import PostgresUserRepository
from qwenpaw.identity.service import UserService


def _alembic_config(postgres_test_schema) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    return config


@pytest.mark.integration
@pytest.mark.asyncio
async def test_config_revision_rejects_a_stale_collaborator_save(
    postgres_test_schema,
) -> None:
    """后保存的旧版本不能覆盖先保存的新配置。"""
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
    agents = PostgresAgentRepository(
        schema=postgres_test_schema.name,
        session_factory=session_factory,
    )
    revisions = PostgresAgentConfigRepository(
        schema=postgres_test_schema.name,
        session_factory=session_factory,
    )

    try:
        owner = await users.create_user(
            "config-owner",
            "config-owner-password",
            PlatformRole.MEMBER,
        )
        agent = LegacyAgentRecord(
            key="config-revision-agent",
            name="Config Revision Agent",
            description="",
            workspace_key="workspaces/config-revision-agent",
            status="active",
        )
        await agents.register_owner(agent=agent, owner_user_id=owner.id)

        initial = await revisions.get_current(agent.key)
        assert initial.version == 1

        saved = await revisions.save_revision(
            agent_key=agent.key,
            expected_version=initial.version,
            structured_config={"running": {"history_max_length": 20}},
            changed_by=owner.id,
        )
        assert saved.version == 2

        unchanged = await revisions.save_revision(
            agent_key=agent.key,
            expected_version=saved.version,
            structured_config={"running": {"history_max_length": 20}},
            changed_by=owner.id,
        )
        assert unchanged.version == 2

        with pytest.raises(AgentConfigVersionConflict) as conflict:
            await revisions.save_revision(
                agent_key=agent.key,
                expected_version=initial.version,
                structured_config={"running": {"history_max_length": 99}},
                changed_by=owner.id,
            )

        assert conflict.value.expected_version == 1
        assert conflict.value.current_version == 2
        current = await revisions.get_current(agent.key)
        assert current.version == 2
        assert current.structured_config == {
            "running": {"history_max_length": 20}
        }
    finally:
        await engine.dispose()
