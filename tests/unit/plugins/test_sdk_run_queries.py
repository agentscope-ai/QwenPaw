# -*- coding: utf-8 -*-
"""Run queries use real Runtime dispatch and enforce exact request ownership."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.commands import CommandResult, CommandSpec
from qwenpaw.plugins.events import EventSubscription, RunEvent
from qwenpaw.plugins.messages import ContentBlock, Message
from qwenpaw.plugins.errors import StaleContextError
from qwenpaw.plugins._events import observe_stream
from qwenpaw.plugins._runs import current_run, index
from qwenpaw.schemas import AgentRequest


async def test_real_runs_query_snapshot_identity_and_reused_request_id(
    sdk_component,
):
    from qwenpaw.plugins.apps import ChatRequest

    received, retained, current_ids = [], [], set()

    def declare(ctx):
        async def query(call, arguments):
            retained.append(call.runs)
            current = await call.runs.current()
            if current:
                assert current.user_id == call.identity.user_id
                assert current.workspace_id == call.identity.workspace_id
                assert current.session_id == call.identity.session_id
                current_ids.add(current.run_id)
            visible = await call.runs.list()
            selected = await call.runs.get(arguments) if arguments else None
            payload = {
                "current": current.run_id if current else None,
                "visible": [item.run_id for item in visible],
                "selected": selected.run_id if selected else None,
            }
            return CommandResult(
                "reply",
                Message(
                    "assistant",
                    (ContentBlock(text=json.dumps(payload)),),
                ),
            )

        async def observe(call, event):
            if isinstance(event, RunEvent):
                received.append((event, await call.runs.get(event.run_id)))

        ctx.register_command(CommandSpec("runs", query))
        ctx.on_activate(
            lambda active: active.subscribe_events(EventSubscription(observe)),
        )

    async with sdk_component(declare, capabilities=("commands", "events")) as (
        host,
        ctx,
    ):

        async def run(user, session, workspace="one"):
            return [
                event
                async for event in host.stream_chat(
                    ChatRequest(
                        "/runs",
                        session_id=session,
                        request_id="reused-client-id",
                    ),
                    workspace_id=workspace,
                    user_id=user,
                )
            ]

        await asyncio.gather(
            run("alice", "shared"),
            run("bob", "shared"),
            run("alice", "different"),
        )
        await run("alice", "shared", "two")
        async with asyncio.timeout(5):
            while (
                len(
                    [
                        event
                        for event, _ in received
                        if event.kind == "run.completed"
                    ],
                )
                < 4
            ):
                await asyncio.sleep(0.01)
        started = [
            event for event, _ in received if event.kind == "run.started"
        ]
        completed = [
            event for event, _ in received if event.kind == "run.completed"
        ]
        assert len({event.snapshot.run_id for event in started}) == 4
        assert current_ids == {event.snapshot.run_id for event in started}
        assert all(event.run_id == "reused-client-id" for event in started)
        assert all(
            event.snapshot.status == "running"
            and event.snapshot.finished_at is None
            for event in started
        )
        assert all(
            event.snapshot.status == "completed"
            and event.snapshot.finished_at >= event.snapshot.started_at
            for event in completed
        )
        alice = next(
            event
            for event in completed
            if event.user_id == "alice"
            and event.session_id == "shared"
            and event.workspace_id == "one"
        )
        for user, session, workspace, allowed in (
            ("alice", "shared", "one", True),
            ("bob", "shared", "one", False),
            ("alice", "different", "one", False),
            ("alice", "shared", "two", False),
        ):
            result = await host.call_command(
                f"/runs {alice.snapshot.run_id}",
                workspace_id=workspace,
                session_id=session,
                user_id=user,
            )
            payload = json.loads(result.content[0].text)
            assert payload["current"] is None
            assert (alice.snapshot.run_id in payload["visible"]) is allowed
            assert bool(payload["selected"]) is allowed
        with pytest.raises(StaleContextError):
            await retained[0].list()


async def test_cancelled_runtime_keeps_terminal_snapshot(sdk_component):
    entered, finished = asyncio.Event(), asyncio.Event()
    events = []

    def declare(ctx):
        async def slow(call, arguments):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        async def observe(call, event):
            if isinstance(event, RunEvent):
                events.append(event)

        ctx.register_command(CommandSpec("slow-run", slow))
        ctx.on_activate(
            lambda active: active.subscribe_events(EventSubscription(observe)),
        )

    async with sdk_component(declare, capabilities=("commands", "events")) as (
        host,
        ctx,
    ):

        async def run():
            return [event async for event in host.stream_chat("/slow-run")]

        task = asyncio.create_task(run())
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        async with asyncio.timeout(5):
            while not any(event.kind == "run.cancelled" for event in events):
                await asyncio.sleep(0.01)
        terminal = next(
            event for event in events if event.kind == "run.cancelled"
        )
        assert terminal.snapshot.status == "cancelled"
        assert terminal.snapshot.finished_at is not None


@pytest.mark.parametrize("as_mapping", [False, True])
@pytest.mark.parametrize(
    "identity_fields",
    [
        {"session_id": "s", "user_id": "alice"},
        {"session_id": "s"},
        {"user_id": "alice"},
        {},
    ],
)
async def test_approval_origin_is_bound_only_with_matching_host_identity(
    sdk_component,
    as_mapping,
    identity_fields,
):
    from qwenpaw.app.approvals.service import get_approval_service
    from qwenpaw.app.approvals.models import ApprovalRequestSummary
    from qwenpaw.security.tool_guard.approval import ApprovalDecision
    from qwenpaw.plugins.events import ApprovalEvent

    observed, expected = [], {}

    def declare(ctx):
        async def request(call, arguments):
            current = await call.runs.current()
            identity = call.identity
            assert current is not None
            assert await call.runs.get(current.run_id) == current
            assert (
                current.workspace_id,
                current.session_id,
                current.user_id,
                current.channel,
            ) == (
                identity.workspace_id,
                identity.session_id,
                identity.user_id,
                identity.channel,
            )
            assert identity.session_id
            if "session_id" in identity_fields:
                assert identity.session_id == identity_fields["session_id"]
            assert identity.user_id == identity_fields.get(
                "user_id",
                identity.session_id,
            )
            service = get_approval_service()
            for user in (identity.user_id, "someone-else"):
                pending = await service.create_pending_summary(
                    session_id=identity.session_id,
                    root_session_id=identity.session_id,
                    owner_agent_id=identity.workspace_id,
                    agent_id=identity.workspace_id,
                    user_id=user,
                    channel=identity.channel,
                    summary=ApprovalRequestSummary("sdk-test", "confirm"),
                )
                expected[pending.request_id] = (
                    current.run_id if user == identity.user_id else None
                )
                await service.resolve_request(
                    pending.request_id,
                    ApprovalDecision.APPROVED,
                )
            return CommandResult(
                "reply",
                Message("assistant", (ContentBlock(text="done"),)),
            )

        async def observe(call, event):
            if isinstance(event, ApprovalEvent):
                observed.append(event)

        ctx.register_command(CommandSpec("approval-origin", request))
        ctx.on_activate(
            lambda active: active.subscribe_events(EventSubscription(observe)),
        )

    async with sdk_component(declare, capabilities=("commands", "events")) as (
        host,
        ctx,
    ):
        workspace = await host._workspace("test")
        request = {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "/approval-origin"},
                    ],
                },
            ],
            "channel": "console",
            **identity_fields,
        }
        if not as_mapping:
            request = AgentRequest(**request)
        events = [event async for event in workspace.stream_query(request)]
        assert any(
            getattr(event, "status", None) == "completed" for event in events
        )
        async with asyncio.timeout(5):
            while len(observed) < 4:
                await asyncio.sleep(0.01)
        assert {event.kind for event in observed} == {
            "approval.pending",
            "approval.approved",
        }
        for event in observed:
            assert event.approval.run_id == expected[event.approval.request_id]


async def test_run_normalization_preserves_unknown_channel_actor(
    fresh_registry,
):
    request = AgentRequest(session_id="room", user_id="", channel="mqtt")
    request._channel_actor_unknown = True
    runs = index(fresh_registry)

    @observe_stream
    async def stream(workspace, normalized):
        assert normalized is request
        snapshot = runs.snapshots[current_run.get()]
        assert (
            snapshot.workspace_id,
            snapshot.session_id,
            snapshot.user_id,
            snapshot.channel,
        ) == (workspace.agent_id, "room", "", "mqtt")
        assert normalized.user_id == ""
        assert normalized._channel_actor_unknown is True
        yield {"object": "response", "status": "completed"}

    events = [
        event
        async for event in stream(SimpleNamespace(agent_id="test"), request)
    ]
    assert events == [{"object": "response", "status": "completed"}]
