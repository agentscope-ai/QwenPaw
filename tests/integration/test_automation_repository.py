"""自动化 PostgreSQL 仓储的 owner、授权和执行记录测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.crons.models import CronExecutionRecord, CronJobSpec
from qwenpaw.app.crons.repo.postgres_repo import PostgresJobRepository


@pytest.fixture
def automation_database(postgres_test_schema):
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


def _job(owner_id, *, name="owner job") -> CronJobSpec:
    return CronJobSpec.model_validate(
        {
            "id": str(uuid4()),
            "name": name,
            "schedule": {"type": "cron", "cron": "0 9 * * *"},
            "task_type": "agent",
            "request": {"input": "daily summary"},
            "dispatch": {
                "channel": "console",
                "target": {"user_id": str(owner_id), "session_id": "daily"},
            },
            "automation_owner_user_id": str(owner_id),
            "created_by_user_id": str(owner_id),
            "status": "pending_authorization",
            "config_version": 1,
        }
    )


async def _seed(schema, session_factory):
    owner_id, other_id = uuid4(), uuid4()
    agent_key = "automation-agent"
    async with session_factory() as session:
        for user_id, username in ((owner_id, "auto-owner"), (other_id, "other")):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,:username,'hash','active','member')"
                ),
                {"id": user_id, "username": username},
            )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".agents '
                "(id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) "
                "VALUES (:id,:owner,'Automation Agent','active','private','inherit','workspaces/auto')"
            ),
            {"id": agent_database_id(agent_key), "owner": other_id},
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".agent_members '
                "(agent_id,user_id,role,granted_by) VALUES (:agent,:user,'user',:owner)"
            ),
            {"agent": agent_database_id(agent_key), "user": owner_id, "owner": other_id},
        )
    return agent_key, owner_id, other_id


@pytest.mark.asyncio
async def test_owner_round_trip_authorization_and_history(automation_database):
    schema, session_factory = automation_database
    agent_key, owner_id, _ = await _seed(schema, session_factory)
    repository = PostgresJobRepository(
        agent_key=agent_key, schema=schema, session_factory=session_factory
    )
    job = _job(owner_id)

    await repository.upsert_job(job)
    stored = await repository.get_job(job.id)
    assert stored is not None
    assert stored.automation_owner_user_id == owner_id
    assert stored.dispatch.target.user_id == str(owner_id)
    assert stored.status == "pending_authorization"

    await repository.authorize(
        job.id,
        authorized_by_user_id=owner_id,
        config_version=1,
        authorization_digest="a" * 64,
        grants=[("automation.execute", {}, {}), ("dispatch:console", {}, {"user_id": str(owner_id)})],
    )
    authorized = await repository.get_authorization(job.id)
    assert authorized is not None
    assert authorized.config_version == 1
    assert authorized.authorization_digest == "a" * 64
    assert {grant.capability for grant in authorized.grants} == {
        "automation.execute",
        "dispatch:console",
    }
    active_job = await repository.get_job(job.id)
    assert active_job is not None
    assert active_job.status == "active"
    assert active_job.enabled is True

    record = CronExecutionRecord(run_at="2026-09-07T08:00:00Z", status="success")
    assert await repository.append_history(job.id, record) == [record]
    assert await repository.get_history(job.id) == [record]


@pytest.mark.asyncio
async def test_scope_changing_replace_revokes_grants_and_increments_version(
    automation_database,
):
    schema, session_factory = automation_database
    agent_key, owner_id, _ = await _seed(schema, session_factory)
    repository = PostgresJobRepository(
        agent_key=agent_key, schema=schema, session_factory=session_factory
    )
    job = _job(owner_id)
    await repository.upsert_job(job)
    await repository.authorize(
        job.id,
        authorized_by_user_id=owner_id,
        config_version=1,
        authorization_digest="b" * 64,
        grants=[("automation.execute", {}, {})],
    )

    changed = job.model_copy(
        update={"request": job.request.model_copy(update={"input": "changed"})}
    )
    await repository.upsert_job(changed)

    stored = await repository.get_job(job.id)
    assert stored is not None
    assert stored.status == "pending_authorization"
    assert stored.config_version == 2
    assert stored.enabled is False
    assert await repository.get_authorization(job.id) is None
