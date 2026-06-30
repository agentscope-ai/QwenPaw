# -*- coding: utf-8 -*-
"""Behavioral tests for the AS2-native background subagent lifecycle."""

# pylint: disable=using-constant-test,protected-access

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from agentscope.message import AssistantMsg

from qwenpaw.app.subagents.manager import (
    SubagentStatus,
    SubagentTaskManager,
)
from qwenpaw.app.subagents.hooks import SubagentWakeGuardHook
from qwenpaw.app.subagents.middleware import SubagentInboxMiddleware
from qwenpaw.app.workspace.local_workspace import QwenPawLocalWorkspace
from qwenpaw.runtime.hooks import HookAction
from qwenpaw.runtime.tool_registry import ToolDescriptor, ToolRegistry


class _ChannelManager:
    def __init__(self) -> None:
        self.enqueued = []

    def enqueue(self, channel, request) -> None:
        self.enqueued.append((channel, request))


class _Workspace:
    def __init__(self, path, stream_factory) -> None:
        self.workspace_dir = path
        self.channel_manager = _ChannelManager()
        self._stream_factory = stream_factory

    async def stream_query(self, request):
        async for item in self._stream_factory(request):
            yield item


def _completed_message(text: str):
    return SimpleNamespace(
        role="assistant",
        status="completed",
        content=[SimpleNamespace(text=text)],
    )


async def _wait_terminal(manager, task_id, timeout=1.0):
    async with asyncio.timeout(timeout):
        while True:
            record = await manager.get(task_id)
            if record is not None and record.status in {
                SubagentStatus.COMPLETED,
                SubagentStatus.FAILED,
                SubagentStatus.CANCELLED,
            }:
                return record
            await asyncio.sleep(0.005)


async def _spawn(manager, **overrides):
    params = {
        "prompt": "research the issue",
        "parent_agent_id": "default",
        "parent_session_id": "console:parent",
        "root_session_id": "console:parent",
        "child_agent_id": "default",
        "child_session_id": "sub-child",
        "user_id": "parent",
        "channel": "console",
        "channel_meta": {"session_id": "console:parent"},
        "parent_is_subagent": False,
    }
    params.update(overrides)
    return await manager.spawn(**params)


@pytest.mark.asyncio
async def test_completion_publishes_event_and_wakes_parent(tmp_path):
    async def stream(_request):
        yield _completed_message("child summary")

    workspace = _Workspace(tmp_path, stream)
    manager = SubagentTaskManager(workspace)
    await manager.start()

    record = await _spawn(manager)
    terminal = await _wait_terminal(manager, record.task_id)

    assert terminal.status == SubagentStatus.COMPLETED
    assert terminal.result == "child summary"
    assert len(workspace.channel_manager.enqueued) == 1
    channel, request = workspace.channel_manager.enqueued[0]
    assert channel == "console"
    assert request.session_id == "console:parent"
    assert request.input == []
    assert request.request_context["subagent_wakeup"] is True

    events = await manager.drain_events("console:parent")
    assert [event.status for event in events] == [SubagentStatus.COMPLETED]
    assert events[0].result == "child summary"
    assert not await manager.has_pending_events("console:parent")
    await manager.stop()


@pytest.mark.asyncio
async def test_parent_agents_with_same_session_are_workspace_isolated(
    tmp_path,
):
    async def stream_a(_request):
        yield _completed_message("result-a")

    async def stream_b(_request):
        yield _completed_message("result-b")

    manager_a = SubagentTaskManager(_Workspace(tmp_path / "a", stream_a))
    manager_b = SubagentTaskManager(_Workspace(tmp_path / "b", stream_b))
    assert manager_a.max_running_per_parent == 8

    record_a = await _spawn(manager_a, parent_agent_id="agent-a")
    record_b = await _spawn(manager_b, parent_agent_id="agent-b")
    await _wait_terminal(manager_a, record_a.task_id)
    await _wait_terminal(manager_b, record_b.task_id)

    events_a = await manager_a.drain_events("console:parent")
    events_b = await manager_b.drain_events("console:parent")
    assert [event.result for event in events_a] == ["result-a"]
    assert [event.result for event in events_b] == ["result-b"]


@pytest.mark.asyncio
async def test_wakeup_waits_for_active_parent_and_avoids_session_race(
    tmp_path,
):
    async def stream(_request):
        yield _completed_message("child summary")

    class _Chats:
        async def get_chat_id_by_session(self, _session_id, _channel):
            return "chat-1"

    class _Tracker:
        running = True

        async def get_status(self, _chat_id):
            return "running" if self.running else "idle"

    workspace = _Workspace(tmp_path, stream)
    workspace.chat_manager = _Chats()
    workspace.task_tracker = _Tracker()
    manager = SubagentTaskManager(workspace)
    await manager.start()

    record = await _spawn(manager)
    await _wait_terminal(manager, record.task_id)
    await asyncio.sleep(0.02)
    assert not workspace.channel_manager.enqueued

    workspace.task_tracker.running = False
    await asyncio.wait_for(record.asyncio_task, timeout=1)
    assert len(workspace.channel_manager.enqueued) == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_long_running_child_is_not_cancelled_by_elapsed_time(tmp_path):
    release = asyncio.Event()

    async def stream(_request):
        await release.wait()
        yield {"output": "done"}

    workspace = _Workspace(tmp_path, stream)
    manager = SubagentTaskManager(workspace)
    await manager.start()
    record = await _spawn(manager)

    # Elapsed wall time alone must never terminate a healthy background
    # subagent. It runs until completion or an explicit lifecycle cancel.
    await asyncio.sleep(0.05)
    running = await manager.get(record.task_id)
    assert running is not None
    assert running.status == SubagentStatus.RUNNING
    assert not record.asyncio_task.done()

    release.set()
    terminal = await _wait_terminal(manager, record.task_id)
    assert terminal.status == SubagentStatus.COMPLETED
    await manager.stop()


@pytest.mark.asyncio
async def test_heartbeat_loss_cancels_child_and_notifies_parent(tmp_path):
    started = asyncio.Event()

    async def stream(_request):
        started.set()
        await asyncio.Event().wait()
        if False:
            yield None

    workspace = _Workspace(tmp_path, stream)
    manager = SubagentTaskManager(
        workspace,
        heartbeat_timeout_seconds=10,
    )
    record = await _spawn(manager)
    await asyncio.wait_for(started.wait(), timeout=1)

    assert (
        await manager._watchdog_tick(
            record.last_heartbeat_at + 10,
        )
        == []
    )
    assert record.status == SubagentStatus.CANCELLING

    terminal = await _wait_terminal(manager, record.task_id)
    assert terminal.status == SubagentStatus.CANCELLED
    assert "heartbeat lost" in (terminal.error or "")
    events = await manager.drain_events("console:parent")
    assert [event.status for event in events] == [
        SubagentStatus.CANCELLED,
    ]
    assert len(workspace.channel_manager.enqueued) == 1


@pytest.mark.asyncio
async def test_cancel_resistant_child_becomes_stale_once_then_completes(
    tmp_path,
):
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()

    async def stream(_request):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
        await release.wait()
        yield _completed_message("recovered result")

    workspace = _Workspace(tmp_path, stream)
    manager = SubagentTaskManager(
        workspace,
        heartbeat_timeout_seconds=10,
        cancel_grace_seconds=5,
    )
    record = await _spawn(manager)
    await asyncio.wait_for(started.wait(), timeout=1)

    await manager._watchdog_tick(record.last_heartbeat_at + 10)
    await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
    requested_at = record.cancel_requested_at
    assert requested_at is not None

    newly_stale = await manager._watchdog_tick(requested_at + 5)
    assert newly_stale == [record]
    for stale_record in newly_stale:
        manager._schedule_parent_wakeup(stale_record)
    await asyncio.sleep(0)
    assert record.status == SubagentStatus.STALE
    assert await manager._watchdog_tick(requested_at + 10) == []
    assert len(workspace.channel_manager.enqueued) == 1

    stale_events = await manager.drain_events("console:parent")
    assert [event.status for event in stale_events] == [SubagentStatus.STALE]
    # STALE is non-terminal: the handle and concurrency ownership remain.
    assert await manager.get(record.task_id) is record

    release.set()
    terminal = await _wait_terminal(manager, record.task_id)
    assert terminal.status == SubagentStatus.COMPLETED
    completed_events = await manager.drain_events("console:parent")
    assert [event.status for event in completed_events] == [
        SubagentStatus.COMPLETED,
    ]


@pytest.mark.asyncio
async def test_watchdog_loop_pause_renews_leases_instead_of_killing(tmp_path):
    gate = asyncio.Event()

    async def stream(_request):
        await gate.wait()
        if False:
            yield None

    workspace = _Workspace(tmp_path, stream)
    manager = SubagentTaskManager(workspace)
    record = await _spawn(manager)
    await asyncio.sleep(0)

    resumed_at = record.last_heartbeat_at + 1000
    await manager._reset_leases_after_loop_pause(resumed_at)
    assert record.last_heartbeat_at == resumed_at
    assert record.status == SubagentStatus.RUNNING
    assert not record.asyncio_task.done()

    await manager.cancel_task(record.task_id, notify_parent=False)
    await asyncio.gather(record.asyncio_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_parent_kill_suppresses_stale_and_late_completion(tmp_path):
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()

    async def stream(_request):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
        await release.wait()
        yield _completed_message("too late")

    workspace = _Workspace(tmp_path, stream)
    manager = SubagentTaskManager(workspace, cancel_grace_seconds=5)
    record = await _spawn(manager)
    await asyncio.wait_for(started.wait(), timeout=1)

    assert await manager.cancel_by_parent("console:parent") == 1
    await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
    requested_at = record.cancel_requested_at
    assert requested_at is not None
    assert await manager.cancel_by_parent("console:parent") == 0
    assert record.cancel_requested_at == requested_at
    assert await manager._watchdog_tick(requested_at + 5) == []
    assert record.status == SubagentStatus.STALE
    assert not await manager.has_pending_events("console:parent")

    release.set()
    await asyncio.gather(record.asyncio_task, return_exceptions=True)
    assert not await manager.has_pending_events("console:parent")
    assert not workspace.channel_manager.enqueued


@pytest.mark.asyncio
async def test_concurrency_guard_and_nested_subagent_rejection(tmp_path):
    gate = asyncio.Event()

    async def stream(_request):
        await gate.wait()
        if False:
            yield None

    workspace = _Workspace(tmp_path, stream)
    manager = SubagentTaskManager(
        workspace,
        max_running_per_parent=1,
    )
    await manager.start()
    first = await _spawn(manager)

    with pytest.raises(RuntimeError, match="limit reached"):
        await _spawn(manager, child_session_id="sub-second")
    with pytest.raises(ValueError, match="nested subagents are not supported"):
        await _spawn(
            manager,
            parent_session_id="different-parent",
            child_session_id="sub-nested",
            parent_is_subagent=True,
        )

    await manager.cancel_task(first.task_id)
    await _wait_terminal(manager, first.task_id)
    await manager.stop()


@pytest.mark.asyncio
async def test_inbox_middleware_injects_hint_once(tmp_path):
    async def stream(_request):
        yield _completed_message("useful result")

    workspace = _Workspace(tmp_path, stream)
    manager = SubagentTaskManager(workspace)
    await manager.start()
    record = await _spawn(manager)
    await _wait_terminal(manager, record.task_id)

    agent = SimpleNamespace(
        name="QwenPaw",
        state=SimpleNamespace(
            # AS2 owns an internal session id that is intentionally distinct
            # from QwenPaw's routing/session id.
            session_id="as2-internal-session",
            reply_id="reply-1",
            context=[AssistantMsg("QwenPaw", "parent context")],
        ),
    )

    async def downstream(**_kwargs):
        yield "model-event"

    middleware = SubagentInboxMiddleware(manager, "console:parent")
    output = [
        item
        async for item in middleware.on_reasoning(
            agent,
            {"tool_choice": None},
            downstream,
        )
    ]

    assert output[-1] == "model-event"
    hint = agent.state.context[-1].content[-1]
    assert "useful result" in hint.hint
    assert "Do not call a polling" in hint.hint
    claim_id = agent._qwenpaw_subagent_event_claim_id
    assert await manager.has_pending_events("console:parent")
    assert await manager.ack_events(claim_id) == 1
    assert not await manager.has_pending_events("console:parent")
    assert await manager.get(record.task_id) is None
    await manager.stop()


def test_channel_metadata_filters_secrets_and_runtime_objects():
    safe = SubagentTaskManager._routing_meta(
        {
            "channel_id": "123",
            "session_webhook": "https://secret.example",
            "access_token": "secret",
            "reply_future": object(),
        },
    )
    assert safe == {"channel_id": "123"}


@pytest.mark.asyncio
async def test_wakeup_guard_keeps_event_while_parent_waits_for_approval():
    class _Manager:
        async def has_pending_events(self, _session_id):
            return True

    from agentscope.message import ToolCallState

    last = SimpleNamespace(
        get_content_blocks=lambda _kind: [
            SimpleNamespace(state=ToolCallState.ASKING),
        ],
    )
    ctx = SimpleNamespace(
        request=SimpleNamespace(
            request_context={"subagent_wakeup": True},
        ),
        workspace=SimpleNamespace(subagent_task_manager=_Manager()),
        session_id="console:parent",
        agent=SimpleNamespace(
            state=SimpleNamespace(context=[last]),
        ),
    )

    result = await SubagentWakeGuardHook().run(ctx)

    assert result.action == HookAction.SKIP_AGENT


@pytest.mark.asyncio
async def test_subagent_toolkit_hides_delegation_tools(tmp_path):
    registry = ToolRegistry()

    async def spawn_subagent():
        return None

    async def cancel_subagent():
        return None

    async def read_file():
        return None

    for tool in (spawn_subagent, cancel_subagent, read_file):
        registry.register(ToolDescriptor(name=tool.__name__, func=tool))
    workspace = QwenPawLocalWorkspace(
        tool_registry=registry,
        workdir=str(tmp_path),
        workspace_id="default",
        default_mcps=[],
        skill_paths=[],
    )

    tools = await workspace.list_tools(
        request_context={"is_subagent": True},
    )
    names = {tool.name for tool in tools}

    assert names == {"read_file"}
