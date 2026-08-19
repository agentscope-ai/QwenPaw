# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Scroll schema migration must not block the request event loop."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

import qwenpaw.agents.context as context_mod
from qwenpaw.runtime.builder import AgentBuilder


@pytest.mark.asyncio
async def test_scroll_component_build_runs_in_worker_thread(
    tmp_path,
    monkeypatch,
):
    started = threading.Event()
    release = threading.Event()
    loop_thread = threading.get_ident()
    result = object()

    def blocking_build(**_kwargs):
        assert threading.get_ident() != loop_thread
        started.set()
        assert release.wait(timeout=2)
        return result

    monkeypatch.setattr(
        context_mod,
        "build_scroll_components",
        blocking_build,
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(workspace_dir=tmp_path),
        session_id="session",
        agent_id="agent",
    )
    config = SimpleNamespace(id="agent")

    task = asyncio.create_task(
        AgentBuilder._build_scroll_components(
            ctx,
            config,
            model=object(),
        ),
    )
    try:
        assert await asyncio.to_thread(started.wait, 1)
        scheduled = asyncio.Event()
        asyncio.get_running_loop().call_soon(scheduled.set)
        await asyncio.wait_for(scheduled.wait(), timeout=0.5)
        assert not task.done()
    finally:
        release.set()

    assert await asyncio.wait_for(task, timeout=1) is result
