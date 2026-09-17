# -*- coding: utf-8 -*-
"""公共与用户私有根 MEMORY.md 的真实 ReMe 隔离检索。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from agentscope.message import TextBlock
from reme import ReMe

from qwenpaw.agents.memory.reme_config import get_reme_app_config
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.agents.memory.scope_runtime import ScopedMemoryRuntimePool
from qwenpaw.config.config import AgentProfileConfig


class _RealSearchRuntime:
    """只暴露本测试所需的真实 ReMe 搜索边界。"""

    def __init__(self, *, workspace: Path, agent_id: str) -> None:
        self.workspace = workspace
        self.app = ReMe(
            **get_reme_app_config(
                working_dir=str(workspace),
                agent_config=AgentProfileConfig(id=agent_id, name=agent_id),
            ),
        )

    async def start(self) -> None:
        await self.app.start()
        response = await self.app.run_job("reindex")
        assert response.success is True

    async def close(self) -> None:
        await self.app.close()

    async def _search_result_items(
        self,
        query: str,
        limit: int,
        min_score: float,
    ) -> list[dict[str, Any]]:
        response = await self.app.run_job(
            "search",
            query=query,
            limit=limit,
            min_score=min_score,
        )
        assert response.success is True
        return [
            {
                "path": str(item.get("path") or ""),
                "line": item.get("start_line"),
                "text": str(item.get("text") or ""),
                "score": float(
                    ReMeLightMemoryManager._extract_score(item),
                ),
            }
            for item in list((response.metadata or {}).get("results") or [])
        ]


def _chunk_text(chunk: Any) -> str:
    return "".join(
        block.text for block in chunk.content if isinstance(block, TextBlock)
    )


@pytest.mark.asyncio
async def test_scoped_search_merges_public_and_current_user_root_memory_only(
    tmp_path: Path,
) -> None:
    agent_id = "root-memory-scope-agent"
    user_a = UUID("11111111-1111-4111-8111-111111111111")
    user_b = UUID("22222222-2222-4222-8222-222222222222")
    public_workspace = tmp_path / "workspaces" / agent_id
    private_a_workspace = tmp_path / "user_workspaces" / str(user_a) / agent_id
    private_b_workspace = tmp_path / "user_workspaces" / str(user_b) / agent_id
    for workspace, token in (
        (public_workspace, "public-root-token"),
        (private_a_workspace, "user-a-root-token"),
        (private_b_workspace, "user-b-root-token"),
    ):
        workspace.mkdir(parents=True)
        (workspace / "MEMORY.md").write_text(token, encoding="utf-8")

    created_private_users: list[UUID] = []

    async def factory(scope, user_id, requested_agent_id, workspace):
        assert user_id is not None
        created_private_users.append(user_id)
        runtime = _RealSearchRuntime(
            workspace=workspace,
            agent_id=requested_agent_id,
        )
        await runtime.start()
        return runtime

    public_runtime = _RealSearchRuntime(
        workspace=public_workspace,
        agent_id=agent_id,
    )
    pool = ScopedMemoryRuntimePool(factory=factory, working_dir=tmp_path)
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = agent_id
    manager._scoped_runtime_pool = pool
    manager._search_result_items = public_runtime._search_result_items

    await public_runtime.start()
    try:
        result_a = await manager.scoped_memory_search(
            query="root-token",
            max_results=10,
            actor_user_id=str(user_a),
        )
        text_a = _chunk_text(result_a)
        assert "public-root-token" in text_a
        assert "user-a-root-token" in text_a
        assert "user-b-root-token" not in text_a

        result_b = await manager.scoped_memory_search(
            query="root-token",
            max_results=10,
            actor_user_id=str(user_b),
        )
        text_b = _chunk_text(result_b)
        assert "public-root-token" in text_b
        assert "user-b-root-token" in text_b
        assert "user-a-root-token" not in text_b

        private_count = len(created_private_users)
        governance_results = await public_runtime._search_result_items(
            "root-token",
            10,
            0,
        )
        governance_text = "\n".join(item["text"] for item in governance_results)
        assert "public-root-token" in governance_text
        assert "user-a-root-token" not in governance_text
        assert "user-b-root-token" not in governance_text
        assert len(created_private_users) == private_count
    finally:
        await pool.close()
        await public_runtime.close()
