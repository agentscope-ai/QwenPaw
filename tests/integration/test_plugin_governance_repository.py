"""插件治理 PostgreSQL 仓储的事务和授权矩阵测试。"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole
from qwenpaw.plugins.governance import (
    AppAudience,
    PluginAccessError,
    PluginGovernanceService,
    PluginInstallation,
    PostgresPluginGovernanceRepository,
)


@pytest.fixture
def plugin_governance_database(postgres_test_schema):
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


async def _seed_users_and_agent(schema, session_factory):
    admin_id, allowed_id, denied_id, inactive_id, agent_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with session_factory() as session:
        for user_id, username, role, status in (
            (admin_id, "plugin-admin", "admin", "active"),
            (allowed_id, "plugin-allowed", "member", "active"),
            (denied_id, "plugin-denied", "member", "active"),
            (inactive_id, "plugin-inactive", "member", "disabled"),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,:username,'hash',:status,:role)"
                ),
                {"id": user_id, "username": username, "status": status, "role": role},
            )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".agents '
                "(id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) "
                "VALUES (:id,:owner,'Plugin Agent','active','private','inherit','workspaces/plugin')"
            ),
            {"id": agent_id, "owner": allowed_id},
        )
    return admin_id, allowed_id, denied_id, inactive_id, agent_id


def _actor(user_id, role):
    return ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="plugin-postgres-test",
    )


def _candidate():
    return PluginInstallation(
        id=uuid4(),
        plugin_id="database-demo",
        version="1.0.0",
        plugin_type="app",
        status="active",
    )


@pytest.mark.asyncio
async def test_selected_user_status_and_agent_setting_round_trip(
    plugin_governance_database,
):
    schema, session_factory = plugin_governance_database
    admin_id, allowed_id, denied_id, _, agent_id = await _seed_users_and_agent(
        schema, session_factory
    )
    repository = PostgresPluginGovernanceRepository(
        schema=schema, session_factory=session_factory
    )
    service = PluginGovernanceService(repository)
    candidate = _candidate()
    admin = _actor(admin_id, PlatformRole.ADMIN)
    allowed = _actor(allowed_id, PlatformRole.MEMBER)
    denied = _actor(denied_id, PlatformRole.MEMBER)

    saved = await service.register_installation(
        admin,
        candidate,
        source_type="upload",
        source_ref="database-demo.zip",
        content_hash="a" * 64,
        audience=AppAudience(mode="selected_users", selected_user_ids=(allowed_id,)),
    )

    assert saved.id == candidate.id
    assert [item.plugin_id for item in await service.list_authorized(allowed)] == [
        "database-demo"
    ]
    assert await service.list_authorized(denied) == []
    projected = await repository.get_installation("database-demo")
    assert projected is not None
    assert projected.audience_mode == "selected_users"
    assert projected.selected_user_ids == (allowed_id,)

    setting = await repository.save_agent_setting(
        agent_id, candidate.id, True, {"mode": "safe"}, allowed_id
    )
    assert setting["config"] == {"mode": "safe"}
    projected_setting = await repository.get_agent_setting(agent_id, candidate.id)
    assert projected_setting["enabled"] is True
    assert projected_setting["config"] == {"mode": "safe"}
    async with session_factory() as session:
        stored = (
            (
                await session.execute(
                    text(
                        f'SELECT enabled,config FROM "{schema}".agent_plugin_settings '
                        "WHERE agent_id=:agent AND plugin_installation_id=:plugin"
                    ),
                    {"agent": agent_id, "plugin": candidate.id},
                )
            )
            .mappings()
            .one()
        )
    assert stored["enabled"] is True
    assert stored["config"] == {"mode": "safe"}

    await service.set_status(admin, candidate.plugin_id, enabled=False)
    assert await service.list_authorized(allowed) == []
    await service.set_status(admin, candidate.plugin_id, enabled=True)
    assert [item.plugin_id for item in await service.list_authorized(allowed)] == [
        "database-demo"
    ]


@pytest.mark.asyncio
async def test_registration_and_audience_are_one_transaction(
    plugin_governance_database,
):
    schema, session_factory = plugin_governance_database
    admin_id, _, _, inactive_id, _ = await _seed_users_and_agent(
        schema, session_factory
    )
    repository = PostgresPluginGovernanceRepository(
        schema=schema, session_factory=session_factory
    )
    service = PluginGovernanceService(repository)

    with pytest.raises(PluginAccessError, match="plugin_audience_user_invalid"):
        await service.register_installation(
            _actor(admin_id, PlatformRole.ADMIN),
            _candidate(),
            source_type="path",
            source_ref="/isolated/database-demo",
            content_hash="b" * 64,
            audience=AppAudience(
                mode="selected_users", selected_user_ids=(inactive_id,)
            ),
        )

    assert await repository.get_installation("database-demo") is None


@pytest.mark.asyncio
async def test_uninstall_removes_all_plugin_owned_rows(plugin_governance_database):
    schema, session_factory = plugin_governance_database
    admin_id, allowed_id, _, _, agent_id = await _seed_users_and_agent(
        schema, session_factory
    )
    repository = PostgresPluginGovernanceRepository(
        schema=schema, session_factory=session_factory
    )
    service = PluginGovernanceService(repository)
    candidate = _candidate()
    admin = _actor(admin_id, PlatformRole.ADMIN)
    await service.register_installation(
        admin,
        candidate,
        source_type="upload",
        source_ref="database-demo.zip",
        content_hash="c" * 64,
        audience=AppAudience(mode="all_members"),
    )
    await repository.save_agent_setting(
        agent_id, candidate.id, True, {"mode": "safe"}, allowed_id
    )
    async with session_factory() as session:
        await session.execute(
            text(
                f'INSERT INTO "{schema}".app_user_data '
                "(plugin_installation_id,user_id,agent_id,namespace,key,value) "
                "VALUES (:plugin,:user,:agent,'settings','theme',CAST(:value AS jsonb))"
            ),
            {
                "plugin": candidate.id,
                "user": allowed_id,
                "agent": agent_id,
                "value": json.dumps({"color": "blue"}),
            },
        )

    await service.begin_uninstall(admin, candidate.plugin_id)
    await service.complete_uninstall(admin, candidate.plugin_id)

    assert await repository.get_installation(candidate.plugin_id) is None
    async with session_factory() as session:
        for table in ("app_grants", "agent_plugin_settings", "app_user_data"):
            count = await session.scalar(
                text(
                    f'SELECT count(*) FROM "{schema}"."{table}" '
                    "WHERE plugin_installation_id=:plugin"
                ),
                {"plugin": candidate.id},
            )
            assert count == 0


@pytest.mark.asyncio
async def test_reconcile_registers_only_missing_disk_plugins_for_all_members(
    plugin_governance_database,
):
    schema, session_factory = plugin_governance_database
    admin_id, *_ = await _seed_users_and_agent(schema, session_factory)
    repository = PostgresPluginGovernanceRepository(
        schema=schema, session_factory=session_factory
    )
    existing = _candidate()
    await repository.register_installation(
        existing,
        "path",
        "/plugins/database-demo",
        "d" * 64,
        admin_id,
        AppAudience(mode="selected_users"),
    )
    legacy = PluginInstallation(
        id=uuid4(),
        plugin_id="legacy-disk-app",
        version="0.9.0",
        plugin_type="app",
        status="active",
    )

    count = await repository.reconcile_discovered_installations(
        [
            (existing, "/plugins/database-demo", "d" * 64),
            (legacy, "/plugins/legacy-disk-app", "e" * 64),
        ]
    )

    assert count == 1
    rows = {row.plugin_id: row for row in await repository.list_installations()}
    assert rows["database-demo"].audience_mode == "selected_users"
    assert rows["legacy-disk-app"].audience_mode == "all_members"
