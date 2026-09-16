# -*- coding: utf-8 -*-
"""用户级频道绑定的 PostgreSQL 隔离契约。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.access.agent_repository import (
    LegacyAgentRecord,
    PostgresAgentRepository,
)
from qwenpaw.identity.models import PlatformRole
from qwenpaw.identity.repository import PostgresUserRepository
from qwenpaw.identity.service import UserService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(postgres_test_schema) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    return config


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_public_agent_keeps_each_users_channel_binding_private(
    postgres_test_schema,
) -> None:
    """把 owner_user_id 从查询或唯一约束移除时，本测试必须失败。"""
    channel_module = import_module("qwenpaw.access.channel_bindings")
    repository_type = channel_module.PostgresChannelBindingRepository

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
    bindings = repository_type(
        schema=postgres_test_schema.name,
        session_factory=session_factory,
    )
    agent = LegacyAgentRecord(
        key="public-agent",
        name="Public Agent",
        description="",
        workspace_key="workspaces/public-agent",
        status="active",
    )

    try:
        owner = await users.create_user(
            "channel-owner",
            "password",
            PlatformRole.MEMBER,
        )
        first_user = await users.create_user(
            "channel-user-a",
            "password",
            PlatformRole.MEMBER,
        )
        second_user = await users.create_user(
            "channel-user-b",
            "password",
            PlatformRole.MEMBER,
        )
        await agents.register_owner(agent=agent, owner_user_id=owner.id)

        first = await bindings.upsert(
            agent_key=agent.key,
            owner_user_id=first_user.id,
            channel_type="console",
            display_name="A 的控制台绑定",
            enabled=True,
            config={"bot_prefix": "A"},
            secrets={},
        )
        second = await bindings.upsert(
            agent_key=agent.key,
            owner_user_id=second_user.id,
            channel_type="console",
            display_name="B 的控制台绑定",
            enabled=False,
            config={"bot_prefix": "B"},
            secrets={},
        )

        assert first.id != second.id
        assert [
            item.id
            for item in await bindings.list_enabled(agent_keys=[agent.key])
        ] == [first.id]
        assert [item.display_name for item in await bindings.list_for_user(
            agent_key=agent.key,
            owner_user_id=first_user.id,
        )] == ["A 的控制台绑定"]
        assert [item.display_name for item in await bindings.list_for_user(
            agent_key=agent.key,
            owner_user_id=second_user.id,
        )] == ["B 的控制台绑定"]

        async with session_factory() as session:
            stored = (
                await session.execute(
                    text(
                        f'SELECT owner_user_id, config FROM '
                        f'"{postgres_test_schema.name}".channel_bindings '
                        "ORDER BY display_name"
                    )
                )
            ).mappings().all()
        assert [row["owner_user_id"] for row in stored] == [
            first_user.id,
            second_user.id,
        ]
        assert [row["config"]["bot_prefix"] for row in stored] == ["A", "B"]
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_channel_secret_is_encrypted_and_never_returned_by_list(
    postgres_test_schema,
) -> None:
    """把频道密钥写回 config 或明文数据库时，本测试必须失败。"""
    channel_module = import_module("qwenpaw.access.channel_bindings")
    repository_type = channel_module.PostgresChannelBindingRepository

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
    bindings = repository_type(
        schema=postgres_test_schema.name,
        session_factory=session_factory,
    )
    agent = LegacyAgentRecord(
        key="secret-agent",
        name="Secret Agent",
        description="",
        workspace_key="workspaces/secret-agent",
        status="active",
    )

    try:
        owner = await users.create_user(
            "channel-secret-owner",
            "password",
            PlatformRole.MEMBER,
        )
        await agents.register_owner(agent=agent, owner_user_id=owner.id)
        saved = await bindings.upsert(
            agent_key=agent.key,
            owner_user_id=owner.id,
            channel_type="telegram",
            display_name="Telegram",
            enabled=True,
            config={"bot_prefix": "paw"},
            secrets={"bot_token": "telegram-secret-value"},
        )

        listed = await bindings.list_for_user(
            agent_key=agent.key,
            owner_user_id=owner.id,
        )
        assert listed[0].config == {"bot_prefix": "paw"}
        assert listed[0].configured_secret_fields == ("bot_token",)
        assert await bindings.get_runtime_config(
            binding_id=saved.id,
            owner_user_id=owner.id,
        ) == {
            "bot_prefix": "paw",
            "bot_token": "telegram-secret-value",
        }
        async def process(request):
            yield {"type": "done"}

        wrapped = import_module(
            "qwenpaw.app.channels.user_bindings"
        ).bind_process_identity(
            process,
            owner_user_id=owner.id,
            binding_id=saved.id,
            record_external_identity=bindings.upsert_external_identity,
        )
        request = SimpleNamespace(
            user_id="telegram-user-42",
            session_id="telegram:chat-7",
            channel="telegram",
            channel_meta={"username": "alice"},
            request_context={},
        )
        assert [event async for event in wrapped(request)] == [
            {"type": "done"}
        ]
        assert request.user_id == str(owner.id)
        await bindings.upsert_external_identity(
            binding_id=saved.id,
            external_subject_id="telegram-user-42",
            platform_user_id=owner.id,
            metadata={"channel": "telegram", "username": "alice-new"},
        )
        await bindings.upsert_external_identity(
            binding_id=saved.id,
            external_subject_id="spoofed-owner",
            platform_user_id=uuid4(),
            metadata={"channel": "telegram"},
        )

        async with session_factory() as session:
            encrypted_value = await session.scalar(
                text(
                    f'SELECT encrypted_value FROM '
                    f'"{postgres_test_schema.name}".credential_records '
                    "WHERE id = (SELECT credential_ref FROM "
                    f'"{postgres_test_schema.name}".channel_bindings '
                    "WHERE id = :binding_id)"
                ),
                {"binding_id": saved.id},
            )
            external_identity = (
                await session.execute(
                    text(
                        f'SELECT external_subject_id, platform_user_id, '
                        f'binding_status, metadata FROM '
                        f'"{postgres_test_schema.name}".'
                        'channel_external_identities '
                        'WHERE channel_binding_id = :binding_id'
                    ),
                    {"binding_id": saved.id},
                )
            ).mappings().one()
        assert encrypted_value is not None
        assert b"telegram-secret-value" not in encrypted_value
        assert external_identity["external_subject_id"] == "telegram-user-42"
        assert external_identity["platform_user_id"] == owner.id
        assert external_identity["binding_status"] == "active"
        assert external_identity["metadata"]["username"] == "alice-new"
        async with session_factory() as session:
            identity_count = await session.scalar(
                text(
                    f'SELECT count(*) FROM '
                    f'"{postgres_test_schema.name}".'
                    'channel_external_identities '
                    'WHERE channel_binding_id = :binding_id'
                ),
                {"binding_id": saved.id},
            )
        assert identity_count == 1
    finally:
        await engine.dispose()
