# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for memory and proactive configuration I/O boundaries."""

import threading
from types import SimpleNamespace

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.memory.proactive import proactive_responder
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


@pytest.mark.asyncio
async def test_reme_auto_search_loads_config_in_worker_thread(monkeypatch):
    """ReMe auto-search must not read agent config on the event loop."""
    event_loop_thread = threading.get_ident()
    load_threads = []
    search_config = SimpleNamespace(enabled=False, max_results=3)
    agent_config = SimpleNamespace(
        running=SimpleNamespace(
            reme_light_memory_config=SimpleNamespace(
                auto_memory_search_config=search_config,
            ),
            light_context_config=SimpleNamespace(
                token_count_estimate_divisor=4,
            ),
        ),
    )

    def load_config(agent_id: str):
        load_threads.append((agent_id, threading.get_ident()))
        return agent_config

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        load_config,
    )
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    message = Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text="hello")],
    )

    assert await manager.auto_memory_search(message) is None
    assert load_threads[0][0] == "agent-1"
    assert load_threads[0][1] != event_loop_thread


@pytest.mark.asyncio
async def test_reme_inbox_config_loads_in_worker_thread(monkeypatch):
    """ReMe inbox delivery must not read config on the event loop."""
    event_loop_thread = threading.get_ident()
    load_threads = []

    def load_config(agent_id: str):
        load_threads.append((agent_id, threading.get_ident()))
        return SimpleNamespace(
            running=SimpleNamespace(
                reme_light_memory_config=SimpleNamespace(
                    auto_memory_inbox_push_enabled=False,
                ),
            ),
        )

    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        load_config,
    )
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"

    pushed = await manager._append_reme_job_result_to_inbox(
        "auto_memory",
        response=SimpleNamespace(metadata={}, answer=""),
        kwargs={},
    )

    assert pushed is False
    assert load_threads[0][0] == "agent-1"
    assert load_threads[0][1] != event_loop_thread


@pytest.mark.asyncio
async def test_proactive_settings_load_config_in_worker_thread(monkeypatch):
    """Proactive delivery must not read agent config on the event loop."""
    event_loop_thread = threading.get_ident()
    load_threads = []

    def load_config(agent_id: str):
        load_threads.append((agent_id, threading.get_ident()))
        return SimpleNamespace(
            language="zh",
            running=SimpleNamespace(
                reme_light_memory_config=SimpleNamespace(
                    proactive_enabled=True,
                    proactive_inbox_push_enabled=False,
                    proactive_max_items=2,
                    proactive_cron_max_items=0,
                    proactive_delivery_cooldown_days=5,
                    proactive_refresh_min_interval_minutes=30,
                    metadata_dir="mem_metadata",
                ),
            ),
        )

    monkeypatch.setattr(proactive_responder, "load_agent_config", load_config)

    settings = await proactive_responder.load_proactive_settings("agent-1")

    assert settings.language == "zh"
    assert settings.enabled is True
    assert settings.inbox_enabled is False
    assert settings.max_items == 2
    assert settings.cooldown_days == 5
    assert settings.refresh_min_interval_minutes == 30
    assert load_threads[0][0] == "agent-1"
    assert load_threads[0][1] != event_loop_thread
