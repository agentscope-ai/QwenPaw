# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Offline startup and watcher coverage for the actual embedded ReMe config.

Install the pinned integration dependencies before running the contract::

    python -m pip install reme-ai==0.4.2.0
    python -m pip install reme-auto-fin==0.1.3 reme-daily-paper==0.1.3
    python -m pytest tests/integration/test_reme_watch_contract.py
"""

import asyncio
import threading

import anyio
import pytest

from qwenpaw.agents.memory.reme_config import get_reme_app_config
from qwenpaw.agents.memory.reme_light_memory_manager import (
    _load_validated_reme_app,
)
from qwenpaw.config.config import AgentProfileConfig


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.asyncio
async def test_embedded_reme_starts_indexes_and_closes_without_shared_workers(
    tmp_path,
) -> None:
    """Load real plugins and resolve all jobs without calling a provider."""
    reme_app = _load_validated_reme_app()
    cfg = get_reme_app_config(
        working_dir=str(tmp_path),
        agent_config=AgentProfileConfig(id="test", name="Test"),
    )
    # Client construction needs a key; no test job calls the model.
    cfg["components"]["as_llm"]["default"]["credential"] = {
        "api_key": "offline-test-key",
    }
    cfg["log_to_console"] = False
    cfg["log_to_file"] = False
    watcher = cfg["jobs"]["index_update_loop"]["steps"][1]
    assert watcher["watch_mode"] == "watch"
    watcher.update(force_polling=True, poll_delay_ms=20, step=10, debounce=50)
    existing_threads = set(threading.enumerate())
    limiter = anyio.to_thread.current_default_thread_limiter()
    borrowed = limiter.borrowed_tokens
    app = reme_app(**cfg)
    try:
        await app.start()
        assert app.is_started
        assert "proactive_refresh" not in app.context.jobs
        store = app.context.components["file_store"]["default"]
        note = tmp_path / cfg["daily_dir"] / "watch-test.md"
        async with asyncio.timeout(10):
            while not any(
                node.path.endswith("watch-test.md")
                for node in await store.get_nodes()
            ):
                note.write_text(
                    "# Watch test\nA durable memory.\n",
                    encoding="utf-8",
                )
                await asyncio.sleep(0.1)
        assert limiter.borrowed_tokens == borrowed
        # Digest consolidation runs independently of proactive interaction.
        response = await app.run_job("auto_dream", date="2000-01-01")
        assert response.success
    finally:
        await app.close()
    assert not any(
        thread.name.startswith("reme-watch")
        for thread in set(threading.enumerate()) - existing_threads
    )
