# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app.runner.subagent_events import (
    SubagentEventRegistry,
    SubagentTaskRecord,
)


def test_register_task_publishes_started_event():
    registry = SubagentEventRegistry()
    registry.register_task(
        SubagentTaskRecord(
            task_id="task-1",
            parent_agent_id="agent-a",
            parent_session_id="parent-1",
            child_agent_id="agent-a",
            child_session_id="child-1",
            task="do work",
        ),
    )

    events = registry.drain_events("parent-1")

    assert len(events) == 1
    assert events[0].event_type == "subagent.started"
    assert events[0].status == "running"
    assert events[0].task_id == "task-1"


def test_pending_terminal_event_flushes_after_registration():
    registry = SubagentEventRegistry()
    registry.publish_terminal(
        "task-fast",
        status="completed",
        result={"output": []},
        elapsed_time=0.01,
    )

    registry.register_task(
        SubagentTaskRecord(
            task_id="task-fast",
            parent_agent_id="agent-a",
            parent_session_id="parent-1",
            child_agent_id="agent-a",
            child_session_id="child-1",
            task="fast work",
        ),
    )

    terminal = registry.drain_events("parent-1", terminal_only=True)

    assert len(terminal) == 1
    assert terminal[0].event_type == "subagent.completed"
    assert terminal[0].status == "completed"
    assert terminal[0].result == {"output": []}


def test_drain_events_keeps_unmatched_tasks():
    registry = SubagentEventRegistry()
    for task_id in ("task-1", "task-2"):
        registry.register_task(
            SubagentTaskRecord(
                task_id=task_id,
                parent_agent_id="agent-a",
                parent_session_id="parent-1",
                child_agent_id="agent-a",
                child_session_id=f"child-{task_id}",
            ),
        )
        registry.publish_terminal(task_id, status="completed", result={})

    first = registry.drain_events(
        "parent-1",
        task_ids={"task-1"},
        terminal_only=True,
    )
    second = registry.drain_events(
        "parent-1",
        task_ids={"task-2"},
        terminal_only=True,
    )

    assert [event.task_id for event in first] == ["task-1"]
    assert [event.task_id for event in second] == ["task-2"]


def test_heartbeat_updates_running_task_last_seen():
    registry = SubagentEventRegistry()
    registry.register_task(
        SubagentTaskRecord(
            task_id="task-heartbeat",
            parent_agent_id="agent-a",
            parent_session_id="parent-1",
            child_agent_id="agent-a",
            child_session_id="child-1",
        ),
    )
    record = registry.get_records_for_parent("parent-1")[0]
    initial_heartbeat = record.last_heartbeat_at

    event = registry.publish_event(
        "task-heartbeat",
        "subagent.heartbeat",
        "running",
    )

    assert event is not None
    assert record.last_heartbeat_at is not None
    assert record.last_heartbeat_at >= initial_heartbeat


def test_linked_running_count_ignores_terminal_tasks():
    registry = SubagentEventRegistry()
    for task_id in ("task-running", "task-done"):
        registry.register_task(
            SubagentTaskRecord(
                task_id=task_id,
                parent_agent_id="agent-a",
                parent_session_id="parent-1",
                child_agent_id="agent-a",
                child_session_id=f"child-{task_id}",
            ),
        )

    registry.publish_terminal("task-done", status="completed", result={})

    assert registry.linked_running_count("parent-1") == 1


def test_mark_stale_tasks_publishes_stale_terminal_event():
    registry = SubagentEventRegistry()
    registry.register_task(
        SubagentTaskRecord(
            task_id="task-stale",
            parent_agent_id="agent-a",
            parent_session_id="parent-1",
            child_agent_id="agent-a",
            child_session_id="child-1",
        ),
    )

    stale_events = registry.mark_stale_tasks(stale_after=0)
    terminal = registry.drain_events("parent-1", terminal_only=True)

    assert len(stale_events) == 1
    assert len(terminal) == 1
    assert terminal[0].event_type == "subagent.stale"
    assert terminal[0].status == "stale"
