# -*- coding: utf-8 -*-
"""Tests for application-level scheduling utilities."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.app.utils import schedule_agent_reload


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_reload_completion_runs_on_failure_and_cancellation(cancelled):
    completed = asyncio.Event()
    results: list[bool] = []
    reload_agent = AsyncMock(
        side_effect=asyncio.CancelledError if cancelled else None,
        return_value=False,
    )
    manager = SimpleNamespace(
        reload_agent=reload_agent,
        note_agent_config_changed=Mock(),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=manager),
        ),
    )

    async def on_complete(reloaded: bool) -> None:
        results.append(reloaded)
        completed.set()

    assert schedule_agent_reload(
        request,
        "agent",
        on_complete=on_complete,
    )
    await asyncio.wait_for(completed.wait(), timeout=1)

    assert results == [False]
    manager.note_agent_config_changed.assert_called_once_with("agent")
    reload_agent.assert_awaited_once_with("agent")


def test_reload_is_not_scheduled_without_manager() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(multi_agent_manager=None)),
    )

    assert schedule_agent_reload(request, "agent") is False
