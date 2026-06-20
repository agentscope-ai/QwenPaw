# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Unit tests for the legacy-dialog → ``history.db`` migration.

Pins the three rollout-critical guarantees: non-destructive, idempotent, and
faithful (rows match what the live writer would have produced).
"""

import json
from pathlib import Path

import pytest
from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolResultBlock

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.migrate import (
    MANIFEST_NAME,
    migrate_dialog_to_history,
)


def _write_dialog(dialog_dir: Path, date: str, msgs: list[Msg]) -> Path:
    dialog_dir.mkdir(parents=True, exist_ok=True)
    path = dialog_dir / f"{date}.jsonl"
    path.write_text(
        "\n".join(json.dumps(m.to_dict()) for m in msgs) + "\n",
        encoding="utf-8",
    )
    return path


def _sample_msgs() -> list[Msg]:
    return [
        Msg(
            name="u",
            role="user",
            content=[TextBlock(type="text", text="please do X")],
        ),
        Msg(
            name="a",
            role="assistant",
            content=[
                TextBlock(type="text", text="working\n⟦ did the work ⟧"),
                ToolCallBlock(
                    type="tool_call", id="c1", name="grep", input="{}"
                ),
                ToolResultBlock(
                    type="tool_result",
                    id="c1",
                    name="grep",
                    output=[TextBlock(type="text", text="found it")],
                ),
            ],
        ),
    ]


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    h = HistoryStore(tmp_path / "history.db")
    yield h
    h.close()


def test_migrates_dialog_into_history(store: HistoryStore, tmp_path: Path):
    dialog = tmp_path / "dialog"
    _write_dialog(dialog, "2026-06-12", _sample_msgs())
    report = migrate_dialog_to_history(history=store, dialog_dir=dialog)
    assert report.rows_inserted > 0
    assert report.sessions == 1
    # The date-file maps to a synthetic legacy session.
    assert store.count("legacy:2026-06-12") == report.rows_inserted
    # Faithful: the tool result is recallable by its call id.
    rows = store._conn.execute(
        "SELECT content FROM conversation_history "
        "WHERE tool_call_id='c1' AND kind='tool_result'",
    ).fetchall()
    assert rows and rows[0]["content"] == "found it"


def test_migration_is_idempotent_via_manifest(store: HistoryStore, tmp_path):
    dialog = tmp_path / "dialog"
    _write_dialog(dialog, "2026-06-12", _sample_msgs())
    migrate_dialog_to_history(history=store, dialog_dir=dialog)
    total = store.count("legacy:2026-06-12")
    assert (dialog / MANIFEST_NAME).exists()

    second = migrate_dialog_to_history(history=store, dialog_dir=dialog)
    assert second.rows_inserted == 0  # all files skipped via manifest
    assert all(f.skipped for f in second.files)
    assert store.count("legacy:2026-06-12") == total  # no growth


def test_idempotent_even_without_manifest(store: HistoryStore, tmp_path):
    """Without the manifest shortcut, the DB UNIQUE index still blocks
    duplicate rows on a re-run."""
    dialog = tmp_path / "dialog"
    _write_dialog(dialog, "2026-06-12", _sample_msgs())
    migrate_dialog_to_history(
        history=store,
        dialog_dir=dialog,
        use_manifest=False,
    )
    total = store.count("legacy:2026-06-12")
    migrate_dialog_to_history(
        history=store,
        dialog_dir=dialog,
        use_manifest=False,
    )
    assert store.count("legacy:2026-06-12") == total


def test_migration_never_touches_source_files(store: HistoryStore, tmp_path):
    dialog = tmp_path / "dialog"
    path = _write_dialog(dialog, "2026-06-12", _sample_msgs())
    before = path.read_bytes()
    migrate_dialog_to_history(history=store, dialog_dir=dialog)
    assert path.read_bytes() == before  # byte-for-byte unchanged


def test_dry_run_inserts_nothing_and_writes_no_manifest(store, tmp_path):
    dialog = tmp_path / "dialog"
    _write_dialog(dialog, "2026-06-12", _sample_msgs())
    report = migrate_dialog_to_history(
        history=store,
        dialog_dir=dialog,
        dry_run=True,
    )
    assert store.count("legacy:2026-06-12") == 0
    assert not (dialog / MANIFEST_NAME).exists()
    assert report.rows_inserted == 0


def test_missing_dialog_dir_is_a_noop(store: HistoryStore, tmp_path: Path):
    report = migrate_dialog_to_history(
        history=store,
        dialog_dir=tmp_path / "nope",
    )
    assert not report.files
    assert "no legacy offload memory" in report.summary()


def test_unparseable_lines_are_counted_not_fatal(store, tmp_path: Path):
    dialog = tmp_path / "dialog"
    dialog.mkdir(parents=True)
    (dialog / "2026-06-12.jsonl").write_text(
        json.dumps(_sample_msgs()[0].to_dict()) + "\n"
        "{ this is not valid json\n",
        encoding="utf-8",
    )
    report = migrate_dialog_to_history(history=store, dialog_dir=dialog)
    assert sum(f.unparseable for f in report.files) == 1
    assert store.count("legacy:2026-06-12") >= 1  # the good line still landed


def test_orphan_tool_results_are_reported_not_imported(store, tmp_path: Path):
    dialog = tmp_path / "dialog"
    _write_dialog(dialog, "2026-06-12", _sample_msgs())
    tr = tmp_path / "tool_results"
    tr.mkdir()
    (tr / "abc.txt").write_text("orphan blob", encoding="utf-8")
    report = migrate_dialog_to_history(
        history=store,
        dialog_dir=dialog,
        tool_results_dir=tr,
    )
    assert report.orphan_tool_results == 1
    # Not imported — no row carries the orphan content.
    rows = store._conn.execute(
        "SELECT 1 FROM conversation_history "
        "WHERE content LIKE '%orphan blob%'",
    ).fetchall()
    assert rows == []
