# -*- coding: utf-8 -*-
"""Agent-owned migration cancellation and maintenance lifecycle coverage."""

import asyncio
import threading
from concurrent.futures import CancelledError
from types import SimpleNamespace

import pytest

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.sync import MIGRATION_KEY
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.app.workspace import service_factories


@pytest.mark.asyncio
async def test_agent_migration_cancellation_drains_worker(
    tmp_path,
    monkeypatch,
):
    history = HistoryStore(tmp_path / "history.db")
    started = threading.Event()
    stopped = threading.Event()
    config = SimpleNamespace(history_retention_days=0)
    workspace = SimpleNamespace(
        workspace_dir=tmp_path,
        agent_id="test",
        config=SimpleNamespace(
            running=SimpleNamespace(
                light_context_config=SimpleNamespace(scroll_config=config),
            ),
        ),
    )

    def migration(_history, _workspace, _agent, _days, stop):
        started.set()
        try:
            assert stop.wait(3)
            raise CancelledError()
        finally:
            stopped.set()

    monkeypatch.setattr(service_factories, "migrate_agent_history", migration)
    task = asyncio.create_task(
        service_factories.prepare_history_service(workspace, history, None),
    )
    try:
        assert await asyncio.to_thread(started.wait, 3)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()
        assert not history.migration_complete("test", MIGRATION_KEY)
    finally:
        await history.shutdown()


@pytest.mark.asyncio
async def test_retention_runs_after_startup_and_stops_with_history(tmp_path):
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="old",
        entry=LogEntry(kind="model_turn", created_at="2000-01-01"),
    )
    history.complete_migration("test", MIGRATION_KEY)
    await history.start_retention(30)
    assert history.count("old") == 1
    try:
        async with asyncio.timeout(5):
            while history.count("old"):
                await asyncio.sleep(0.05)
        assert history.migration_complete("test", MIGRATION_KEY)
    finally:
        await history.shutdown()
    assert history.closed
