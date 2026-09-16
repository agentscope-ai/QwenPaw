# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Durable task invariants using independent SQLite connections/reopens."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from qwenpaw.pawapp.task import SSEChannel
from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    CommandLookup,
    ExecutorEvent,
    ExecutorRunRef,
    TaskOrigin,
    TaskScope,
    TaskStore,
    TaskStoreError,
    SubmissionLookup,
    TaskCoordinator,
)


@pytest.fixture
def action():
    path = (
        Path(__file__).resolve().parents[3]
        / "docs/design/pawapp-vnext-data-action.example.json"
    )
    return ActionDescriptor.model_validate_json(path.read_text())


@pytest.fixture
def scope():
    return TaskScope(
        principal_id="alice",
        workspace_id="workspace-a",
        app_id="qwenpaw-data",
    )


@pytest.fixture
def origin():
    return TaskOrigin(
        engagement="delegated",
        origin_ref="chat:1",
        return_session_ref="chat:1",
    )


@pytest.fixture
async def store(tmp_path):
    return await TaskStore.open(tmp_path / "host/tasks.sqlite3")


async def create(store, scope, action, origin, request_id="request-1"):
    return await store.create(
        scope,
        action,
        request_id=request_id,
        inputs={"text": "Analyze revenue", "datasource_id": "sales"},
        origin=origin,
    )


def run_ref(suffix="1"):
    return ExecutorRunRef(
        executor_id="data-engine",
        session_id=f"session-{suffix}",
        run_id=f"run-{suffix}",
    )


async def accept(store, scope, action, origin):
    submission = await create(store, scope, action, origin)
    task_id = submission.handle.task_id
    assert await store.begin_submission(scope, task_id)
    return await store.record_accepted(scope, task_id, run_ref())


async def wait_for_period(store, scope, task_id):
    return await store.apply_event(
        scope,
        task_id,
        ExecutorEvent(
            run_ref=run_ref(),
            sequence=0,
            cursor="0",
            status="waiting_for_input",
            detail={
                "input_request": {
                    "request_id": "clarification-1",
                    "title": "Choose a period",
                    "questions": [
                        {
                            "question": "Which period?",
                            "options": [{"label": "Q1"}, {"label": "Q2"}],
                        },
                    ],
                },
            },
        ),
    )


@pytest.mark.asyncio
async def test_concurrent_retries_allocate_one_durable_identity(
    store,
    scope,
    action,
    origin,
):
    other = await TaskStore.open(store.path)
    submissions = await asyncio.gather(
        *(
            create(store if i % 2 else other, scope, action, origin)
            for i in range(12)
        ),
    )
    task_ids = {submission.handle.task_id for submission in submissions}
    assert len(task_ids) == 1
    assert len({s.handle.submission_id for s in submissions}) == 1
    task_id = task_ids.pop()
    wins = await asyncio.gather(
        *(
            (store if i % 2 else other).begin_submission(scope, task_id)
            for i in range(12)
        ),
    )
    assert sum(wins) == 1
    reopened = await TaskStore.open(store.path)
    stored = await reopened.get(scope, task_id)
    assert stored.handle.submission_state == "in_flight"
    assert [event.kind for event in await reopened.events(scope, task_id)] == [
        "created",
        "submission",
    ]


@pytest.mark.asyncio
async def test_answer_commands_are_scoped_validated_and_idempotent(
    store,
    scope,
    action,
    origin,
):
    task = await accept(store, scope, action, origin)
    await wait_for_period(store, scope, task.handle.task_id)
    assert await store.recoverable() == []
    kwargs = {
        "command_id": "answer-1",
        "request_id": "clarification-1",
        "answers": [
            {"question": "Which period?", "selected_options": ["Q1"]},
        ],
    }
    first = await store.prepare_answer(scope, task.handle.task_id, **kwargs)
    assert [item.handle.task_id for item in await store.recoverable()] == [
        task.handle.task_id,
    ]
    retry = await store.prepare_answer(scope, task.handle.task_id, **kwargs)
    assert retry == first
    with pytest.raises(TaskStoreError, match="command_conflict"):
        await store.prepare_answer(
            scope,
            task.handle.task_id,
            **{
                **kwargs,
                "answers": [
                    {
                        "question": "Which period?",
                        "selected_options": ["Q2"],
                    },
                ],
            },
        )
    with pytest.raises(TaskStoreError, match="invalid_task_answer"):
        await store.prepare_answer(
            scope,
            task.handle.task_id,
            command_id="answer-invalid",
            request_id="clarification-1",
            answers=[
                {"question": "Which period?", "selected_options": ["Q3"]},
            ],
        )
    other = scope.model_copy(update={"principal_id": "mallory"})
    with pytest.raises(TaskStoreError, match="task_not_found"):
        await store.command(other, task.handle.task_id, first.command_id)


@pytest.mark.asyncio
async def test_cancel_before_submission_is_terminal_without_executor_run(
    store,
    scope,
    action,
    origin,
):
    task = await create(store, scope, action, origin)
    command = await store.prepare_cancel(
        scope,
        task.handle.task_id,
        reason="No longer needed",
    )
    assert command.state == "accepted"
    cancelled = await store.get(scope, task.handle.task_id)
    assert cancelled.handle.status == "cancelled"
    assert cancelled.handle.cancel_requested is True
    assert not await store.begin_submission(scope, task.handle.task_id)
    assert (
        await store.prepare_cancel(
            scope,
            task.handle.task_id,
            reason="A different retry reason",
        )
        == command
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["inputs", "origin", "action"])
async def test_reused_request_identity_rejects_changed_meaning(
    store,
    scope,
    action,
    origin,
    changed,
):
    await create(store, scope, action, origin)
    inputs = {"text": "Analyze revenue", "datasource_id": "sales"}
    if changed == "inputs":
        inputs["datasource_id"] = "another"
    elif changed == "origin":
        origin = origin.model_copy(
            update={"return_session_ref": "another-chat"},
        )
    else:
        action = action.model_copy(
            update={"permissions": ("extra-permission",)},
        )
    with pytest.raises(TaskStoreError, match="request_conflict"):
        await store.create(
            scope,
            action,
            request_id="request-1",
            inputs=inputs,
            origin=origin,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["principal_id", "workspace_id", "app_id"])
async def test_all_storage_access_is_scoped(
    store,
    scope,
    action,
    origin,
    field,
):
    submission = await accept(store, scope, action, origin)
    task_id = submission.handle.task_id
    other_scope = scope.model_copy(update={field: "other"})
    delivery = (await store.pending_deliveries(scope, task_id))[0]
    operations = [
        lambda: store.get(other_scope, task_id),
        lambda: store.events(other_scope, task_id),
        lambda: store.begin_submission(other_scope, task_id),
        lambda: store.record_accepted(other_scope, task_id, run_ref()),
        lambda: store.apply_event(
            other_scope,
            task_id,
            ExecutorEvent(
                run_ref=run_ref(),
                sequence=0,
                cursor="0",
                status="running",
            ),
        ),
        lambda: store.mark_recovery(
            other_scope,
            task_id,
            state="unresolved",
            reason="unknown",
        ),
        lambda: store.pending_deliveries(other_scope, task_id),
        lambda: store.acknowledge(other_scope, delivery),
    ]
    for operation in operations:
        with pytest.raises(TaskStoreError, match="task_not_found"):
            await operation()


@pytest.mark.asyncio
async def test_run_mapping_cannot_be_replaced_or_shared(
    store,
    scope,
    action,
    origin,
):
    first = await accept(store, scope, action, origin)
    with pytest.raises(TaskStoreError, match="run_conflict"):
        await store.record_accepted(scope, first.handle.task_id, run_ref("2"))
    second = await create(store, scope, action, origin, request_id="request-2")
    await store.begin_submission(scope, second.handle.task_id)
    with pytest.raises(TaskStoreError, match="run_conflict"):
        await store.record_accepted(scope, second.handle.task_id, run_ref())


@pytest.mark.asyncio
async def test_replay_preserves_sequences_and_terminal_state(
    store,
    scope,
    action,
    origin,
):
    submission = await accept(store, scope, action, origin)
    task_id = submission.handle.task_id
    event = ExecutorEvent(
        run_ref=run_ref(),
        sequence=8,
        cursor="opaque:8",
        status="running",
        text_result="partial result",
    )
    first = await store.apply_event(scope, task_id, event)
    assert first.handle.event_sequence == 4
    assert first.handle.executor_sequence == 8
    assert await store.apply_event(scope, task_id, event) == first
    with pytest.raises(TaskStoreError, match="event_conflict"):
        await store.apply_event(
            scope,
            task_id,
            event.model_copy(update={"text_result": "different"}),
        )
    with pytest.raises(TaskStoreError, match="event_out_of_order"):
        await store.apply_event(
            scope,
            task_id,
            event.model_copy(update={"sequence": 7}),
        )
    terminal_event = ExecutorEvent(
        run_ref=run_ref(),
        sequence=9,
        cursor="opaque:9",
        status="succeeded",
    )
    completed = await store.apply_event(scope, task_id, terminal_event)
    assert completed.handle.text_result == "partial result"
    assert await store.apply_event(scope, task_id, terminal_event) == completed
    with pytest.raises(TaskStoreError, match="task_terminal"):
        await store.apply_event(
            scope,
            task_id,
            terminal_event.model_copy(
                update={"sequence": 10, "status": "failed"},
            ),
        )
    assert (
        await store.mark_recovery(
            scope,
            task_id,
            state="unresolved",
            reason="late_eof",
        )
        == completed
    )


@pytest.mark.asyncio
async def test_event_outbox_failure_rolls_back_status_result_and_cursor(
    store,
    scope,
    action,
    origin,
):
    before = await accept(store, scope, action, origin)
    task_id = before.handle.task_id
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_delivery
            BEFORE INSERT ON task_deliveries BEGIN
            SELECT RAISE(ABORT, 'injected outbox failure'); END""",
        )
    event = ExecutorEvent(
        run_ref=run_ref(),
        sequence=0,
        cursor="0",
        status="succeeded",
        text_result="report",
    )
    with pytest.raises(
        sqlite3.IntegrityError,
        match="injected outbox failure",
    ):
        await store.apply_event(scope, task_id, event)
    reopened = await TaskStore.open(store.path)
    assert await reopened.get(scope, task_id) == before
    assert len(await reopened.events(scope, task_id)) == 3
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TRIGGER reject_delivery")
    completed = await reopened.apply_event(scope, task_id, event)
    assert completed.handle.status == "succeeded"
    assert completed.handle.replay_cursor == "0"
    assert completed.handle.text_result == "report"


@pytest.mark.asyncio
@pytest.mark.parametrize("engagement", ["direct", "delegated"])
async def test_delivery_recovery_respects_origin_and_persists_receipts(
    store,
    scope,
    action,
    origin,
    engagement,
):
    if engagement == "direct":
        origin = TaskOrigin(
            engagement="direct",
            origin_ref="app",
            app_session_ref="app-session",
        )
    submission = await accept(store, scope, action, origin)
    task_id = submission.handle.task_id
    await store.apply_event(
        scope,
        task_id,
        ExecutorEvent(
            run_ref=run_ref(),
            sequence=0,
            cursor="0",
            status="waiting_for_input",
            detail={
                "input_request": {
                    "request_id": "clarification-1",
                    "questions": [
                        {
                            "question": "Which period?",
                            "options": [
                                {"label": "Q1"},
                                {"label": "Q2"},
                            ],
                        },
                    ],
                },
            },
        ),
    )
    await store.apply_event(
        scope,
        task_id,
        ExecutorEvent(
            run_ref=run_ref(),
            sequence=1,
            cursor="1",
            status="succeeded",
            text_result="report",
        ),
    )
    reopened = await TaskStore.open(store.path)
    pending = await reopened.pending_deliveries(scope, task_id)
    continuations = [item for item in pending if item.kind == "continuation"]
    assert len(continuations) == (2 if engagement == "delegated" else 0)
    assert {item.target_ref for item in pending} == {
        "chat:1" if engagement == "delegated" else "app-session",
    }
    for item in pending:
        await reopened.acknowledge(scope, item)
        await reopened.acknowledge(scope, item)
    reopened = await TaskStore.open(store.path)
    assert await reopened.pending_deliveries(scope, task_id) == []
    assert (await reopened.get(scope, task_id)).handle.text_result == "report"


@pytest.mark.asyncio
async def test_success_requires_persisted_result(store, scope, action, origin):
    submission = await accept(store, scope, action, origin)
    with pytest.raises(TaskStoreError, match="result_required"):
        await store.apply_event(
            scope,
            submission.handle.task_id,
            ExecutorEvent(
                run_ref=run_ref(),
                sequence=0,
                cursor="0",
                status="succeeded",
            ),
        )


@pytest.mark.asyncio
async def test_database_version_and_private_permissions(store):
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(TaskStoreError, match="unsupported_store_version"):
        await TaskStore.open(store.path)


def test_descriptor_validates_inputs_and_uses_stable_digest(action):
    copied = ActionDescriptor.model_validate_json(action.model_dump_json())
    assert copied.descriptor_digest == action.descriptor_digest
    action.validate_inputs({"text": "revenue", "datasource_id": "sales"})
    with pytest.raises(ValueError, match="invalid action input") as error:
        action.validate_inputs(
            {"text": {"secret": "never-echo-this"}, "datasource_id": "sales"},
        )
    assert "never-echo-this" not in str(error.value)
    with pytest.raises(ValueError):
        action.validate_inputs(
            {
                "text": "revenue",
                "datasource_id": "sales",
                "adapter_ref": "other",
            },
        )
    data = action.model_dump(mode="json")
    data["input_schema"]["properties"]["text"] = {
        "$ref": "https://invalid/schema.json",
    }
    with pytest.raises(ValidationError, match="local refs"):
        ActionDescriptor.model_validate(data)


def test_origin_contract_keeps_direct_out_of_main_chat():
    with pytest.raises(ValidationError):
        TaskOrigin(engagement="delegated", origin_ref="chat:1")
    with pytest.raises(ValidationError):
        TaskOrigin(
            engagement="direct",
            origin_ref="app",
            app_session_ref="app-session",
            return_session_ref="chat:1",
        )


class ProtocolFixture:
    """Simulates a surviving remote executor for Host-only recovery tests."""

    submission_protocol_version = 1

    def __init__(self):
        self.runs = {}
        self.submitted_ids = []
        self.queried_ids = []
        self.events = []
        self.cursors = []
        self.fault = None
        self.unknown = False
        self.closed = False
        self.commands = {}
        self.command_calls = []
        self.command_fault = None

    async def submit(self, submission):
        submission_id = submission.handle.submission_id
        self.submitted_ids.append(submission_id)
        if self.fault == "before_accept":
            self.fault = None
            raise TimeoutError("injected before executor acceptance")
        ref = self.runs.setdefault(
            submission_id,
            run_ref(str(len(self.runs) + 1)),
        )
        if self.fault == "after_accept":
            self.fault = None
            raise TimeoutError("injected after executor acceptance")
        return ref

    async def query(self, submission):
        submission_id = submission.handle.submission_id
        self.queried_ids.append(submission_id)
        if self.unknown:
            return SubmissionLookup(state="unknown")
        ref = self.runs.get(submission_id)
        return SubmissionLookup(
            state="accepted" if ref else "not_found",
            run_ref=ref,
        )

    async def attach(self, submission):
        ref = submission.handle.executor_run_ref
        cursor = submission.handle.replay_cursor
        self.cursors.append(cursor)
        try:
            for event in self.events:
                if event.run_ref == ref and (
                    cursor is None or event.sequence > int(cursor)
                ):
                    yield event
        finally:
            self.closed = True

    async def command(self, submission, command):
        del submission
        self.command_calls.append(command.command_id)
        if self.command_fault == "before_accept":
            self.command_fault = None
            raise TimeoutError("injected before command acceptance")
        result = self.commands.setdefault(
            command.command_id,
            CommandLookup(state="accepted"),
        )
        if self.command_fault == "after_accept":
            self.command_fault = None
            raise TimeoutError("injected after command acceptance")
        return result

    async def query_command(self, submission, command):
        del submission
        return self.commands.get(
            command.command_id,
            CommandLookup(state="not_found"),
        )


async def fixture_policy(scope, action, origin, inputs):
    """Tests grant this one action; production must supply Host policy."""
    assert scope.principal_id == "alice"
    assert action.permissions == (
        "data.analysis.execute",
        "data.datasource.read",
    )
    assert origin.engagement in action.engagements
    assert inputs["datasource_id"] in {"sales", "cost"}


def coordinator(store, action, engine):
    result = TaskCoordinator(store, authorize=fixture_policy)
    result.register(action, engine)
    return result


async def dispatch(boundary, scope, origin):
    return await boundary.dispatch(
        scope,
        "analyze",
        request_id="request-1",
        inputs={"text": "Analyze revenue", "datasource_id": "sales"},
        origin=origin,
    )


async def test_consumer_closes_executor_stream_on_terminal(
    store,
    scope,
    action,
    origin,
):
    engine = ProtocolFixture()
    boundary = coordinator(store, action, engine)
    task = await dispatch(boundary, scope, origin)
    engine.events = [
        ExecutorEvent(
            run_ref=task.handle.executor_run_ref,
            sequence=0,
            cursor="0",
            status="succeeded",
            text_result="done",
        ),
    ]
    await boundary.consume(scope, task.handle.task_id)
    assert engine.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["before_accept", "after_accept"])
async def test_reconcile_after_host_restart_uses_original_submission(
    store,
    scope,
    action,
    origin,
    fault,
):
    engine = ProtocolFixture()
    engine.fault = fault
    boundary = coordinator(store, action, engine)
    with pytest.raises(TimeoutError):
        await dispatch(boundary, scope, origin)
    original = await create(store, scope, action, origin)
    assert original.handle.recovery_state == "reconciling"
    restarted = coordinator(await TaskStore.open(store.path), action, engine)
    recovered = await restarted.reconcile(scope, original.handle.task_id)
    assert recovered.handle.task_id == original.handle.task_id
    assert recovered.handle.submission_id == original.handle.submission_id
    assert recovered.handle.executor_run_ref == run_ref()
    assert recovered.handle.recovery_state == "none"
    assert len(engine.runs) == 1
    assert set(engine.submitted_ids) == {original.handle.submission_id}
    assert engine.queried_ids == [original.handle.submission_id]
    assert len(engine.submitted_ids) == (2 if fault == "before_accept" else 1)


@pytest.mark.asyncio
async def test_eof_unknown_then_late_terminal_preserves_partial_output(
    store,
    scope,
    action,
    origin,
):
    engine = ProtocolFixture()
    boundary = coordinator(store, action, engine)
    submitted = await dispatch(boundary, scope, origin)
    task_id = submitted.handle.task_id
    engine.events.append(
        ExecutorEvent(
            run_ref=run_ref(),
            sequence=0,
            cursor="0",
            status="running",
            text_result="durable report",
        ),
    )
    partial = await boundary.consume(scope, task_id)
    assert partial.handle.status == "running"
    assert partial.handle.recovery_reason == "stream_eof"
    assert partial.handle.replay_cursor == "0"
    restarted = coordinator(await TaskStore.open(store.path), action, engine)
    engine.unknown = True
    unknown = await restarted.reconcile(scope, task_id)
    assert unknown.handle.status == "running"
    assert unknown.handle.recovery_state == "unresolved"
    assert unknown.handle.text_result == "durable report"
    assert not [
        item
        for item in await store.pending_deliveries(scope, task_id)
        if item.kind == "continuation"
    ]
    engine.unknown = False
    engine.events.append(
        ExecutorEvent(
            run_ref=run_ref(),
            sequence=1,
            cursor="1",
            status="succeeded",
        ),
    )
    await restarted.reconcile(scope, task_id)
    completed = await restarted.consume(scope, task_id)
    assert completed.handle.status == "succeeded"
    assert completed.handle.text_result == "durable report"
    assert completed.handle.recovery_state == "none"
    assert engine.cursors == [None, "0"]
    assert len(engine.submitted_ids) == 1
    pending = await store.pending_deliveries(scope, task_id)
    assert len([item for item in pending if item.kind == "continuation"]) == 1
    # Reopen after terminal commit but before the destination acknowledges.
    last = coordinator(await TaskStore.open(store.path), action, engine)
    assert await last.consume(scope, task_id) == completed
    assert await last.store.pending_deliveries(scope, task_id) == pending


@pytest.mark.asyncio
async def test_missing_previously_accepted_run_never_creates_replacement(
    store,
    scope,
    action,
    origin,
):
    engine = ProtocolFixture()
    boundary = coordinator(store, action, engine)
    submitted = await dispatch(boundary, scope, origin)
    engine.runs.clear()
    recovered = await boundary.reconcile(scope, submitted.handle.task_id)
    assert recovered.handle.recovery_state == "unresolved"
    assert recovered.handle.executor_run_ref == run_ref()
    assert recovered.handle.status == "pending"
    assert len(engine.submitted_ids) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["before_accept", "after_accept"])
async def test_command_recovery_reuses_durable_identity(
    store,
    scope,
    action,
    origin,
    fault,
):
    engine = ProtocolFixture()
    boundary = coordinator(store, action, engine)
    task = await dispatch(boundary, scope, origin)
    await wait_for_period(store, scope, task.handle.task_id)
    command = await store.prepare_answer(
        scope,
        task.handle.task_id,
        command_id="answer-recovery",
        request_id="clarification-1",
        answers=[
            {"question": "Which period?", "selected_options": ["Q1"]},
        ],
    )
    engine.command_fault = fault
    first = await boundary.deliver_command(
        scope,
        task.handle.task_id,
        command.command_id,
    )
    if fault == "after_accept":
        assert first.state == "accepted"
    else:
        assert first.state == "unknown"
        reopened = coordinator(
            await TaskStore.open(store.path),
            action,
            engine,
        )
        first = await reopened.deliver_command(
            scope,
            task.handle.task_id,
            command.command_id,
        )
        assert first.state == "accepted"
    assert set(engine.command_calls) == {command.command_id}
    assert len(engine.commands) == 1


@pytest.mark.asyncio
async def test_dispatch_checks_policy_and_rejects_unready_adapter(
    store,
    scope,
    action,
    origin,
):
    engine = ProtocolFixture()

    async def deny(*_):
        raise PermissionError("action permission denied")

    boundary = TaskCoordinator(store, authorize=deny)
    boundary.register(action, engine)
    with pytest.raises(PermissionError):
        await dispatch(boundary, scope, origin)
    assert not engine.submitted_ids
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        )
    unsupported = TaskCoordinator(store, authorize=fixture_policy)
    engine.submission_protocol_version = 0
    with pytest.raises(
        TaskStoreError,
        match="unsupported_submission_protocol",
    ):
        unsupported.register(action, engine)


@pytest.mark.asyncio
async def test_dispatch_is_idempotent_and_descriptor_is_server_owned(
    store,
    scope,
    action,
    origin,
):
    engine = ProtocolFixture()
    boundary = coordinator(store, action, engine)
    original_digest = action.descriptor_digest
    # A caller changing the original/returned dict cannot replace registration.
    action.input_schema.clear()
    boundary.describe(scope.app_id, "analyze").input_schema.clear()
    assert (
        boundary.describe(scope.app_id, "analyze").descriptor_digest
        == original_digest
    )
    first, second = await asyncio.gather(
        dispatch(boundary, scope, origin),
        dispatch(boundary, scope, origin),
    )
    assert first.handle.task_id == second.handle.task_id
    assert len(engine.submitted_ids) == 1


@pytest.mark.asyncio
async def test_legacy_sse_channel_drains_on_close_even_when_full():
    channel = SSEChannel(max_buffer=1)
    await channel.send_event({"type": "progress"})
    channel.close()
    assert [event async for event in channel] == [
        'data: {"type": "progress"}\n\n',
    ]
    assert channel.is_closed


@pytest.mark.asyncio
async def test_concurrent_direct_and_delegated_tasks_keep_results_separate(
    store,
    scope,
    action,
    origin,
):
    engine = ProtocolFixture()
    boundary = coordinator(store, action, engine)
    delegated, direct = await asyncio.gather(
        dispatch(boundary, scope, origin),
        boundary.dispatch(
            scope,
            "analyze",
            request_id="direct-request",
            inputs={"text": "Analyze cost", "datasource_id": "cost"},
            origin=TaskOrigin(
                engagement="direct",
                origin_ref="app",
                app_session_ref="data-1",
            ),
        ),
    )
    assert delegated.handle.executor_run_ref != direct.handle.executor_run_ref
    for submission, text in ((delegated, "revenue"), (direct, "cost")):
        engine.events.append(
            ExecutorEvent(
                run_ref=submission.handle.executor_run_ref,
                sequence=0,
                cursor="0",
                status="succeeded",
                text_result=text,
            ),
        )
    first, second = await asyncio.gather(
        boundary.consume(scope, delegated.handle.task_id),
        boundary.consume(scope, direct.handle.task_id),
    )
    assert first.handle.text_result == "revenue"
    assert second.handle.text_result == "cost"
    assert not [
        item
        for item in await store.pending_deliveries(
            scope,
            direct.handle.task_id,
        )
        if item.kind == "continuation"
    ]


@pytest.mark.asyncio
async def test_policy_checks_resources_without_mutating_saved_inputs(
    store,
    scope,
    action,
    origin,
):
    engine = ProtocolFixture()

    async def policy(_scope, _action, _origin, inputs):
        if inputs["datasource_id"] != "sales":
            raise PermissionError("datasource is outside the allowed scope")
        inputs["datasource_id"] = "accidental-policy-mutation"

    boundary = TaskCoordinator(store, authorize=policy)
    boundary.register(action, engine)
    submitted = await dispatch(boundary, scope, origin)
    assert submitted.inputs["datasource_id"] == "sales"
    with pytest.raises(PermissionError, match="outside the allowed scope"):
        await boundary.dispatch(
            scope,
            "analyze",
            request_id="denied-request",
            inputs={
                "text": "read restricted data",
                "datasource_id": "restricted",
            },
            origin=origin,
        )
    assert len(engine.submitted_ids) == 1
