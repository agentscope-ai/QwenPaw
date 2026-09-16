# -*- coding: utf-8 -*-
"""Task 5.3-B 会话分享候选、添加与撤销集成契约。"""

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

from qwenpaw.app.chats.repo import (
    ConversationShareEligibilityError,
    PostgresConversationRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(postgres_test_schema) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    return config


@pytest.mark.integration
@pytest.mark.asyncio
async def test_owner_shares_only_with_current_agent_eligible_user(
    postgres_test_schema,
) -> None:
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    schema = postgres_test_schema.name
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner_id, eligible_id, history_only_id, outsider_id = (uuid4() for _ in range(4))
    agent_id, conversation_id = uuid4(), uuid4()

    async with factory.begin() as session:
        await session.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO qwenpaw_runtime'))
        await session.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO qwenpaw_runtime'))
        for user_id, username in (
            (owner_id, "owner"),
            (eligible_id, "eligible"),
            (history_only_id, "history-only"),
            (outsider_id, "outsider"),
        ):
            await session.execute(
                text(f'INSERT INTO "{schema}".users (id,username,password_hash,status,platform_role) VALUES (:id,:username,\'x\',\'active\',\'member\')'),
                {"id": user_id, "username": username},
            )
        await session.execute(
            text(f'INSERT INTO "{schema}".agents (id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) VALUES (:id,:owner,\'Shared Agent\',\'active\',\'shared\',\'inherit\',\'workspaces/shared\')'),
            {"id": agent_id, "owner": owner_id},
        )
        await session.execute(
            text(f'INSERT INTO "{schema}".agent_members (agent_id,user_id,role,granted_by) VALUES (:agent,:user,\'user\',:owner)'),
            {"agent": agent_id, "user": eligible_id, "owner": owner_id},
        )
        await session.execute(
            text(f'INSERT INTO "{schema}".agent_history_access (agent_id,user_id,first_chat_created_at,last_chat_created_at) VALUES (:agent,:user,now(),now())'),
            {"agent": agent_id, "user": history_only_id},
        )
        await session.execute(
            text(f'INSERT INTO "{schema}".conversations (id,agent_id,owner_user_id,title,status) VALUES (:id,:agent,:owner,\'Share me\',\'active\')'),
            {"id": conversation_id, "agent": agent_id, "owner": owner_id},
        )

    @asynccontextmanager
    async def runtime_session_factory():
        async with factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE qwenpaw_runtime"))
            yield session

    repository = PostgresConversationRepository(schema=schema, session_factory=runtime_session_factory)
    owner_repo = repository.with_user(owner_id)
    try:
        candidates = await owner_repo.list_share_candidates(
            conversation_id=conversation_id,
            owner_user_id=owner_id,
        )
        assert [candidate.user_id for candidate in candidates] == [eligible_id]

        first = await owner_repo.add_viewer(
            conversation_id=conversation_id,
            user_id=eligible_id,
            granted_by=owner_id,
        )
        second = await owner_repo.add_viewer(
            conversation_id=conversation_id,
            user_id=eligible_id,
            granted_by=owner_id,
        )
        assert first.user_id == second.user_id == eligible_id
        assert [member.user_id for member in await owner_repo.list_members(
            conversation_id=conversation_id,
            owner_user_id=owner_id,
        )] == [eligible_id]

        viewer_access = await repository.with_user(
            eligible_id
        ).get_conversation_for_user(
            conversation_id=conversation_id,
            user_id=eligible_id,
        )
        assert viewer_access is not None
        assert viewer_access.access_role == "viewer"
        assert viewer_access.read_only is True
        assert viewer_access.shared_by_username == "owner"

        async with factory.begin() as session:
            await session.execute(
                text(
                    f'UPDATE "{schema}".agent_members SET revoked_at=now() '
                    "WHERE agent_id=:agent AND user_id=:user"
                ),
                {"agent": agent_id, "user": eligible_id},
            )

        assert await repository.with_user(
            eligible_id
        ).get_conversation_for_user(
            conversation_id=conversation_id,
            user_id=eligible_id,
        ) is None
        assert await repository.with_user(
            eligible_id
        ).list_conversations_for_user(
            user_id=eligible_id,
            scope="shared",
        ) == []

        async with factory.begin() as session:
            await session.execute(
                text(
                    f'UPDATE "{schema}".agent_members SET revoked_at=NULL '
                    "WHERE agent_id=:agent AND user_id=:user"
                ),
                {"agent": agent_id, "user": eligible_id},
            )

        restored = await repository.with_user(
            eligible_id
        ).get_conversation_for_user(
            conversation_id=conversation_id,
            user_id=eligible_id,
        )
        assert restored is not None
        assert restored.access_role == "viewer"
        assert restored.read_only is True

        assert await repository.with_user(
            outsider_id
        ).get_conversation_for_user(
            conversation_id=conversation_id,
            user_id=outsider_id,
        ) is None

        with pytest.raises(ConversationShareEligibilityError):
            await owner_repo.add_viewer(
                conversation_id=conversation_id,
                user_id=history_only_id,
                granted_by=owner_id,
            )

        async with factory.begin() as session:
            member_count = await session.scalar(
                text(f'SELECT count(*) FROM "{schema}".agent_members WHERE agent_id=:agent AND user_id=:user'),
                {"agent": agent_id, "user": eligible_id},
            )
            assert member_count == 1

        assert await owner_repo.remove_viewer(
            conversation_id=conversation_id,
            user_id=eligible_id,
            owner_user_id=owner_id,
        )
        assert await repository.with_user(
            eligible_id
        ).get_conversation_for_user(
            conversation_id=conversation_id,
            user_id=eligible_id,
        ) is None
        assert await repository.with_user(
            eligible_id
        ).list_conversations_for_user(
            user_id=eligible_id,
            scope="shared",
        ) == []
        assert not await owner_repo.remove_viewer(
            conversation_id=conversation_id,
            user_id=eligible_id,
            owner_user_id=owner_id,
        )
    finally:
        await engine.dispose()
