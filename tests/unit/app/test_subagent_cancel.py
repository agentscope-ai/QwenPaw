# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

from qwenpaw.app.runner import subagent_cancel
from qwenpaw.app.runner.subagent_events import (
    SubagentTaskRecord,
    get_subagent_event_registry,
)


def test_cancel_linked_subagents_cancels_all_running_children(monkeypatch):
    registry = get_subagent_event_registry()
    registry.register_task(
        SubagentTaskRecord(
            task_id="task-1",
            parent_agent_id="default",
            parent_session_id="parent-cancel",
            child_agent_id="default",
            child_session_id="child-1",
        ),
    )
    registry.register_task(
        SubagentTaskRecord(
            task_id="task-2",
            parent_agent_id="default",
            parent_session_id="parent-cancel",
            child_agent_id="default",
            child_session_id="child-2",
        ),
    )
    cancelled = []

    async def fake_cancel(task_id: str) -> bool:
        cancelled.append(task_id)
        return True

    monkeypatch.setattr(subagent_cancel, "_cancel_task_callback", fake_cancel)

    count = asyncio.run(
        subagent_cancel.cancel_linked_subagents("parent-cancel"),
    )

    assert count == 2
    assert cancelled == ["task-1", "task-2"]
