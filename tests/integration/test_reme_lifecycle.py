# -*- coding: utf-8 -*-
"""ReMe 与 QwenPaw 配置的真实生命周期集成测试。"""

import asyncio
from datetime import date

import pytest
from reme import ReMe

from qwenpaw.agents.memory.reme_config import get_reme_app_config
from qwenpaw.config.config import AgentProfileConfig


async def _wait_for_search(
    app: ReMe,
    query: str,
    expected: bool,
    timeout: float = 20.0,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    latest = ""
    while asyncio.get_running_loop().time() < deadline:
        result = await app.run_job("search", query=query)
        latest = str(result.answer)
        if (query in latest) is expected:
            return latest
        await asyncio.sleep(0.2)
    return latest


@pytest.mark.asyncio
async def test_reme_lifecycle_preserves_index_and_graph(tmp_path) -> None:
    """启动、重建索引、生成图谱并重启后仍能读取持久化数据。"""
    memory_dir = tmp_path / "memory"
    digest_dir = tmp_path / "digest" / "wiki"
    memory_dir.mkdir(parents=True)
    digest_dir.mkdir(parents=True)

    (memory_dir / f"{date.today().isoformat()}.md").write_text(
        "# 今日记忆\n\n完成 [[ReMe 生命周期验收]]。\n",
        encoding="utf-8",
    )
    (digest_dir / "reme-lifecycle.md").write_text(
        "---\ntitle: ReMe 生命周期验收\n---\n\n"
        "该知识关联到 [[今日记忆]]。\n",
        encoding="utf-8",
    )

    config = get_reme_app_config(
        working_dir=str(tmp_path),
        agent_config=AgentProfileConfig(
            id="reme-lifecycle-agent",
            name="ReMe Lifecycle Agent",
        ),
    )

    app = ReMe(**config)
    await app.start()
    try:
        assert app.is_started is True
        assert (await app.run_job("status")).success is True
        assert (await app.run_job("reindex")).success is True

        graph = await app.run_job("graph_snapshot")
        assert graph.success is True
        assert len(graph.answer["nodes"]) >= 2
        assert len(graph.answer["edges"]) >= 1
    finally:
        await app.close()

    restarted = ReMe(**config)
    await restarted.start()
    try:
        assert restarted.is_started is True
        graph = await restarted.run_job("graph_snapshot")
        assert graph.success is True
        assert len(graph.answer["nodes"]) >= 2
        assert len(graph.answer["edges"]) >= 1
    finally:
        await restarted.close()

    assert restarted.is_started is False


@pytest.mark.asyncio
async def test_reme_lifecycle_indexes_root_memory_and_preserves_deletion(
    tmp_path,
) -> None:
    """Root MEMORY.md is searchable, live-updated, and deletion survives restart."""
    root_memory = tmp_path / "MEMORY.md"
    profile = tmp_path / "PROFILE.md"
    root_memory.write_text("root-memory-unique-token", encoding="utf-8")
    profile.write_text("profile-must-not-be-indexed-token", encoding="utf-8")

    config = get_reme_app_config(
        working_dir=str(tmp_path),
        agent_config=AgentProfileConfig(
            id="reme-root-memory-agent",
            name="ReMe Root Memory Agent",
        ),
    )

    app = ReMe(**config)
    await app.start()
    try:
        assert (await app.run_job("reindex")).success is True
        root_result = await app.run_job("search", query="root-memory-unique-token")
        profile_result = await app.run_job(
            "search",
            query="profile-must-not-be-indexed-token",
        )
        assert "MEMORY.md" in str(root_result.answer)
        assert "PROFILE.md" not in str(profile_result.answer)

        root_memory.write_text("root-memory-updated-token", encoding="utf-8")
        assert "root-memory-updated-token" in await _wait_for_search(
            app,
            "root-memory-updated-token",
            expected=True,
        )
        assert "root-memory-unique-token" not in await _wait_for_search(
            app,
            "root-memory-unique-token",
            expected=False,
        )

        root_memory.unlink()
        assert "root-memory-updated-token" not in await _wait_for_search(
            app,
            "root-memory-updated-token",
            expected=False,
        )
    finally:
        await app.close()

    restarted = ReMe(**config)
    await restarted.start()
    try:
        assert "root-memory-updated-token" not in await _wait_for_search(
            restarted,
            "root-memory-updated-token",
            expected=False,
        )
    finally:
        await restarted.close()
