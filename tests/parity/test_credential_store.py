# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.drivers.credentials.postgres_store import PostgresCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.errors import CredentialNotFoundError


def _alembic_config(test_schema) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_schema.async_url())
    config.attributes["target_schema"] = test_schema.name
    return config


@pytest.mark.asyncio
async def test_postgres_store_scopes_resolution_and_rejects_revoked_credentials(
    postgres_test_schema,
):
    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as session:
            yield session

    creator = uuid4()
    consumer = uuid4()
    other_consumer = uuid4()
    async with sessions() as session:
        await session.execute(
            text(
                f'INSERT INTO "{postgres_test_schema.name}".users '
                "(id, username, password_hash, platform_role, status) "
                "VALUES (:id, :name, 'hash', 'member', 'active')"
            ),
            {"id": creator, "name": f"u-{creator.hex}"},
        )

    store = PostgresCredentialStore(
        schema=postgres_test_schema.name,
        session_factory=sessions,
    )
    credential_id = await store.create_and_bind(
        record=CredentialRecord(
            ref="ignored-public-ref",
            kind="mcp-static",
            public={"label": "configured"},
            secrets={"Authorization": "synthetic-secret"},
        ),
        scope_type="driver",
        scope_id=consumer,
        consumer_type="driver",
        consumer_id=consumer,
        purpose="static",
        created_by=creator,
    )

    resolved = await store.resolve(
        consumer_type="driver",
        consumer_id=consumer,
        purpose="static",
        scope_type="driver",
        scope_id=consumer,
    )
    assert resolved.ref == str(credential_id)
    assert resolved.secrets == {"Authorization": "synthetic-secret"}
    assert "synthetic-secret" not in repr(resolved)

    with pytest.raises(CredentialNotFoundError):
        await store.resolve(
            consumer_type="driver",
            consumer_id=other_consumer,
            purpose="static",
            scope_type="driver",
            scope_id=other_consumer,
        )

    assert await store.revoke_binding(
        consumer_type="driver",
        consumer_id=consumer,
        purpose="static",
        scope_type="driver",
        scope_id=consumer,
    )
    with pytest.raises(CredentialNotFoundError):
        await store.resolve(
            consumer_type="driver",
            consumer_id=consumer,
            purpose="static",
            scope_type="driver",
            scope_id=consumer,
        )
    await engine.dispose()
