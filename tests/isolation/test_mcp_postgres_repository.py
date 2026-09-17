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

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.mcp.postgres_repository import (
    MCPRevisionConflict,
    PostgresMCPRepository,
    workspace_uses_postgres,
)
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.constants import CREDENTIAL_KIND_OAUTH_AUTH_CODE
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.errors import CredentialNotFoundError
from qwenpaw.drivers.storage import AsyncDriverCardStore


def _config(test_schema) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_schema.async_url())
    config.attributes["target_schema"] = test_schema.name
    return config


@pytest.mark.asyncio
async def test_mcp_repository_preserves_allowlist_null_and_rejects_stale_update(
    postgres_test_schema,
):
    await asyncio.to_thread(command.upgrade, _config(postgres_test_schema), "head")
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as session:
            yield session

    user_id = uuid4()
    agent_key = "mcp-pg-test"
    async with sessions() as session:
        await session.execute(
            text(
                f"INSERT INTO \"{postgres_test_schema.name}\".users (id,username,password_hash,status,platform_role) VALUES (:id,:username,'hash','active','member')"
            ),
            {"id": user_id, "username": f"u-{user_id.hex}"},
        )
        await session.execute(
            text(
                f"INSERT INTO \"{postgres_test_schema.name}\".agents (id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) VALUES (:id,:owner,'Agent','active','private','inherited',:workspace)"
            ),
            {
                "id": agent_database_id(agent_key),
                "owner": user_id,
                "workspace": agent_key,
            },
        )

    repo = PostgresMCPRepository(
        schema=postgres_test_schema.name, session_factory=sessions
    )
    created = await repo.create_driver(
        agent_key=agent_key,
        client_key="demo",
        created_by=user_id,
        config={"transport": "stdio", "command": "safe"},
        tool_allowlist=None,
        policy={},
    )
    assert created.revision == 1
    assert created.tool_allowlist is None

    updated = await repo.update_driver(
        agent_key=agent_key,
        client_key="demo",
        expected_revision=1,
        updated_by=user_id,
        config={"transport": "stdio", "command": "safe-2"},
        tool_allowlist=[],
        policy={},
    )
    assert updated.revision == 2
    assert updated.tool_allowlist == []
    with pytest.raises(MCPRevisionConflict):
        await repo.update_driver(
            agent_key=agent_key,
            client_key="demo",
            expected_revision=1,
            updated_by=user_id,
            config=updated.config,
            tool_allowlist=[],
            policy={},
        )
    assert await repo.get_driver(agent_key="other-agent", client_key="demo") is None

    async with repo.transaction() as session:
        target = await repo.get_oauth_target(
            session=session,
            agent_key=agent_key,
            client_key="demo",
        )
        credential_id = await repo.replace_bound_credential(
            session=session,
            target=target,
            actor_user_id=user_id,
            purpose="oauth",
            kind=CREDENTIAL_KIND_OAUTH_AUTH_CODE,
            public={"expires_at": 1},
            secrets={"access_token": "old", "refresh_token": "refresh"},
        )
    await repo.refresh_oauth_credential(
        agent_key=agent_key,
        credential_id=credential_id,
        record=CredentialRecord(
            ref=str(credential_id),
            kind=CREDENTIAL_KIND_OAUTH_AUTH_CODE,
            public={"expires_at": 2},
            secrets={"access_token": "new", "refresh_token": "refresh"},
        ),
    )
    resolved = await repo.resolve_bound_credential(
        agent_key=agent_key,
        client_key="demo",
        purpose="oauth",
    )
    assert resolved.secrets["access_token"] == "new"
    async with repo.transaction() as session:
        target = await repo.get_oauth_target(
            session=session,
            agent_key=agent_key,
            client_key="demo",
        )
        await repo.revoke_bound_credential(
            session=session,
            target=target,
            actor_user_id=user_id,
        )
    with pytest.raises(CredentialNotFoundError):
        await repo.refresh_oauth_credential(
            agent_key=agent_key,
            credential_id=credential_id,
            record=resolved,
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_cutover_gate_ignores_non_mcp_legacy_cards(tmp_path, monkeypatch):
    import qwenpaw.app.mcp.postgres_repository as module

    class EmptyRepository:
        async def has_any_driver(self, *, agent_key):
            return False

    workspace = type(
        "Workspace",
        (),
        {"agent_id": "new-agent", "workspace_dir": tmp_path},
    )()
    await AsyncDriverCardStore(tmp_path / "drivers").save(
        DriverCard(
            name="other-protocol",
            protocol="acp",
            endpoint={"transport": "stdio", "command": "safe"},
        )
    )
    monkeypatch.setattr(module, "is_postgres_mcp_enabled", lambda: True)
    assert (
        await workspace_uses_postgres(
            workspace,
            repository=EmptyRepository(),
        )
        is True
    )


@pytest.mark.asyncio
async def test_principal_identities_include_active_owner_and_members_only(
    postgres_test_schema,
):
    await asyncio.to_thread(command.upgrade, _config(postgres_test_schema), "head")
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as session:
            yield session

    owner_id, member_id, disabled_id, revoked_id = (uuid4() for _ in range(4))
    active_agent = "principal-active-agent"
    disabled_owner_agent = "principal-disabled-owner-agent"
    async with sessions() as session:
        for user_id, username, status in (
            (owner_id, "active-owner", "active"),
            (member_id, "active-member", "active"),
            (disabled_id, "disabled-user", "disabled"),
            (revoked_id, "revoked-user", "active"),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{postgres_test_schema.name}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,:username,'hash',:status,'member')"
                ),
                {"id": user_id, "username": username, "status": status},
            )
        for agent_key, owner in (
            (active_agent, owner_id),
            (disabled_owner_agent, disabled_id),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{postgres_test_schema.name}".agents '
                    "(id,owner_user_id,name,status,visibility,default_model_mode,"
                    "draft_workspace_key) VALUES "
                    "(:id,:owner,'Agent','active','private','inherited',:workspace)"
                ),
                {
                    "id": agent_database_id(agent_key),
                    "owner": owner,
                    "workspace": agent_key,
                },
            )
        await session.execute(
            text(
                f'INSERT INTO "{postgres_test_schema.name}".agent_members '
                "(agent_id,user_id,role,granted_by,revoked_at) VALUES "
                "(:agent,:active,'collaborator',:owner,NULL),"
                "(:agent,:disabled,'user',:owner,NULL),"
                "(:agent,:revoked,'user',:owner,CURRENT_TIMESTAMP)"
            ),
            {
                "agent": agent_database_id(active_agent),
                "active": member_id,
                "disabled": disabled_id,
                "revoked": revoked_id,
                "owner": owner_id,
            },
        )

    repo = PostgresMCPRepository(
        schema=postgres_test_schema.name, session_factory=sessions
    )
    identities = await repo.list_principal_identities(agent_key=active_agent)
    assert [(item.user_id, item.username) for item in identities] == [
        (member_id, "active-member"),
        (owner_id, "active-owner"),
    ]
    assert await repo.list_principal_identities(agent_key=disabled_owner_agent) == []
    await engine.dispose()
