# -*- coding: utf-8 -*-
"""ReMe 生命周期必须向 Workspace 暴露真实启动结果。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


@pytest.mark.asyncio
async def test_start_propagates_reme_startup_failure() -> None:
    """可选服务管理器只能在收到异常后移除失效的 ReMe 实例。"""
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "broken-agent"
    manager._reme = SimpleNamespace(
        start=AsyncMock(side_effect=RuntimeError("startup failed")),
    )
    manager._update_qwenpaw_model = AsyncMock()

    with pytest.raises(RuntimeError, match="startup failed"):
        await manager.start()


@pytest.mark.asyncio
async def test_start_rejects_missing_reme_application() -> None:
    """构造失败不能被伪装成一次成功的空启动。"""
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "missing-agent"
    manager._reme = None

    with pytest.raises(RuntimeError, match="not initialized"):
        await manager.start()
