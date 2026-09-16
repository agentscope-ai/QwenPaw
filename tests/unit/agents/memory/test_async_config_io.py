# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for memory and proactive configuration I/O boundaries."""

import threading
from types import SimpleNamespace

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.memory.proactive import proactive_responder
from qwenpaw.agents.memory.proactive.proactive_responder import (
    _generate_final_message,
)
from qwenpaw.agents.memory.proactive.proactive_types import (
    ProactiveQueryResult,
)
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
async def test_proactive_final_message_loads_config_in_worker_thread(
    monkeypatch,
):
    """Proactive response formatting must not read config on the loop."""
    event_loop_thread = threading.get_ident()
    load_threads = []

    def load_config(agent_id: str):
        load_threads.append((agent_id, threading.get_ident()))
        return SimpleNamespace(language="en")

    async def send_message(**_kwargs):
        return None

    monkeypatch.setattr(proactive_responder, "load_agent_config", load_config)
    monkeypatch.setattr(
        proactive_responder,
        "send_proactive_message_via_http",
        send_message,
    )

    result = ProactiveQueryResult(
        query="status",
        success=True,
        data="ready",
    )
    assert await _generate_final_message(result, "agent-1") is None
    assert load_threads[0][0] == "agent-1"
    assert load_threads[0][1] != event_loop_thread
