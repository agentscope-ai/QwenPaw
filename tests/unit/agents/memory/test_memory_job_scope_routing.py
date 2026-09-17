# -*- coding: utf-8 -*-
"""自动记忆与后台任务必须路由到明确的记忆作用域。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.memory_scope.models import MemoryScopeDenied

USER_ID = UUID("11111111-1111-4111-8111-111111111111")


class _RuntimePool:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    async def get_private(self, *, user_id, agent_id):
        assert user_id == USER_ID
        assert agent_id == "agent-a"
        return self.runtime


@pytest.mark.asyncio
async def test_manual_dream_runs_in_current_users_private_runtime() -> None:
    """手动 dream 若调用公共 runtime，本测试必须失败。"""
    private_runtime = SimpleNamespace(dream=AsyncMock())
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-a"
    manager._scoped_runtime_pool = _RuntimePool(private_runtime)
    manager._require_private_memory_access = AsyncMock()

    await manager.scoped_dream(
        actor_user_id=str(USER_ID),
        hint="整理近期主题",
    )

    assert manager._require_private_memory_access.await_count == 1
    private_runtime.dream.assert_awaited_once()
    kwargs = private_runtime.dream.await_args.kwargs
    assert kwargs["hint"] == "整理近期主题"
    assert kwargs["recipient_user_id"] == str(USER_ID)


@pytest.mark.asyncio
async def test_private_auto_memory_checks_access_at_submit_and_write() -> None:
    """提交私有记忆任务前必须先检查当前访问权限。"""
    runtime = SimpleNamespace(auto_memory=AsyncMock())
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-a"
    manager._scoped_runtime_pool = _RuntimePool(runtime)
    manager._require_private_memory_access = AsyncMock()

    await manager.scoped_auto_memory(
        messages=[SimpleNamespace(model_dump=lambda **_kwargs: {})],
        actor_user_id=str(USER_ID),
        session_id="session-a",
    )

    manager._require_private_memory_access.assert_awaited_once_with(USER_ID)
    runtime.auto_memory.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_runtime_rechecks_access_before_reme_write() -> None:
    """任务提交后撤权时，真正执行 ReMe 写入前必须拒绝。"""
    runtime = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    runtime.agent_id = "agent-a"
    runtime._reme = SimpleNamespace(is_started=True, run_job=AsyncMock())
    runtime._scope_actor_user_id = USER_ID
    runtime._scope_access_checker = AsyncMock(
        side_effect=MemoryScopeDenied("memory_access_revoked"),
    )

    with pytest.raises(MemoryScopeDenied, match="memory_access_revoked"):
        await runtime._run_reme_job_unlocked(
            "auto_memory",
            raise_on_error=True,
            messages=[],
            session_id="session-a",
        )

    runtime._scope_access_checker.assert_awaited_once_with(USER_ID)
    runtime._reme.run_job.assert_not_awaited()


def test_reme_cron_jobs_use_explicit_public_callbacks() -> None:
    """Cron 若复用可被请求身份影响的普通入口，本测试必须失败。"""
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._reme = SimpleNamespace(is_started=True)
    manager.get_memory_config = lambda: SimpleNamespace(
        dream_cron_enabled=True,
        dream_cron="0 23 * * *",
        daily_paper_cron_enabled=True,
        daily_paper_cron="0 9 * * *",
    )

    jobs = manager.list_cron_jobs()

    assert jobs[0].callback.__func__ is ReMeLightMemoryManager.public_dream
    assert (
        jobs[1].callback.__func__
        is ReMeLightMemoryManager.public_daily_paper
    )
