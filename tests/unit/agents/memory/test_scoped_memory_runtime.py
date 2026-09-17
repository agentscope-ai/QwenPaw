# -*- coding: utf-8 -*-
"""每个记忆作用域使用独立 ReMe 运行时。"""

from pathlib import Path
from uuid import UUID

import pytest

from qwenpaw.memory_scope.models import MemoryScope
from qwenpaw.agents.memory.scope_runtime import ScopedMemoryRuntimePool


@pytest.mark.asyncio
async def test_private_runtime_is_not_reused_across_users(
    tmp_path: Path,
) -> None:
    created: list[tuple[str, str, str]] = []

    async def factory(scope, user_id, agent_id, workspace):
        created.append((scope.value, str(user_id), agent_id))
        return {"scope": scope, "workspace": workspace}

    pool = ScopedMemoryRuntimePool(factory=factory, working_dir=tmp_path)
    user_a = UUID("11111111-1111-4111-8111-111111111111")
    user_b = UUID("22222222-2222-4222-8222-222222222222")

    a1 = await pool.get_private(user_id=user_a, agent_id="agent-a")
    a2 = await pool.get_private(user_id=user_a, agent_id="agent-a")
    b1 = await pool.get_private(user_id=user_b, agent_id="agent-a")

    assert a1 is a2
    assert a1 is not b1
    assert created == [
        ("private", str(user_a), "agent-a"),
        ("private", str(user_b), "agent-a"),
    ]
    assert a1["workspace"].as_posix().endswith(f"user_workspaces/{user_a}/agent-a")
    assert b1["workspace"] != a1["workspace"]


@pytest.mark.asyncio
async def test_public_runtime_is_shared_only_by_agent(tmp_path: Path) -> None:
    created: list[tuple[str, str]] = []

    async def factory(scope, user_id, agent_id, workspace):
        created.append((scope.value, agent_id))
        return workspace

    pool = ScopedMemoryRuntimePool(factory=factory, working_dir=tmp_path)
    public_a = await pool.get_public(agent_id="agent-a")
    public_a_again = await pool.get_public(agent_id="agent-a")
    public_b = await pool.get_public(agent_id="agent-b")

    assert public_a is public_a_again
    assert public_a != public_b
    assert created == [("public", "agent-a"), ("public", "agent-b")]


@pytest.mark.asyncio
async def test_public_and_private_root_memory_storage_is_physically_isolated(
    tmp_path: Path,
) -> None:
    """公共、用户 A、用户 B 必须使用不同根文件和 ReMe 元数据目录。"""

    async def factory(scope, user_id, agent_id, workspace):
        return {
            "scope": scope,
            "workspace": workspace,
            "root_memory": workspace / "MEMORY.md",
            "metadata": workspace / "mem_metadata",
        }

    user_a = UUID("11111111-1111-4111-8111-111111111111")
    user_b = UUID("22222222-2222-4222-8222-222222222222")
    pool = ScopedMemoryRuntimePool(factory=factory, working_dir=tmp_path)

    public = await pool.get_public(agent_id="agent-a")
    private_a = await pool.get_private(user_id=user_a, agent_id="agent-a")
    private_b = await pool.get_private(user_id=user_b, agent_id="agent-a")

    assert public["root_memory"] == (
        tmp_path / "workspaces" / "agent-a" / "MEMORY.md"
    ).resolve()
    assert private_a["root_memory"] == (
        tmp_path / "user_workspaces" / str(user_a) / "agent-a" / "MEMORY.md"
    ).resolve()
    assert private_b["root_memory"] == (
        tmp_path / "user_workspaces" / str(user_b) / "agent-a" / "MEMORY.md"
    ).resolve()
    assert len(
        {
            public["metadata"],
            private_a["metadata"],
            private_b["metadata"],
        },
    ) == 3


@pytest.mark.asyncio
async def test_close_user_closes_only_that_users_private_runtime(
    tmp_path: Path,
) -> None:
    closed: list[str] = []

    class Runtime:
        async def close(self):
            closed.append(self.key)

        def __init__(self, key):
            self.key = key

    async def factory(scope, user_id, agent_id, workspace):
        return Runtime(f"{scope.value}:{user_id}:{agent_id}")

    user_a = UUID("11111111-1111-4111-8111-111111111111")
    user_b = UUID("22222222-2222-4222-8222-222222222222")
    pool = ScopedMemoryRuntimePool(factory=factory, working_dir=tmp_path)
    await pool.get_private(user_id=user_a, agent_id="agent-a")
    await pool.get_private(user_id=user_b, agent_id="agent-a")

    await pool.close_user(user_id=user_a)

    assert closed == [f"private:{user_a}:agent-a"]
    assert await pool.get_private(user_id=user_b, agent_id="agent-a")


@pytest.mark.asyncio
async def test_private_runtime_registers_controlled_workspace_once(
    tmp_path: Path,
) -> None:
    registrations: list[tuple[UUID, str, str]] = []

    async def factory(scope, user_id, agent_id, workspace):
        return workspace

    async def registrar(user_id, agent_id, workspace_key):
        registrations.append((user_id, agent_id, workspace_key))

    user_id = UUID("11111111-1111-4111-8111-111111111111")
    pool = ScopedMemoryRuntimePool(
        factory=factory,
        registrar=registrar,
        working_dir=tmp_path,
    )

    await pool.get_private(user_id=user_id, agent_id="agent-a")
    await pool.get_private(user_id=user_id, agent_id="agent-a")

    assert registrations == [(user_id, "agent-a", f"user_workspaces/{user_id}/agent-a")]
