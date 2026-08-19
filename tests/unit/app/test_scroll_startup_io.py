# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for Scroll's startup-time synchronous I/O."""

from __future__ import annotations

import asyncio
import importlib
import threading
from pathlib import Path

import pytest

from qwenpaw.agents.context.scroll import sync as scroll_sync
from qwenpaw.agents.context.scroll.history import HistoryStore


@pytest.mark.asyncio
async def test_scroll_schema_migration_does_not_block_startup_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A populated legacy DB may build its date index in a worker thread."""
    monkeypatch.setattr(
        "qwenpaw.envs.load_envs_into_environ",
        lambda: None,
    )
    app_module = importlib.import_module("qwenpaw.app._app")
    startup_helper = app_module._sync_scroll_history_on_startup

    db_path = tmp_path / "history.db"
    legacy = HistoryStore(db_path)
    with legacy._conn:  # pylint: disable=protected-access
        legacy._conn.execute("DROP INDEX ch_created_at")
        legacy._conn.executemany(
            "INSERT INTO conversation_history"
            "(session_id, kind, content, created_at) VALUES (?, ?, ?, ?)",
            [
                ("legacy", "model_turn", f"row-{index}", "2024-01-01")
                for index in range(5000)
            ],
        )
    legacy.close()

    started = threading.Event()
    release = threading.Event()
    original_init_schema = HistoryStore._init_schema

    def blocked_init_schema(self) -> None:
        started.set()
        assert release.wait(timeout=5)
        original_init_schema(self)

    def startup_sync() -> None:
        history = HistoryStore(db_path)
        history.close()

    monkeypatch.setattr(HistoryStore, "_init_schema", blocked_init_schema)
    monkeypatch.setattr(scroll_sync, "sync_all_scroll_agents", startup_sync)

    task = asyncio.create_task(startup_helper())
    try:
        await asyncio.sleep(0)
        assert await asyncio.to_thread(started.wait, 2)
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    await task

    migrated = HistoryStore(db_path)
    try:
        indexes = {
            row["name"]
            # pylint: disable-next=protected-access
            for row in migrated._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'",
            )
        }
        assert "ch_created_at" in indexes
    finally:
        migrated.close()
