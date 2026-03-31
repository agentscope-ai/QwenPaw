# -*- coding: utf-8 -*-
"""Tests for FilePlanStorage."""
from __future__ import annotations

import asyncio

import pytest

from agentscope.plan import Plan, SubTask
from copaw.plan.storage import FilePlanStorage


def _make_plan(name: str = "Test Plan") -> Plan:
    return Plan(
        name=name,
        description="Test description",
        expected_outcome="Test outcome",
        subtasks=[
            SubTask(
                name="Task 1",
                description="Do task 1",
                expected_outcome="Done 1",
            ),
            SubTask(
                name="Task 2",
                description="Do task 2",
                expected_outcome="Done 2",
            ),
        ],
    )


class TestFilePlanStorageCRUD:
    """Basic CRUD operations for FilePlanStorage."""

    async def test_add_and_get(self, tmp_path):
        storage = FilePlanStorage(str(tmp_path / "plans"))
        plan = _make_plan()
        await storage.add_plan(plan)

        loaded = await storage.get_plan(plan.id)
        assert loaded is not None
        assert loaded.id == plan.id
        assert loaded.name == plan.name
        assert len(loaded.subtasks) == 2

    async def test_get_nonexistent_returns_none(self, tmp_path):
        storage = FilePlanStorage(str(tmp_path / "plans"))
        result = await storage.get_plan("nonexistent-id")
        assert result is None

    async def test_get_plans_empty(self, tmp_path):
        storage = FilePlanStorage(str(tmp_path / "plans"))
        plans = await storage.get_plans()
        assert plans == []

    async def test_get_plans_multiple(self, tmp_path):
        storage = FilePlanStorage(str(tmp_path / "plans"))
        p1 = _make_plan("Plan A")
        p2 = _make_plan("Plan B")
        await storage.add_plan(p1)
        await storage.add_plan(p2)

        plans = await storage.get_plans()
        assert len(plans) == 2
        names = {p.name for p in plans}
        assert names == {"Plan A", "Plan B"}

    async def test_delete(self, tmp_path):
        storage = FilePlanStorage(str(tmp_path / "plans"))
        plan = _make_plan()
        await storage.add_plan(plan)
        await storage.delete_plan(plan.id)

        result = await storage.get_plan(plan.id)
        assert result is None

    async def test_delete_nonexistent_no_error(self, tmp_path):
        storage = FilePlanStorage(str(tmp_path / "plans"))
        await storage.delete_plan("nonexistent")

    async def test_override_existing(self, tmp_path):
        storage = FilePlanStorage(str(tmp_path / "plans"))
        plan = _make_plan("Original")
        await storage.add_plan(plan)

        plan.name = "Updated"
        await storage.add_plan(plan, override=True)

        loaded = await storage.get_plan(plan.id)
        assert loaded is not None
        assert loaded.name == "Updated"

    async def test_no_override_raises(self, tmp_path):
        storage = FilePlanStorage(str(tmp_path / "plans"))
        plan = _make_plan()
        await storage.add_plan(plan)

        with pytest.raises(ValueError, match="already exists"):
            await storage.add_plan(plan, override=False)


class TestFilePlanStoragePersistence:
    """Storage survives reopen."""

    async def test_survives_restart(self, tmp_path):
        path = str(tmp_path / "plans")
        storage1 = FilePlanStorage(path)
        plan = _make_plan("Persistent")
        await storage1.add_plan(plan)
        del storage1

        storage2 = FilePlanStorage(path)
        loaded = await storage2.get_plan(plan.id)
        assert loaded is not None
        assert loaded.name == "Persistent"


class TestFilePlanStorageConcurrency:
    """Concurrent writes should not corrupt data."""

    async def test_concurrent_writes(self, tmp_path):
        storage = FilePlanStorage(str(tmp_path / "plans"))

        async def _add(idx: int):
            plan = _make_plan(f"Concurrent-{idx}")
            await storage.add_plan(plan)

        await asyncio.gather(*[_add(i) for i in range(10)])

        plans = await storage.get_plans()
        assert len(plans) == 10
        names = {p.name for p in plans}
        for i in range(10):
            assert f"Concurrent-{i}" in names
