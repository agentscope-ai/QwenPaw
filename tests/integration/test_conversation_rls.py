# -*- coding: utf-8 -*-
"""Task 5.3-A PostgreSQL 会话所有权与 RLS 集成契约。"""

from __future__ import annotations

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

from qwenpaw.app.chats.repo import PostgresConversationRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(postgres_test_schema) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    return config


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_role_cannot_cross_read_owned_conversations(
    postgres_test_schema,
) -> None:
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    schema = postgres_test_schema.name
    engine = create_async_engine(
        postgres_test_schema.async_url(),
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_a, user_b = uuid4(), uuid4()
    agent_a, agent_b = uuid4(), uuid4()
    chat_a, chat_b = uuid4(), uuid4()

    async with factory.begin() as session:
        await session.execute(
            text(f'GRANT USAGE ON SCHEMA "{schema}" TO qwenpaw_runtime')
        )
        await session.execute(
            text(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" '
                "TO qwenpaw_runtime"
            )
        )
        for user_id, username in ((user_a, "rls-a"), (user_b, "rls-b")):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,:username,'x','active','member')"
                ),
                {"id": user_id, "username": username},
            )
        for agent_id, owner_id, name in (
            (agent_a, user_a, "Agent A"),
            (agent_b, user_b, "Agent B"),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agents '
                    "(id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) "
                    "VALUES (:id,:owner,:name,'active','private','inherit',:workspace)"
                ),
                {
                    "id": agent_id,
                    "owner": owner_id,
                    "name": name,
                    "workspace": f"workspaces/{agent_id}",
                },
            )
        for chat_id, agent_id, owner_id, title in (
            (chat_a, agent_a, user_a, "A private"),
            (chat_b, agent_b, user_b, "B private"),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".conversations '
                    "(id,agent_id,owner_user_id,title,status) "
                    "VALUES (:id,:agent,:owner,:title,'active')"
                ),
                {
                    "id": chat_id,
                    "agent": agent_id,
                    "owner": owner_id,
                    "title": title,
                },
            )

    @asynccontextmanager
    async def runtime_session_factory():
        async with factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE qwenpaw_runtime"))
            yield session

    repository = PostgresConversationRepository(
        schema=schema,
        session_factory=runtime_session_factory,
    )
    try:
        owned = await repository.with_user(user_a).list_conversations_for_user(
            user_id=user_a,
            scope="owned",
        )
        assert [row.conversation.id for row in owned] == [chat_a]
        assert [row.access_role for row in owned] == ["owner"]
        assert await repository.with_user(user_a).get_conversation(chat_b) is None
    finally:
        await engine.dispose()
