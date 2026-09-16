# -*- coding: utf-8 -*-
"""同一 Agent 下用户私有记忆运行时的文件隔离。"""

from pathlib import Path
from uuid import UUID

import pytest

from qwenpaw.agents.memory.scope_runtime import ScopedMemoryRuntimePool


@pytest.mark.asyncio
async def test_private_runtime_unique_markers_never_cross_user(
    tmp_path: Path,
) -> None:
    async def factory(scope, user_id, agent_id, workspace):
        del scope, user_id, agent_id
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    user_a = UUID("11111111-1111-4111-8111-111111111111")
    user_b = UUID("22222222-2222-4222-8222-222222222222")
    pool = ScopedMemoryRuntimePool(factory=factory, working_dir=tmp_path)
    runtime_a = await pool.get_private(user_id=user_a, agent_id="agent-a")
    runtime_b = await pool.get_private(user_id=user_b, agent_id="agent-a")

    (runtime_a / "MEMORY.md").write_text("marker-user-a", encoding="utf-8")
    (runtime_b / "MEMORY.md").write_text("marker-user-b", encoding="utf-8")

    assert "marker-user-b" not in (runtime_a / "MEMORY.md").read_text(encoding="utf-8")
    assert "marker-user-a" not in (runtime_b / "MEMORY.md").read_text(encoding="utf-8")
