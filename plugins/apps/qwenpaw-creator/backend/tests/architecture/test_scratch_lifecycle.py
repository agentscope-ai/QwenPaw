# -*- coding: utf-8 -*-
"""The app can serve requests during a scratch sweep and drain it on shutdown."""

import asyncio
import threading
from types import SimpleNamespace

import pytest


@pytest.mark.unit
def test_scratch_reclamation_yields_to_startup_and_joins_on_shutdown(
    tmp_path, monkeypatch
):
    import main

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "ensure_vendor_libs", lambda: None)
    monkeypatch.setattr(main, "ensure_creator_runtime_dependencies", dict)
    started = threading.Event()
    stopped = threading.Event()

    def sweep(_services, *, budget):
        started.set()
        if budget.stop_event.wait(10):
            stopped.set()
        return SimpleNamespace(released_directories=0)

    monkeypatch.setattr(main, "release_orphaned_scratch", sweep)

    async def exercise():
        await asyncio.wait_for(main._startup(), timeout=5)
        try:
            assert await asyncio.to_thread(started.wait, 5)
            assert not stopped.is_set()
        finally:
            await asyncio.wait_for(main._shutdown(), timeout=5)
        assert stopped.is_set()

    asyncio.run(exercise())
