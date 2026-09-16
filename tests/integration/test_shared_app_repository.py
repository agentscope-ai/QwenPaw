# -*- coding: utf-8 -*-
"""共享应用 PostgreSQL Repository 与数据库约束测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


@pytest.fixture
def shared_app_database(postgres_test_schema):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    command.upgrade(config, "head")
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    yield postgres_test_schema.name, session_factory


@pytest.mark.asyncio
async def test_publication_lifecycle_and_immutable_columns(shared_app_database):
    from qwenpaw.publications.models import (
        SharedAppDraftRecord,
        SharedAppPublicationRecord,
        SharedAppRecord,
    )
    from qwenpaw.publications.repository import (
        PostgresSharedAppRepository,
        PublicationStateConflict,
    )
    from sqlalchemy.exc import DBAPIError

    schema, session_factory = shared_app_database
    repository = PostgresSharedAppRepository(
        schema=schema,
        session_factory=session_factory,
    )
    owner_id, admin_id, agent_id = uuid4(), uuid4(), uuid4()
    app_id, draft_id, publication_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    async with session_factory() as session:
        for user_id, username, role in (
            (owner_id, "owner", "member"),
            (admin_id, "admin", "admin"),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,:username,'hash','active',:role)"
                ),
                {"id": user_id, "username": username, "role": role},
            )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".agents '
                "(id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) "
                "VALUES (:id,:owner,'Agent','active','private','inherit','workspaces/agent')"
            ),
            {"id": agent_id, "owner": owner_id},
        )

    app = SharedAppRecord(
        id=app_id,
        agent_id=agent_id,
        owner_user_id=owner_id,
        status="draft",
        created_at=now,
        updated_at=now,
    )
    assert await repository.create_app(app) == app
    draft = SharedAppDraftRecord(
        id=draft_id,
        shared_app_id=app_id,
        revision=1,
        manifest={"display": {"name": "演示应用"}},
        workspace_key="workspaces/agent",
        created_by=owner_id,
        updated_at=now,
    )
    assert await repository.create_draft(draft) == draft
    publication = SharedAppPublicationRecord(
        id=publication_id,
        shared_app_id=app_id,
        version="r1",
        immutable_manifest={
            "display": {"name": "演示应用"},
            "model": {"provider_id": "provider", "model": "model"},
            "integrity": {"manifest_hash": "a" * 64, "workspace_hash": "b" * 64},
        },
        baseline_workspace_key=f"published_workspaces/{publication_id}",
        submitted_by=owner_id,
        review_status="pending",
    )
    assert await repository.create_submission(publication) == publication

    approved = await repository.review(
        publication_id,
        reviewer_id=admin_id,
        decision="approved",
        note="依赖检查通过",
        reviewed_at=now,
    )
    assert approved.review_status == "approved"
    assert approved.review_note == "依赖检查通过"

    active = await repository.switch_current(
        app_id,
        publication_id=publication_id,
        expected_current_id=None,
        actor_id=admin_id,
        changed_at=now,
    )
    assert active.status == "active"
    assert active.current_publication_id == publication_id
    async with session_factory() as session:
        audit_actions = (
            await session.execute(
                text(
                    f'SELECT action FROM "{schema}".audit_logs '
                    "WHERE resource_id=:resource ORDER BY created_at"
                ),
                {"resource": publication_id},
            )
        ).scalars().all()
    assert audit_actions == [
        "shared_app.publication.submit",
        "shared_app.publication.approved",
        "shared_app.publication.publish",
    ]
    with pytest.raises(PublicationStateConflict, match="publication_state_changed"):
        await repository.switch_current(
            app_id,
            publication_id=publication_id,
            expected_current_id=None,
            actor_id=admin_id,
            changed_at=now,
        )

    with pytest.raises(DBAPIError, match="shared_app_publication_immutable"):
        async with session_factory() as session:
            await session.execute(
                text(
                    f'UPDATE "{schema}".shared_app_publications '
                    "SET immutable_manifest=CAST(:manifest AS jsonb) WHERE id=:id"
                ),
                {"id": publication_id, "manifest": json.dumps({"tampered": True})},
            )

    from qwenpaw.app.chats.repo.conversation import ConversationRecord
    from qwenpaw.app.chats.repo.postgres_repo import PostgresConversationRepository

    conversation_repository = PostgresConversationRepository(
        schema=schema,
        session_factory=session_factory,
    ).with_user(owner_id)
    conversation = ConversationRecord(
        id=uuid4(),
        agent_id=agent_id,
        owner_user_id=owner_id,
        title="共享应用会话",
        status="active",
        created_at=now,
        updated_at=now,
    )
    await conversation_repository.create_conversation(conversation)
    bound = await conversation_repository.bind_publication(
        conversation.id,
        expected_agent_id=agent_id,
        shared_app_id=app_id,
        publication_id=publication_id,
        updated_at=now,
    )
    assert bound is not None
    assert bound.shared_app_id == app_id
    assert bound.publication_id == publication_id


@pytest.mark.asyncio
async def test_shared_app_conversation_requires_complete_publication_pair(
    shared_app_database,
):
    from qwenpaw.app.chats.repo.conversation import ConversationRecord
    from qwenpaw.app.chats.repo.postgres_repo import PostgresConversationRepository

    schema, session_factory = shared_app_database
    owner_id, agent_id, app_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    async with session_factory() as session:
        await session.execute(
            text(
                f'INSERT INTO "{schema}".users '
                "(id,username,password_hash,status,platform_role) "
                "VALUES (:id,'owner','hash','active','member')"
            ),
            {"id": owner_id},
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".agents '
                "(id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) "
                "VALUES (:id,:owner,'Agent','active','private','inherit','workspaces/agent')"
            ),
            {"id": agent_id, "owner": owner_id},
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".shared_apps '
                "(id,agent_id,owner_user_id,status) VALUES (:id,:agent,:owner,'draft')"
            ),
            {"id": app_id, "agent": agent_id, "owner": owner_id},
        )

    repository = PostgresConversationRepository(
        schema=schema,
        session_factory=session_factory,
    ).with_user(owner_id)
    record = ConversationRecord(
        id=uuid4(),
        agent_id=agent_id,
        owner_user_id=owner_id,
        title="Invalid",
        status="active",
        shared_app_id=app_id,
        publication_id=None,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(Exception, match="ck_conversations_shared_publication_pair"):
        await repository.create_conversation(record)
