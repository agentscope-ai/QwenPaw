# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""``qwenpaw history purge`` — preview, delete, and reclaim durable history."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.cli.history_cmd import history_group


def _seed(db_path: Path, *, old: int, fresh: int) -> None:
    """A store with ``old`` ancient rows and ``fresh`` future-dated rows."""
    h = HistoryStore(db_path)
    for i in range(old):
        h.append(
            session_id="s",
            dedup_key=f"old{i}",
            entry=LogEntry(
                kind="model_turn",
                role="assistant",
                content="ancient",
                created_at="2020-01-01T00:00:00+00:00",
            ),
        )
    for i in range(fresh):
        h.append(
            session_id="s",
            dedup_key=f"new{i}",
            entry=LogEntry(
                kind="model_turn",
                role="assistant",
                content="fresh",
                created_at="2999-01-01T00:00:00+00:00",
            ),
        )
    h.close()


def _count(db_path: Path) -> int:
    h = HistoryStore(db_path)
    try:
        return h.count("s")
    finally:
        h.close()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_dry_run_previews_without_deleting(runner, tmp_path):
    db = tmp_path / "history.db"
    _seed(db, old=3, fresh=2)
    res = runner.invoke(
        history_group,
        ["purge", "--db", str(db), "--days", "30", "--dry-run"],
    )
    assert res.exit_code == 0, res.output
    assert "3 rows" in res.output
    assert "dry-run: nothing deleted" in res.output
    assert _count(db) == 5  # untouched


def test_purge_deletes_old_keeps_fresh(runner, tmp_path):
    db = tmp_path / "history.db"
    _seed(db, old=3, fresh=2)
    res = runner.invoke(
        history_group,
        ["purge", "--db", str(db), "--days", "30", "--yes"],
    )
    assert res.exit_code == 0, res.output
    assert "Removed 3 rows" in res.output
    assert _count(db) == 2  # only the fresh rows survive


def test_confirmation_can_be_declined(runner, tmp_path):
    db = tmp_path / "history.db"
    _seed(db, old=3, fresh=2)
    # Answer "n" at the prompt.
    res = runner.invoke(
        history_group,
        ["purge", "--db", str(db), "--days", "30"],
        input="n\n",
    )
    assert res.exit_code == 0, res.output
    assert "Cancelled." in res.output
    assert _count(db) == 5


def test_vacuum_shrinks_the_file(runner, tmp_path):
    db = tmp_path / "history.db"
    # A lot of large old rows so deletion frees meaningful space.
    h = HistoryStore(db)
    for i in range(200):
        h.append(
            session_id="s",
            dedup_key=f"big{i}",
            entry=LogEntry(
                kind="model_turn",
                role="assistant",
                content="x" * 5000,
                created_at="2020-01-01T00:00:00+00:00",
            ),
        )
    h.close()
    before = db.stat().st_size
    res = runner.invoke(
        history_group,
        ["purge", "--db", str(db), "--days", "30", "--yes", "--vacuum"],
    )
    assert res.exit_code == 0, res.output
    assert "vacuumed" in res.output
    assert db.stat().st_size < before  # file actually shrank


def test_tool_output_only_keeps_conversation(runner, tmp_path):
    db = tmp_path / "history.db"
    h = HistoryStore(db)
    old = "2020-01-01T00:00:00+00:00"
    h.append(
        session_id="s",
        dedup_key="turn",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="keep me",
            created_at=old,
        ),
    )
    h.append(
        session_id="s",
        dedup_key="result",
        entry=LogEntry(
            kind="tool_result",
            role="tool",
            content="huge tool dump",
            created_at=old,
        ),
    )
    h.close()
    res = runner.invoke(
        history_group,
        [
            "purge",
            "--db",
            str(db),
            "--days",
            "30",
            "--tool-output-only",
            "--yes",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "tool-output rows" in res.output
    assert "Removed 1 rows" in res.output
    assert _count(db) == 1  # the conversation turn survives


def test_missing_db_is_reported_not_created(runner, tmp_path):
    db = tmp_path / "nope.db"
    res = runner.invoke(
        history_group,
        ["purge", "--db", str(db), "--days", "30", "--dry-run"],
    )
    assert res.exit_code == 0, res.output
    assert "skip (not found)" in res.output
    assert not db.exists()  # never created by the purge path
