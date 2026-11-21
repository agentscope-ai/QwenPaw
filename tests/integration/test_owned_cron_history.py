"""独立测试数据库：本人任务历史的持久归属与跨用户隔离。"""

from uuid import uuid4

import pytest
from sqlalchemy import text

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.crons.models import CronExecutionRecord
from qwenpaw.app.crons.repo.postgres_repo import PostgresJobRepository
from tests.integration.test_automation_repository import (
    automation_database,
    _job,
    _seed,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_owned_cron_history_survives_agent_changes_without_exposing_others(
    automation_database,
):
    schema, sessions = automation_database
    key, owner, agent_owner = await _seed(schema, sessions)
    repository = PostgresJobRepository(
        agent_key=key, schema=schema, session_factory=sessions
    )
    mine, other = _job(owner), _job(agent_owner, name="private other job")
    await repository.upsert_job(mine)
    await repository.upsert_job(other)
    record = CronExecutionRecord(run_at="2026-11-21T00:00:00Z", status="success")
    await repository.append_history(mine.id, record)
    assert [item.id for item in await repository.list_owned_jobs(owner)] == [mine.id]
    assert await repository.get_owned_history(mine.id, agent_owner) is None
    assert await repository.get_owned_history(other.id, owner) is None
    assert await repository.get_owned_history(str(uuid4()), owner) is None
    assert await repository.get_owned_history("../not-a-task-id", owner) is None
    # 管理员且为 Agent 所有者，也不能通过本人历史读取入口取得他人的内容。
    async with sessions() as session:
        await session.execute(
            text(f"UPDATE \"{schema}\".users SET platform_role='admin' WHERE id=:id"),
            {"id": agent_owner},
        )
        await session.execute(
            text(
                f'UPDATE "{schema}".agent_members SET revoked_at=now() WHERE user_id=:id'
            ),
            {"id": owner},
        )
    wrong_navigation = PostgresJobRepository(
        agent_key="another-agent", schema=schema, session_factory=sessions
    )
    assert await wrong_navigation.get_owned_history(mine.id, owner) == [record]
    assert (
        await repository.get_owned_history(
            mine.id, owner, expected_agent_id=agent_database_id("another-agent")
        )
        is None
    )
    for status in ("disabled", "deleted"):
        async with sessions() as session:
            await session.execute(
                text(f'UPDATE "{schema}".agents SET status=:status WHERE id=:id'),
                {"status": status, "id": agent_database_id(key)},
            )
        assert await repository.get_owned_history(mine.id, owner) == [record]
        assert await repository.get_owned_history(mine.id, agent_owner) is None
    await repository.delete_job(mine.id)
    assert await repository.get_owned_history(mine.id, owner) is None
