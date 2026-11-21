"""独立测试数据库验证历史归属、RLS 与 0024 迁移回滚边界。"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.access.agent_repository import PostgresAgentRepository, agent_database_id
from qwenpaw.app.chats.historical_workspace import OwnerHistoryRepository
from qwenpaw.app.chats.repo.postgres_repo import PostgresConversationRepository
from qwenpaw.persistence.database import set_request_user

ROOT = Path(__file__).resolve().parents[2]


def _config(target):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", target.async_url())
    config.attributes["target_schema"] = target.name
    return config


@pytest.mark.integration
@pytest.mark.asyncio
async def test_owned_history_outlives_agent_access_and_migration_is_reversible(
    postgres_test_schema,
):
    target = postgres_test_schema
    engine = create_async_engine(target.async_url(), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    # A fresh dedicated test container has no pre-provisioned application role.
    async with sessions.begin() as session:
        await session.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='qwenpaw_runtime') THEN
                    CREATE ROLE qwenpaw_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS;
                END IF;
            END $$
        """))
    await asyncio.to_thread(command.upgrade, _config(target), "head")
    schema = target.name
    owner, agent_owner, viewer, outsider = [uuid4() for _ in range(4)]
    agent_key = "history-agent"
    agent_id = agent_database_id(agent_key)
    chat, message, run = [uuid4() for _ in range(3)]

    async with sessions.begin() as session:
        await session.execute(
            text(f'GRANT USAGE ON SCHEMA "{schema}" TO qwenpaw_runtime')
        )
        await session.execute(
            text(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO qwenpaw_runtime'
            )
        )
        for user_id, username, role in (
            (owner, "owner", "member"),
            (agent_owner, "agentowner", "member"),
            (viewer, "viewer", "member"),
            (outsider, "outsider", "admin"),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users (id,username,password_hash,status,platform_role) '
                    "VALUES (:id,:name,'x','active',:role)"
                ),
                {"id": user_id, "name": username, "role": role},
            )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".agents '
                "(id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) "
                "VALUES (:id,:owner,'History Agent','active','shared','inherit',:workspace)"
            ),
            {
                "id": agent_id,
                "owner": agent_owner,
                "workspace": f"workspaces/{agent_key}",
            },
        )
        for member in (owner, viewer):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agent_members (agent_id,user_id,role,granted_by) '
                    "VALUES (:agent,:user,'user',:owner)"
                ),
                {"agent": agent_id, "user": member, "owner": agent_owner},
            )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".conversations (id,agent_id,owner_user_id,title,status) '
                "VALUES (:id,:agent,:owner,'My history','active')"
            ),
            {"id": chat, "agent": agent_id, "owner": owner},
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".conversation_members '
                "(conversation_id,user_id,role,granted_by) VALUES (:chat,:viewer,'viewer',:owner)"
            ),
            {"chat": chat, "viewer": viewer, "owner": owner},
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".runs (id,conversation_id,initiated_by,status,started_at) '
                "VALUES (:run,:chat,:owner,'completed',now())"
            ),
            {"run": run, "chat": chat, "owner": owner},
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".messages '
                "(id,conversation_id,run_id,sequence,role,message_type,content,status,created_by) "
                "VALUES (:id,:chat,:run,1,'assistant','message','{}','completed',:owner)"
            ),
            {"id": message, "chat": chat, "run": run, "owner": owner},
        )

    @asynccontextmanager
    async def runtime_sessions():
        async with sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE qwenpaw_runtime"))
            yield session

    repo = PostgresConversationRepository(
        schema=schema, session_factory=runtime_sessions
    )
    owner_repo, viewer_repo = repo.with_user(owner), repo.with_user(viewer)
    agents = PostgresAgentRepository(schema=schema, session_factory=runtime_sessions)
    historical = OwnerHistoryRepository(repo, user_id=owner, agent_id=agent_id)

    async def writable(user_id):
        async with runtime_sessions() as session:
            await set_request_user(session, user_id)
            return await session.scalar(
                text(f'SELECT "{schema}".qwenpaw_can_write_conversation(:chat)'),
                {"chat": chat},
            )

    async def assert_owned_read_only():
        access = await historical.get_conversation_for_user(
            conversation_id=chat, user_id=owner
        )
        assert access is not None and access.access_role == "owner" and access.read_only
        assert len(await owner_repo.list_messages(chat)) == 1
        assert await owner_repo.has_messages(chat)
        assert await owner_repo.get_message(chat, message) is not None
        assert await owner_repo.get_run(run) is not None
        assert [
            row.conversation.id
            for row in await owner_repo.list_conversations_for_user(
                user_id=owner,
                agent_id=agent_id,
            )
        ] == [chat]
        assert await writable(owner) is False
        async with runtime_sessions() as session:
            await set_request_user(session, owner)
            update = await session.execute(
                text(
                    f"UPDATE \"{schema}\".conversations SET title='forbidden' WHERE id=:chat"
                ),
                {"chat": chat},
            )
            assert update.rowcount == 0

    try:
        assert await writable(owner) is True
        assert await viewer_repo.has_messages(chat)
        assert await writable(viewer) is False
        # Agent owner or platform administrator does not own another user's history.
        for user in (agent_owner, outsider):
            assert (
                await repo.with_user(user).get_conversation_for_user(
                    conversation_id=chat,
                    user_id=user,
                )
                is None
            )
        # Revoked runtime access keeps only the creator's historical reads.
        async with sessions.begin() as session:
            await session.execute(
                text(
                    f'UPDATE "{schema}".agent_members SET revoked_at=now() WHERE agent_id=:agent'
                ),
                {"agent": agent_id},
            )
        await assert_owned_read_only()
        assert not await viewer_repo.has_messages(chat)
        records = await agents.list_historical_accessible(
            agent_keys=[agent_key], user_id=owner
        )
        assert records[agent_key].historical_read_only
        assert (
            await agents.list_historical_accessible(
                agent_keys=[agent_key], user_id=viewer
            )
            == {}
        )
        # No profile / selected Agent is needed to recover the creator's stable chat ID.
        recovered = await agents.get_owned_history_agent(
            conversation_id=chat,
            user_id=owner,
            agent_keys=[],
        )
        assert recovered is not None and recovered.key == agent_key
        assert (
            await agents.get_owned_history_agent(
                conversation_id=chat,
                user_id=outsider,
                agent_keys=[agent_key],
            )
            is None
        )
        for status in ("disabled", "deleted"):
            async with sessions.begin() as session:
                await session.execute(
                    text(
                        f"UPDATE \"{schema}\".agents SET status=:status, visibility='public' WHERE id=:agent"
                    ),
                    {"agent": agent_id, "status": status},
                )
            await assert_owned_read_only()
            assert not await viewer_repo.has_messages(chat)
            assert (
                await viewer_repo.get_conversation_for_user(
                    conversation_id=chat, user_id=viewer
                )
                is None
            )

        await asyncio.to_thread(
            command.downgrade, _config(target), "0023_console_tasks"
        )
        assert (
            await owner_repo.get_conversation_for_user(
                conversation_id=chat, user_id=owner
            )
            is None
        )
        assert (
            await writable(owner) is True
        )  # Exact original 0009 write-helper behavior.
        await asyncio.to_thread(command.upgrade, _config(target), "head")
        await assert_owned_read_only()

        async with sessions.begin() as session:
            await session.execute(
                text(
                    f"UPDATE \"{schema}\".users SET status='disabled' WHERE id=:owner"
                ),
                {"owner": owner},
            )
        assert not await owner_repo.has_messages(chat)
        async with sessions.begin() as session:
            await session.execute(
                text(f"UPDATE \"{schema}\".users SET status='active' WHERE id=:owner"),
                {"owner": owner},
            )
            await session.execute(
                text(
                    f"UPDATE \"{schema}\".conversations SET status='deleted' WHERE id=:chat"
                ),
                {"chat": chat},
            )
        assert not await owner_repo.has_messages(chat)
    finally:
        await engine.dispose()
