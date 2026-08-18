# -*- coding: utf-8 -*-
"""Tests for synchronous and asynchronous agent config loading."""

import asyncio
import threading

from qwenpaw.config import config as config_module


def test_load_agent_config_supports_separate_event_loops(monkeypatch) -> None:
    """The public loader offloads work on each caller's event loop."""
    caller_thread = threading.get_ident()
    worker_threads: list[int] = []
    sentinel = object()

    def fake_load_agent_config(agent_id: str) -> object:
        assert agent_id == "agent"
        worker_threads.append(threading.get_ident())
        return sentinel

    monkeypatch.setattr(
        config_module,
        "_load_agent_config",
        fake_load_agent_config,
    )

    assert asyncio.run(config_module.load_agent_config("agent")) is sentinel
    assert asyncio.run(config_module.load_agent_config("agent")) is sentinel
    assert len(worker_threads) == 2
    assert all(thread_id != caller_thread for thread_id in worker_threads)
