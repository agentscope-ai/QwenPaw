"""Isolated PostgreSQL tests for metadata import and setting transactions."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool


@dataclass
class GovernanceDatabase:
    schema: str
    dsn: str = field(repr=False)

    def __iter__(self):
        yield self.schema
        yield self.dsn


@pytest.fixture
def governance_database(postgres_test_schema):
    dsn = postgres_test_schema.async_url()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", dsn)
    config.attributes["target_schema"] = postgres_test_schema.name
    command.upgrade(config, "head")
    return GovernanceDatabase(postgres_test_schema.name, dsn)


@pytest.mark.asyncio
async def test_import_keeps_grants_status_and_settings_are_versioned(
    governance_database,
):
    from qwenpaw.models.repository import PostgresModelRepository

    schema, dsn = governance_database
    engine = create_async_engine(dsn, poolclass=NullPool)
    factory = async_sessionmaker(engine)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    admin, user = uuid4(), uuid4()
    try:
        async with session_factory() as session:
            for uid, name, role in [
                (admin, "admin", "admin"),
                (user, "user", "member"),
            ]:
                await session.execute(
                    text(
                        f"INSERT INTO \"{schema}\".users (id,username,password_hash,status,platform_role) VALUES (:id,:name,'x','active',:role)"
                    ),
                    {"id": uid, "name": name, "role": role},
                )
        from qwenpaw.models.governance import ModelGovernanceService
        from tests.unit.models.test_governance import Manager, actor
        from qwenpaw.identity.models import PlatformRole

        rows = await ModelGovernanceService(None, Manager()).preview_import(
            actor(PlatformRole.ADMIN), Manager()
        )
        repo = PostgresModelRepository(schema=schema, session_factory=session_factory)
        assert await repo.get_status() == {"enforced": False, "version": 0}
        await repo.import_metadata(rows, admin)
        mid = rows[0]["id"]
        await repo.set_user_grant(mid, user, True, admin)
        granted = (await repo.list_models())[0]
        assert granted["user_grants"] == [
            {"user_id": str(user), "username": "user", "enabled": True}
        ]
        await repo.set_model_status(mid, False)
        await repo.import_metadata(rows, admin)
        assert (await repo.list_models())[0]["status"] == "disabled"
        assert mid in await repo.allowed_models(user, None)
        assert await repo.set_enforced(True, 0, "test", admin) == {
            "enforced": True,
            "version": 1,
        }
        with pytest.raises(ValueError, match="version_conflict"):
            await repo.set_enforced(False, 0, "stale", admin)
        async with session_factory() as session:
            assert (
                await session.execute(
                    text(f'SELECT count(*) FROM "{schema}".system_setting_revisions')
                )
            ).scalar_one() == 1
        from datetime import UTC, datetime
        from qwenpaw.app.chats.repo.postgres_repo import PostgresConversationRepository
        from qwenpaw.app.chats.repo.conversation import ConversationRecord
        from qwenpaw.access.agent_repository import agent_database_id
        from uuid import UUID

        agent_id = agent_database_id("fixture-agent")
        async with session_factory() as session:
            await session.execute(
                text(
                    f"INSERT INTO \"{schema}\".agents (id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) VALUES (:id,:owner,'Agent','active','private','inherit','fixture')"
                ),
                {"id": agent_id, "owner": user},
            )
        conversations = PostgresConversationRepository(
            schema=schema, session_factory=session_factory
        )
        now = datetime.now(UTC)
        record = ConversationRecord(
            id=uuid4(),
            agent_id=agent_id,
            owner_user_id=user,
            title="Keep",
            status="active",
            created_at=now,
            updated_at=now,
        )
        await conversations.with_user(user).create_conversation(record)
        selected = await conversations.with_user(user).set_model_override(
            record.id,
            expected_agent_id=agent_id,
            model_override_id=UUID(mid),
            updated_at=now,
        )
        assert selected.model_override_id == UUID(mid) and selected.title == "Keep"
        assert await repo.references([mid]) == [
            {"conversation_id": str(record.id), "agent_id": str(agent_id)}
        ]
        async with session_factory() as session:
            await session.execute(
                text(f'GRANT USAGE ON SCHEMA "{schema}" TO qwenpaw_runtime')
            )
            await session.execute(
                text(
                    f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO qwenpaw_runtime'
                )
            )

        @asynccontextmanager
        async def restricted_factory():
            async with factory.begin() as session:
                await session.execute(text("SET LOCAL ROLE qwenpaw_runtime"))
                yield session

        restricted = PostgresModelRepository(
            schema=schema, session_factory=restricted_factory
        )
        with pytest.raises(ValueError, match="model_reference_authority_unavailable"):
            await restricted.references([mid])
        assert (
            await conversations.with_user(admin).set_model_override(
                record.id,
                expected_agent_id=agent_id,
                model_override_id=None,
                updated_at=now,
            )
            is None
        )
        assert (
            await conversations.with_user(user).set_model_override(
                record.id,
                expected_agent_id=uuid4(),
                model_override_id=None,
                updated_at=now,
            )
            is None
        )
        assert (
            await conversations.with_user(user).get_conversation(record.id)
        ).model_override_id == UUID(mid)
        assert (
            await conversations.with_user(user).set_model_override(
                record.id,
                expected_agent_id=agent_id,
                model_override_id=None,
                updated_at=now,
            )
        ).model_override_id is None
        await repo.set_user_grant(mid, user, False, admin)
        async with session_factory() as session:
            await session.execute(
                text(
                    f"INSERT INTO \"{schema}\".model_grants (id,model_id,subject_type,subject_id,enabled,created_by) VALUES (:id,:model,'agent',:agent,true,:actor)"
                ),
                {"id": uuid4(), "model": UUID(mid), "agent": agent_id, "actor": admin},
            )
        assert mid in await repo.allowed_models(user, "fixture-agent")
        assert mid not in await repo.allowed_models(admin, "fixture-agent")
        with pytest.raises(ValueError, match="user_unavailable"):
            await repo.set_user_grant(mid, uuid4(), True, admin)
    finally:
        await engine.dispose()
