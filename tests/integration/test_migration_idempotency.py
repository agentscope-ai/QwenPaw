"""分领域迁移器的幂等、事务与报告契约。"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_migrations import _alembic_config

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.chats.session import session_relative_paths
from qwenpaw.migration.agents import migrate_agents
from qwenpaw.migration.conversations import migrate_conversations
from qwenpaw.migration.identity import migrate_identity
from qwenpaw.migration.messages import migrate_messages
from qwenpaw.migration.skills import migrate_skills
from qwenpaw.migration.inbox import migrate_inbox
from qwenpaw.migration.mcp import migrate_mcp
from qwenpaw.migration.remaining import migrate_cron, migrate_tokens


@pytest.mark.asyncio
@pytest.mark.integration
async def test_identity_migration_is_idempotent_and_reports_hashes(
    postgres_test_schema,
    tmp_path,
) -> None:
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    (secret_dir / "auth.json").write_text(
        json.dumps(
            {
                "user": {
                    "username": "legacy-admin",
                    "password_hash": "a" * 64,
                    "password_salt": "b" * 32,
                },
                "jwt_secret": "must-not-appear-in-report",
            }
        ),
        encoding="utf-8",
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
        first = await migrate_identity(
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        second = await migrate_identity(
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        async with factory() as session:
            count = await session.scalar(
                text(
                    f'SELECT count(*) FROM "{postgres_test_schema.name}".users'
                )
            )

        assert count == 1
        assert first.status == "completed"
        assert first.inserted_count == 1
        assert first.unchanged_count == 0
        assert second.status == "completed"
        assert second.inserted_count == 0
        assert second.unchanged_count == 1
        assert first.source_hash == second.source_hash
        assert first.target_hash == second.target_hash
        assert first.target_count == second.target_count == 1
        assert first.execution_order == 1
        assert first.transaction_committed is True
        assert "must-not-appear-in-report" not in first.model_dump_json()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_identity_migration_rejects_invalid_legacy_credentials_without_write(
    postgres_test_schema,
    tmp_path,
) -> None:
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    (secret_dir / "auth.json").write_text(
        '{"user":{"username":"legacy-admin","password_hash":"invalid"}}',
        encoding="utf-8",
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
        report = await migrate_identity(
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        async with factory() as session:
            count = await session.scalar(
                text(
                    f'SELECT count(*) FROM "{postgres_test_schema.name}".users'
                )
            )

        assert count == 0
        assert report.status == "rejected"
        assert report.transaction_committed is False
        assert report.rejected[0].code == "invalid_legacy_credential"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_identity_migration_does_not_overwrite_conflicting_username(
    postgres_test_schema,
    tmp_path,
) -> None:
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    (secret_dir / "auth.json").write_text(
        json.dumps(
            {
                "user": {
                    "username": "legacy-admin",
                    "password_hash": "a" * 64,
                    "password_salt": "b" * 32,
                }
            }
        ),
        encoding="utf-8",
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

    users = f'"{postgres_test_schema.name}".users'
    try:
        async with factory.begin() as session:
            await session.execute(
                text(
                    f"INSERT INTO {users} "
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (gen_random_uuid(),'legacy-admin','different',"
                    "'active','admin')"
                )
            )
        report = await migrate_identity(
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        async with factory() as session:
            stored_hash = await session.scalar(
                text(
                    f"SELECT password_hash FROM {users} "
                    "WHERE username='legacy-admin'"
                )
            )

        assert stored_hash == "different"
        assert report.status == "rejected"
        assert report.inserted_count == 0
        assert report.rejected[0].code == "target_identity_conflict"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_empty_identity_source_reports_existing_target_total(
    postgres_test_schema,
    tmp_path,
) -> None:
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    secret_dir = tmp_path / "missing-secret"
    engine = create_async_engine(
        postgres_test_schema.async_url(),
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    users = f'"{postgres_test_schema.name}".users'
    try:
        async with factory.begin() as session:
            await session.execute(
                text(
                    f"INSERT INTO {users} "
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (gen_random_uuid(),'existing-admin','hash',"
                    "'active','admin')"
                )
            )
        report = await migrate_identity(
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )

        assert report.status == "empty"
        assert report.source_count == 0
        assert report.target_count == 1
        assert report.inserted_count == 0
        assert report.source_hash == (
            "sha256:e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855"
        )
    finally:
        await engine.dispose()


def _write_legacy_agents(working_dir, *, include_secret: bool = False) -> None:
    workspaces = working_dir / "workspaces"
    profiles = {}
    for agent_id in ("default", "helper"):
        workspace = workspaces / agent_id
        workspace.mkdir(parents=True)
        profiles[agent_id] = {
            "id": agent_id,
            "workspace_dir": str(workspace),
            "enabled": True,
        }
        agent = {
            "id": agent_id,
            "name": agent_id.title(),
            "description": f"{agent_id} description",
            "workspace_dir": str(workspace),
            "running": {"max_iters": 20},
        }
        if include_secret:
            agent["mcp"] = {"clients": {"demo": {"api_key": "raw-secret"}}}
        (workspace / "agent.json").write_text(
            json.dumps(agent),
            encoding="utf-8",
        )
    (working_dir / "config.json").write_text(
        json.dumps(
            {
                "agents": {
                    "active_agent": "default",
                    "agent_order": ["default", "helper"],
                    "profiles": profiles,
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agent_migration_is_idempotent_and_redacts_secrets(
    postgres_test_schema,
    tmp_path,
) -> None:
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    working_dir = tmp_path / "working"
    secret_dir = tmp_path / "secret"
    working_dir.mkdir()
    secret_dir.mkdir()
    _write_legacy_agents(working_dir, include_secret=True)
    engine = create_async_engine(
        postgres_test_schema.async_url(),
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    users = f'"{postgres_test_schema.name}".users'
    revisions = f'"{postgres_test_schema.name}".agent_config_revisions'
    try:
        async with factory.begin() as session:
            await session.execute(
                text(
                    f"INSERT INTO {users} "
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (gen_random_uuid(),'admin','hash','active','admin')"
                )
            )
        first = await migrate_agents(
            working_dir=working_dir,
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        second = await migrate_agents(
            working_dir=working_dir,
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        async with factory() as session:
            agent_count = await session.scalar(
                text(f'SELECT count(*) FROM "{postgres_test_schema.name}".agents')
            )
            revision_count = await session.scalar(
                text(f"SELECT count(*) FROM {revisions}")
            )
            raw_config = await session.scalar(
                text(
                    f"SELECT structured_config::text FROM {revisions} "
                    "WHERE structured_config::text LIKE '%secret_ref%' LIMIT 1"
                )
            )

        assert agent_count == revision_count == 2
        assert first.inserted_count == 2
        assert first.updated_count == 2
        assert second.inserted_count == second.updated_count == 0
        assert second.unchanged_count == 2
        assert first.target_hash == second.target_hash
        assert "raw-secret" not in raw_config
        assert "secret_ref" in raw_config
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agent_migration_preserves_existing_owner_and_rejects_revision_conflict(
    postgres_test_schema,
    tmp_path,
) -> None:
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    working_dir = tmp_path / "working"
    secret_dir = tmp_path / "secret"
    working_dir.mkdir()
    secret_dir.mkdir()
    _write_legacy_agents(working_dir)
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
        first = await migrate_agents(
            working_dir=working_dir,
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        assert first.status == "rejected"
        assert first.rejected[0].code == "missing_target_admin"
        async with factory.begin() as session:
            user_id = await session.scalar(
                text(
                    f'INSERT INTO "{postgres_test_schema.name}".users '
                    "(id,username,password_hash,status,platform_role) VALUES "
                    "(gen_random_uuid(),'admin','hash','active','admin') RETURNING id"
                )
            )
        migrated = await migrate_agents(
            working_dir=working_dir,
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        assert migrated.inserted_count == 2
        async with factory.begin() as session:
            await session.execute(
                text(
                    f'UPDATE "{postgres_test_schema.name}".agent_config_revisions '
                    "SET content_hash='manual-change' WHERE revision=1"
                )
            )
        conflicted = await migrate_agents(
            working_dir=working_dir,
            secret_dir=secret_dir,
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        async with factory() as session:
            owners = (
                await session.execute(
                    text(
                        f'SELECT DISTINCT owner_user_id FROM "{postgres_test_schema.name}".agents'
                    )
                )
            ).scalars().all()

        assert owners == [user_id]
        assert conflicted.inserted_count == 0
        assert conflicted.updated_count == 0
        assert {item.code for item in conflicted.rejected} == {
            "target_config_conflict"
        }
    finally:
        await engine.dispose()


def _write_legacy_chats(working_dir, *, agent_key: str, user_id, chat_id) -> None:
    workspace = working_dir / "workspaces" / agent_key
    workspace.mkdir(parents=True)
    timestamp = datetime(2026, 9, 8, tzinfo=UTC).isoformat()
    (workspace / "chats.json").write_text(
        json.dumps(
            {
                "version": 1,
                "chats": [
                    {
                        "id": str(chat_id),
                        "name": "Legacy chat",
                        "session_id": "console:legacy",
                        "user_id": str(user_id),
                        "channel": "console",
                        "created_at": timestamp,
                        "updated_at": timestamp,
                        "status": "idle",
                        "pinned": False,
                        "archived_at": None,
                        "source": "chat",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_legacy_messages(working_dir, *, agent_key: str, user_id) -> list:
    timestamp = datetime(2026, 9, 8).isoformat()
    messages = [
        {
            "id": str(uuid4()),
            "role": "user",
            "created_at": timestamp,
            "content": [{"type": "text", "text": "legacy question"}],
        },
        {
            "id": str(uuid4()),
            "role": "assistant",
            "created_at": timestamp,
            "content": [{"type": "text", "text": "legacy answer"}],
        },
    ]
    relative = next(
        path
        for path in session_relative_paths(
            "console:legacy", str(user_id), "console"
        )
        if path.startswith("console/")
    )
    path = working_dir / "workspaces" / agent_key / "sessions" / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"agent": {"state": {"context": messages}}}),
        encoding="utf-8",
    )
    return messages


@pytest.mark.asyncio
@pytest.mark.integration
async def test_conversation_migration_is_idempotent(postgres_test_schema, tmp_path):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    user_id = uuid4()
    chat_id = uuid4()
    _write_legacy_chats(
        working_dir,
        agent_key="default",
        user_id=user_id,
        chat_id=chat_id,
    )
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    schema = postgres_test_schema.name
    try:
        async with factory.begin() as session:
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,'owner','hash','active','member')"
                ),
                {"id": user_id},
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agents '
                    "(id,owner_user_id,name,status,visibility,default_model_mode,"
                    "draft_workspace_key) VALUES "
                    "(:id,:owner,'Default','active','private','inherited','default')"
                ),
                {"id": agent_database_id("default"), "owner": user_id},
            )
        first = await migrate_conversations(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )
        second = await migrate_conversations(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )
        assert first.inserted_count == 1
        assert second.inserted_count == 0
        assert second.unchanged_count == 1
        assert first.target_hash == second.target_hash
        assert first.execution_order == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_conversation_migration_preserves_conflicting_target(
    postgres_test_schema, tmp_path
):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    user_id = uuid4()
    chat_id = uuid4()
    _write_legacy_chats(
        working_dir,
        agent_key="default",
        user_id=user_id,
        chat_id=chat_id,
    )
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    schema = postgres_test_schema.name
    agent_id = agent_database_id("default")
    try:
        async with factory.begin() as session:
            await session.execute(
                text(f'INSERT INTO "{schema}".users (id,username,password_hash,status,platform_role) VALUES (:id,\'owner\',\'hash\',\'active\',\'member\')'),
                {"id": user_id},
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agents '
                    "(id,owner_user_id,name,status,visibility,default_model_mode,"
                    "draft_workspace_key) VALUES "
                    "(:id,:owner,'Default','active','private','inherited','default')"
                ),
                {"id": agent_id, "owner": user_id},
            )
            await session.execute(
                text(f'INSERT INTO "{schema}".conversations (id,agent_id,owner_user_id,title,status,created_at,updated_at) VALUES (:id,:agent,:owner,\'Target title\',\'active\',:at,:at)'),
                {"id": chat_id, "agent": agent_id, "owner": user_id, "at": datetime(2026, 9, 8, tzinfo=UTC)},
            )
        report = await migrate_conversations(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )
        async with factory() as session:
            title = await session.scalar(
                text(f'SELECT title FROM "{schema}".conversations WHERE id=:id'),
                {"id": chat_id},
            )
        assert title == "Target title"
        assert report.status == "rejected"
        assert report.rejected[0].code == "target_conversation_conflict"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_message_migration_is_idempotent(postgres_test_schema, tmp_path):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    user_id = uuid4()
    chat_id = uuid4()
    _write_legacy_chats(
        working_dir,
        agent_key="default",
        user_id=user_id,
        chat_id=chat_id,
    )
    _write_legacy_messages(working_dir, agent_key="default", user_id=user_id)
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    schema = postgres_test_schema.name
    try:
        async with factory.begin() as session:
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,'owner','hash','active','member')"
                ),
                {"id": user_id},
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agents '
                    "(id,owner_user_id,name,status,visibility,default_model_mode,"
                    "draft_workspace_key) VALUES "
                    "(:id,:owner,'Default','active','private','inherited','default')"
                ),
                {"id": agent_database_id("default"), "owner": user_id},
            )
        await migrate_conversations(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )
        first = await migrate_messages(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )
        second = await migrate_messages(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )

        assert first.inserted_count == 2
        assert first.target_count == 2
        assert second.inserted_count == 0
        assert second.unchanged_count == 2
        assert first.target_hash == second.target_hash
        assert first.execution_order == 4
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_message_migration_preserves_existing_history(
    postgres_test_schema, tmp_path
):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    user_id = uuid4()
    chat_id = uuid4()
    _write_legacy_chats(
        working_dir,
        agent_key="default",
        user_id=user_id,
        chat_id=chat_id,
    )
    _write_legacy_messages(working_dir, agent_key="default", user_id=user_id)
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    schema = postgres_test_schema.name
    agent_id = agent_database_id("default")
    target_message_id = uuid4()
    try:
        async with factory.begin() as session:
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,'owner','hash','active','member')"
                ),
                {"id": user_id},
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agents '
                    "(id,owner_user_id,name,status,visibility,default_model_mode,"
                    "draft_workspace_key) VALUES "
                    "(:id,:owner,'Default','active','private','inherited','default')"
                ),
                {"id": agent_id, "owner": user_id},
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".conversations '
                    "(id,agent_id,owner_user_id,title,status,created_at,updated_at) "
                    "VALUES (:id,:agent,:owner,'Target','active',:at,:at)"
                ),
                {
                    "id": chat_id,
                    "agent": agent_id,
                    "owner": user_id,
                    "at": datetime(2026, 9, 8, tzinfo=UTC),
                },
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".messages '
                    "(id,conversation_id,sequence,role,message_type,content,status,"
                    "created_by,created_at) VALUES "
                    "(:id,:conversation,1,'user','message',CAST(:content AS jsonb),"
                    "'completed',:owner,:at)"
                ),
                {
                    "id": target_message_id,
                    "conversation": chat_id,
                    "content": json.dumps({"text": "target history"}),
                    "owner": user_id,
                    "at": datetime(2026, 9, 8, tzinfo=UTC),
                },
            )
        report = await migrate_messages(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )
        async with factory() as session:
            identifiers = (
                await session.execute(
                    text(f'SELECT id FROM "{schema}".messages ORDER BY sequence')
                )
            ).scalars().all()

        assert identifiers == [target_message_id]
        assert report.status == "rejected"
        assert report.inserted_count == 0
        assert report.rejected[0].code == "target_message_history_conflict"
    finally:
        await engine.dispose()


def _write_legacy_skill(working_dir, *, agent_key: str, enabled: bool) -> None:
    workspace = working_dir / "workspaces" / agent_key
    skill = workspace / "skills" / "example-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Example skill\n", encoding="utf-8")
    (workspace / "skill.json").write_text(
        json.dumps(
            {
                "schema_version": "workspace-skill-manifest.v1",
                "skills": {
                    "example-skill": {
                        "enabled": enabled,
                        "detached": False,
                        "config": {"language": "zh-CN"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_skill_migration_is_idempotent(postgres_test_schema, tmp_path):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    _write_legacy_skill(working_dir, agent_key="default", enabled=True)
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    schema = postgres_test_schema.name
    agent_id = agent_database_id("default")
    try:
        async with factory.begin() as session:
            user_id = await session.scalar(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) VALUES "
                    "(gen_random_uuid(),'owner','hash','active','member') RETURNING id"
                )
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agents '
                    "(id,owner_user_id,name,status,visibility,default_model_mode,"
                    "draft_workspace_key) VALUES "
                    "(:id,:owner,'Default','active','private','inherited','default')"
                ),
                {"id": agent_id, "owner": user_id},
            )
        first = await migrate_skills(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )
        second = await migrate_skills(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )

        assert first.inserted_count == 1
        assert second.inserted_count == 0
        assert second.unchanged_count == 1
        assert first.target_hash == second.target_hash
        assert first.execution_order == 5
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_skill_migration_preserves_existing_governance(
    postgres_test_schema, tmp_path
):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    _write_legacy_skill(working_dir, agent_key="default", enabled=True)
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    schema = postgres_test_schema.name
    agent_id = agent_database_id("default")
    try:
        async with factory.begin() as session:
            user_id = await session.scalar(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) VALUES "
                    "(gen_random_uuid(),'owner','hash','active','member') RETURNING id"
                )
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agents '
                    "(id,owner_user_id,name,status,visibility,default_model_mode,"
                    "draft_workspace_key) VALUES "
                    "(:id,:owner,'Default','active','private','inherited','default')"
                ),
                {"id": agent_id, "owner": user_id},
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agent_skills '
                    "(id,agent_id,name,content_key,enabled,detached,config) VALUES "
                    "(gen_random_uuid(),:agent,'example-skill','skills/example-skill',"
                    "false,false,'{}')"
                ),
                {"agent": agent_id},
            )
        report = await migrate_skills(
            working_dir=working_dir,
            schema=schema,
            session_factory=session_factory,
        )
        async with factory() as session:
            enabled = await session.scalar(
                text(
                    f'SELECT enabled FROM "{schema}".agent_skills '
                    "WHERE agent_id=:agent AND name='example-skill'"
                ),
                {"agent": agent_id},
            )

        assert enabled is False
        assert report.status == "rejected"
        assert report.inserted_count == 0
        assert report.rejected[0].code == "target_agent_skill_conflict"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_remaining_domain_migrations_are_safe_and_idempotent(
    postgres_test_schema, tmp_path
):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    working_dir = tmp_path / "working"
    workspace = working_dir / "workspaces" / "default"
    workspace.mkdir(parents=True)
    (workspace / "agent.json").write_text(
        json.dumps({"mcp": {"clients": {"search": {
            "name": "Search", "enabled": False, "transport": "stdio",
            "command": "npx", "args": ["server"], "env": {}, "headers": {},
        }}}}), encoding="utf-8"
    )
    (workspace / "jobs.json").write_text(
        json.dumps({"version": 2, "jobs": []}), encoding="utf-8"
    )
    user_id, event_id = uuid4(), uuid4()
    (working_dir / "inbox_events.json").write_text(json.dumps([{
        "id": str(event_id), "recipient_user_id": str(user_id),
        "agent_id": "default", "source_type": "memory", "source_id": "dream",
        "event_type": "result", "status": "success", "severity": "info",
        "title": "Done", "body": "Body", "payload": {}, "read": True,
        "created_at": datetime(2026, 9, 8, tzinfo=UTC).timestamp(),
    }]), encoding="utf-8")
    (working_dir / "token_usage.json").write_text(json.dumps({
        "2026-09-08": {"provider:model": {
            "provider_id": "provider", "model_name": "model",
            "prompt_tokens": 1, "completion_tokens": 1, "call_count": 1,
        }}
    }), encoding="utf-8")
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    schema = postgres_test_schema.name
    try:
        async with factory.begin() as session:
            await session.execute(text(
                f'INSERT INTO "{schema}".users '
                "(id,username,password_hash,status,platform_role) VALUES "
                "(:id,'owner','hash','active','member')"
            ), {"id": user_id})
            await session.execute(text(
                f'INSERT INTO "{schema}".agents '
                "(id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) "
                "VALUES (:id,:owner,'Default','active','private','inherited','default')"
            ), {"id": agent_database_id("default"), "owner": user_id})
        mcp_first = await migrate_mcp(working_dir=working_dir, schema=schema, session_factory=session_factory)
        inbox_first = await migrate_inbox(working_dir=working_dir, schema=schema, session_factory=session_factory)
        mcp_second = await migrate_mcp(working_dir=working_dir, schema=schema, session_factory=session_factory)
        inbox_second = await migrate_inbox(working_dir=working_dir, schema=schema, session_factory=session_factory)
        cron = await migrate_cron(working_dir=working_dir, schema=schema, session_factory=session_factory)
        tokens = await migrate_tokens(working_dir=working_dir, schema=schema, session_factory=session_factory)

        assert (mcp_first.inserted_count, mcp_second.unchanged_count) == (1, 1)
        assert (inbox_first.inserted_count, inbox_second.unchanged_count) == (1, 1)
        assert mcp_first.target_hash == mcp_second.target_hash
        assert inbox_first.target_hash == inbox_second.target_hash
        assert cron.status == "empty"
        assert tokens.status == "rejected"
        assert tokens.rejected[0].code == "missing_usage_attribution"
        async with factory() as session:
            assert await session.scalar(text(f'SELECT count(*) FROM "{schema}".agent_drivers')) == 1
            assert await session.scalar(text(f'SELECT count(*) FROM "{schema}".notifications')) == 1
            assert await session.scalar(text(f'SELECT count(*) FROM "{schema}".notification_receipts WHERE read_at IS NOT NULL')) == 1
            assert await session.scalar(text(f'SELECT count(*) FROM "{schema}".usage_records')) == 0
    finally:
        await engine.dispose()
