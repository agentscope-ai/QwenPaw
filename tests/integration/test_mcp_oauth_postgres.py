# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from qwenpaw.app.mcp.oauth_repository import (
    OAuthSessionConflictError,
    PostgresOAuthRepository,
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_real_postgres_oauth_state_rejects_replay_expiry_and_revocation(
    postgres_test_schema,
) -> None:
    """A real transaction must enforce every ownership predicate atomically."""
    schema = postgres_test_schema.name
    engine = create_async_engine(postgres_test_schema.async_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    q = f'"{schema}"'
    async with engine.begin() as connection:
        statements = (
            f"CREATE TABLE {q}.users (id uuid PRIMARY KEY, status text)",
            f"CREATE TABLE {q}.agents (id uuid PRIMARY KEY, owner_user_id uuid, status text)",
            f"CREATE TABLE {q}.agent_members (agent_id uuid, user_id uuid, role text, revoked_at timestamptz)",
            f"CREATE TABLE {q}.agent_drivers (id uuid PRIMARY KEY, agent_id uuid, status text)",
            f"CREATE TABLE {q}.mcp_oauth_sessions (id uuid PRIMARY KEY, driver_id uuid, initiated_by uuid, state_hash text UNIQUE, status text, expires_at timestamptz, completed_at timestamptz)",
        )
        for statement in statements:
            await connection.execute(text(statement))
    user_id, agent_id, driver_id = uuid4(), uuid4(), uuid4()
    async with factory.begin() as db:
        values = {"user": user_id, "agent": agent_id, "driver": driver_id}
        await db.execute(text(f"INSERT INTO {q}.users VALUES (:user, 'active')"), values)
        await db.execute(text(f"INSERT INTO {q}.agents VALUES (:agent, :user, 'active')"), values)
        await db.execute(text(f"INSERT INTO {q}.agent_drivers VALUES (:driver, :agent, 'active')"), values)

    repo = PostgresOAuthRepository(schema=schema)
    async with factory.begin() as db:
        await repo.create(
            session=db,
            state="single-use",
            driver_id=driver_id,
            initiated_by=user_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        pending = await repo.status(
            session=db,
            state="single-use",
            driver_id=driver_id,
            initiated_by=user_id,
        )
        assert pending is not None and pending.status == "pending"
        await repo.consume(
            session=db,
            state="single-use",
            driver_id=driver_id,
            initiated_by=user_id,
        )
        completed = await repo.status(
            session=db,
            state="single-use",
            driver_id=driver_id,
            initiated_by=user_id,
        )
        assert completed is not None and completed.status == "completed"
        assert await repo.status(
            session=db,
            state="single-use",
            driver_id=driver_id,
            initiated_by=uuid4(),
        ) is None
    async with factory.begin() as db:
        with pytest.raises(OAuthSessionConflictError):
            await repo.consume(
                session=db,
                state="single-use",
                driver_id=driver_id,
                initiated_by=user_id,
            )

    cases = (
        ("expired", datetime.now(UTC) - timedelta(seconds=1), None),
        ("revoked-user", datetime.now(UTC) + timedelta(minutes=5), "user"),
        ("deleted-driver", datetime.now(UTC) + timedelta(minutes=5), "driver"),
    )
    for state, expires_at, mutation in cases:
        async with factory.begin() as db:
            await repo.create(
                session=db,
                state=state,
                driver_id=driver_id,
                initiated_by=user_id,
                expires_at=expires_at,
            )
            if mutation == "user":
                await db.execute(
                    text(f"UPDATE {q}.users SET status='disabled' WHERE id=:id"),
                    {"id": user_id},
                )
            if mutation == "driver":
                await db.execute(
                    text(f"UPDATE {q}.agent_drivers SET status='deleted' WHERE id=:id"),
                    {"id": driver_id},
                )
            with pytest.raises(OAuthSessionConflictError):
                await repo.consume(
                    session=db,
                    state=state,
                    driver_id=driver_id,
                    initiated_by=user_id,
                )
            if mutation == "user":
                await db.execute(
                    text(f"UPDATE {q}.users SET status='active' WHERE id=:id"),
                    {"id": user_id},
                )
            if mutation == "driver":
                await db.execute(
                    text(f"UPDATE {q}.agent_drivers SET status='active' WHERE id=:id"),
                    {"id": driver_id},
                )
    await engine.dispose()
