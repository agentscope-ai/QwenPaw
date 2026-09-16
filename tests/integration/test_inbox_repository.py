# -*- coding: utf-8 -*-
"""私人收件箱 PostgreSQL Repository 集成契约。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


@pytest.fixture
def inbox_database(postgres_test_schema):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    command.upgrade(config, "head")
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as session:
            yield session

    yield postgres_test_schema.name, sessions


@pytest.mark.asyncio
async def test_private_notifications_receipts_and_soft_delete(inbox_database):
    from qwenpaw.app.inbox_repository import PostgresInboxRepository

    schema, sessions = inbox_database
    user_a, user_b = uuid4(), uuid4()
    async with sessions() as session:
        for user_id, username in ((user_a, "inbox-a"), (user_b, "inbox-b")):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,:username,'hash','active','member')"
                ),
                {"id": user_id, "username": username},
            )

    repository = PostgresInboxRepository(schema=schema, session_factory=sessions)
    event_a1 = await repository.append_event(
        recipient_user_id=user_a,
        agent_id="default",
        source_type="heartbeat",
        source_id="heartbeat",
        event_type="heartbeat_result",
        status="success",
        severity="info",
        title="A1",
        body="only A",
        payload={"run_id": "run-a"},
    )
    event_a2 = await repository.append_event(
        recipient_user_id=user_a,
        agent_id="agent-a",
        source_type="cron",
        source_id="job-a",
        event_type="cron_result",
        status="error",
        severity="error",
        title="A2",
        body="only A too",
        payload={},
    )
    event_b = await repository.append_event(
        recipient_user_id=user_b,
        agent_id="agent-b",
        source_type="cron",
        source_id="job-b",
        event_type="cron_result",
        status="success",
        severity="info",
        title="B",
        body="only B",
        payload={"run_id": "run-b"},
    )

    page_a, total_a, unread_a = await repository.query_events(
        recipient_user_id=user_a,
        source_types={"heartbeat", "cron"},
        limit=50,
        offset=0,
    )
    page_b, total_b, unread_b = await repository.query_events(
        recipient_user_id=user_b,
        limit=50,
        offset=0,
    )
    assert {item["id"] for item in page_a} == {event_a1["id"], event_a2["id"]}
    assert (total_a, unread_a) == (2, 2)
    assert [item["id"] for item in page_b] == [event_b["id"]]
    assert (total_b, unread_b) == (1, 1)

    assert await repository.mark_all_read(recipient_user_id=user_a) == 2
    assert await repository.mark_all_read(recipient_user_id=user_a) == 0
    _, _, unread_b_after = await repository.query_events(
        recipient_user_id=user_b,
        limit=50,
        offset=0,
    )
    assert unread_b_after == 1

    deleted = await repository.delete_events(
        [event_a1["id"], event_b["id"]],
        recipient_user_id=user_a,
    )
    assert deleted == 1
    assert (
        await repository.has_run_reference(
            "run-a",
            recipient_user_id=user_a,
        )
        is False
    )
    assert (
        await repository.has_run_reference(
            "run-b",
            recipient_user_id=user_a,
        )
        is False
    )
    assert (
        await repository.has_run_reference(
            "run-b",
            recipient_user_id=user_b,
        )
        is True
    )

    async with sessions() as session:
        notification_count = await session.scalar(
            text(f'SELECT count(*) FROM "{schema}".notifications')
        )
        deleted_receipts = await session.scalar(
            text(
                f'SELECT count(*) FROM "{schema}".notification_receipts '
                "WHERE deleted_at IS NOT NULL"
            )
        )
    assert notification_count == 3
    assert deleted_receipts == 1
