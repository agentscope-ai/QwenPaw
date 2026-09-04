# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from qwenpaw.portability.transaction_journal import (
    ImportTransactionJournal,
    recover_import_transactions,
)
from qwenpaw.portability.models import MigrationPlan
from qwenpaw.utils.io_utils import read_json_async, write_json_atomic_async


async def _plan(workspace: Path, plan_id: str, state: str) -> Path:
    path = workspace / ".qwenpaw/imports/plans" / f"{plan_id}.json"
    plan = MigrationPlan(
        plan_id=plan_id,
        source="codex",
        agent_id="agent-1",
        created_at=datetime.now(timezone.utc),
        state=state,
    )
    await write_json_atomic_async(path, plan.model_dump(mode="json"))
    return path


@pytest.mark.asyncio
async def test_recovery_resets_plan_without_restoring_live_files(
    tmp_path: Path,
):
    plan_id = "plan-" + "a" * 32
    target = tmp_path / "skills/example.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before")
    journal = ImportTransactionJournal(tmp_path, plan_id)
    await journal.begin()
    plan_path = await _plan(tmp_path, plan_id, "applying")
    target.write_text("after")

    assert await recover_import_transactions([tmp_path]) == [plan_id]
    assert target.read_text() == "after"
    assert (await read_json_async(plan_path))["state"] == "ready"
    assert not journal.path.exists()


@pytest.mark.asyncio
async def test_recovery_keeps_a_committed_transaction(tmp_path: Path):
    plan_id = "plan-" + "b" * 32
    target = tmp_path / "skills/example.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before")
    journal = ImportTransactionJournal(tmp_path, plan_id)
    await journal.begin()
    await _plan(tmp_path, plan_id, "applied")
    target.write_text("after")

    assert await recover_import_transactions([tmp_path]) == []
    assert target.read_text() == "after"
    assert not journal.path.exists()


@pytest.mark.asyncio
async def test_invalid_journal_is_quarantined_without_blocking_recovery(
    tmp_path: Path,
):
    plan_id = "plan-" + "c" * 32
    journal = ImportTransactionJournal(tmp_path, plan_id)
    await journal.begin()
    plan_path = await _plan(tmp_path, plan_id, "applying")
    broken = journal.path.with_name("broken.json")
    broken.write_text("not json", encoding="utf-8")

    assert await recover_import_transactions([tmp_path]) == [plan_id]
    assert (await read_json_async(plan_path))["state"] == "ready"
    assert not broken.exists()
    assert list(broken.parent.glob("broken.json.corrupt-*"))


@pytest.mark.asyncio
async def test_journal_without_a_valid_plan_is_quarantined(tmp_path: Path):
    plan_id = "plan-" + "d" * 32
    journal = ImportTransactionJournal(tmp_path, plan_id)
    await journal.begin()

    assert await recover_import_transactions([tmp_path]) == []
    assert list(journal.path.parent.glob(f"{journal.path.name}.corrupt-*"))


@pytest.mark.asyncio
async def test_mismatched_journal_cannot_reset_another_plan(tmp_path: Path):
    first = "plan-" + "e" * 32
    second = "plan-" + "f" * 32
    journal = ImportTransactionJournal(tmp_path, first)
    await journal.begin()
    await write_json_atomic_async(
        journal.path,
        {"plan_id": second, "state": "applying"},
    )
    second_path = await _plan(tmp_path, second, "applying")

    assert await recover_import_transactions([tmp_path]) == []
    assert (await read_json_async(second_path))["state"] == "applying"
    assert list(journal.path.parent.glob(f"{journal.path.name}.corrupt-*"))
