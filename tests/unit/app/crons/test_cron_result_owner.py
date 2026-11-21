"""同一 Agent 的定时任务结果属于任务创建者。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qwenpaw.app.crons import manager as module
from qwenpaw.app.crons.manager import CronManager
from tests.unit.app.conftest import InMemoryJobRepository, make_cron_job_spec


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery_failed", [False, True])
async def test_execution_inbox_result_uses_job_owner_instead_of_agent_owner(
    monkeypatch, delivery_failed
):
    owner, agent_owner = uuid4(), uuid4()
    repo = InMemoryJobRepository()
    mgr = CronManager(
        repo=repo,
        workspace=MagicMock(),
        channel_manager=AsyncMock(),
        agent_id="shared-agent",
    )
    job = make_cron_job_spec().model_copy(
        update={
            "automation_owner_user_id": owner,
            "created_by_user_id": owner,
            "save_result_to_inbox": True,
        }
    )
    mgr._executor.execute = AsyncMock(
        return_value={"delivery_status": "failed" if delivery_failed else "success"}
    )
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.access.agent_repository.PostgresAgentRepository",
        lambda **kwargs: SimpleNamespace(
            get_governance=AsyncMock(
                return_value=SimpleNamespace(owner_user_id=agent_owner)
            )
        ),
    )
    append = AsyncMock()
    monkeypatch.setattr(module, "append_inbox_event", append)
    await mgr._execute_once(job)
    append.assert_awaited_once()
    assert append.await_args.kwargs["recipient_user_id"] == str(owner)
