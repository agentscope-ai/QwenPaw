# -*- coding: utf-8 -*-
"""A neutral App exercises the shared Main Chat and SDK runtime."""

# pylint: disable=redefined-outer-name,protected-access

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.pawapp.artifacts import ArtifactStore
from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    ActionRegistration,
    ActionResult,
    TaskScope,
    TaskStore,
    TaskStoreError,
)
from qwenpaw.pawapp.tasks.contracts import (
    ExecutorEvent,
    ExecutorRunRef,
    TaskAnswer,
    TaskInputRequest,
    TaskOrigin,
    ProjectRef,
    TaskExperienceDefinition,
    content_digest,
)
from qwenpaw.pawapp.tasks.policy import FileTaskPolicy, TaskGrant, TaskPolicy
from qwenpaw.pawapp.tasks.runtime import HostTaskRuntime

SCOPE = TaskScope(
    principal_id="alice",
    workspace_id="sales",
    app_id="neutral-app",
)
ORIGIN = TaskOrigin(
    engagement="delegated",
    origin_ref="main",
    return_session_ref="chat-one",
)
ACTION = ActionDescriptor(
    app_id=SCOPE.app_id,
    action_id="inspect",
    summary="Inspect a value",
    engagements=("direct", "delegated"),
    input_schema={"type": "object"},
    adapter_ref="neutral.inspect.v1",
    output_types=("text/plain", "qwenpaw:file"),
    result_schema={
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
        "additionalProperties": False,
    },
)
QUESTION = TaskInputRequest(
    request_id="color",
    questions=(
        {
            "question": "Which color?",
            "options": [{"label": "Blue"}, {"label": "Green"}],
        },
    ),
)


@pytest.fixture
async def harness(tmp_path):
    store = await TaskStore.open(tmp_path / "tasks.db")
    artifacts = await ArtifactStore.open(tmp_path / "artifacts")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        TaskPolicy(
            grants=(
                TaskGrant(
                    scope=SCOPE,
                    action_id=ACTION.action_id,
                    descriptor_digest=ACTION.descriptor_digest,
                ),
            ),
        ).model_dump_json(),
    )
    runtimes = []

    async def start(
        handler,
        recovery="interrupt",
        action=ACTION,
        experience=None,
    ):
        registration = ActionRegistration(
            action=action,
            handler=handler,
            recovery=recovery,
            experience=experience,
        )
        runtime = HostTaskRuntime(
            store,
            policy=FileTaskPolicy(policy_path),
            registrations=lambda: {
                (SCOPE.app_id, action.action_id): registration,
            },
            authorize_origin=AsyncMock(),
            artifacts=artifacts,
            interval=0.01,
        )
        await runtime.start()
        runtimes.append(runtime)
        return runtime

    yield SimpleNamespace(
        start=start,
        store=store,
        artifacts=artifacts,
        policy=policy_path,
    )
    for runtime in runtimes:
        await runtime.aclose()


async def dispatch(runtime, request="one", origin=ORIGIN):
    return (
        await runtime.dispatch(
            SCOPE,
            ACTION.action_id,
            request_id=request,
            inputs={},
            origin=origin,
        )
    )["task"]


async def status(harness, task_id, expected):
    async with asyncio.timeout(4):
        while True:
            handle = (await harness.store.get(SCOPE, task_id)).handle
            if handle.status == expected:
                return handle
            await asyncio.sleep(0.01)


async def test_terminal_commit_between_stream_reads(harness, monkeypatch):
    from qwenpaw.pawapp.tasks import TaskCoordinator
    from qwenpaw.pawapp.tasks.managed import ManagedHandlerAdapter

    adapter = ManagedHandlerAdapter(
        harness.store,
        ActionRegistration(action=ACTION, handler=AsyncMock()),
    )
    coordinator = TaskCoordinator(harness.store, authorize=AsyncMock())
    coordinator.register(ACTION, adapter)
    submission = await coordinator.dispatch(
        SCOPE,
        ACTION.action_id,
        request_id="race",
        inputs={},
        origin=ORIGIN,
    )
    # Control exactly when the handler commits, without a background job.
    monkeypatch.setattr(adapter, "_ensure_job", AsyncMock())
    original_run = harness.store._run
    committed = False

    async def interleave(operation, **kwargs):
        nonlocal committed
        result = await original_run(operation, **kwargs)
        if (
            operation.__qualname__.endswith("attach.<locals>.read")
            and not committed
        ):
            committed = True
            await adapter.emit(
                submission,
                "done",
                status="succeeded",
                result_data={"answer": "complete"},
            )
        return result

    monkeypatch.setattr(harness.store, "_run", interleave)
    async with asyncio.timeout(2):
        done = await coordinator.consume(SCOPE, submission.handle.task_id)
    assert committed
    assert done.handle.status == "succeeded"
    assert done.handle.result_data == {"answer": "complete"}


async def test_explicit_failure_is_public_terminal_and_stops_handler(harness):
    continued = []

    async def handler(ctx):
        await ctx.fail(
            "revision-conflict",
            text="The document changed. Review it before retrying.",
        )
        continued.append(True)
        return ActionResult("This must not be published.", {"answer": "wrong"})

    runtime = await harness.start(handler, "replay_safe")
    task = await dispatch(runtime)
    failed = await status(harness, task.task_id, "failed")
    assert (
        failed.text_result
        == "The document changed. Review it before retrying."
    )
    assert failed.result_data is None
    assert not continued
    assert (await dispatch(runtime)).task_id == task.task_id


async def test_question_replay_artifact_and_scoped_reuse(harness):
    calls = []

    async def handler(ctx):
        calls.append(ctx.submission_id)
        await ctx.report("begin", text="Checking")
        await ctx.publish(
            source_id="note",
            name="note.txt",
            media_type="text/plain",
            content=b"reusable",
        )
        answers = await ctx.request_input(QUESTION)
        return ActionResult(
            "Checked",
            {"answer": answers[0].selected_options[0]},
        )

    runtime = await harness.start(handler, "replay_safe")
    task = await dispatch(runtime)
    waiting = await status(harness, task.task_id, "waiting_for_input")
    assert waiting.input_request == QUESTION
    assert (await dispatch(runtime)).task_id == task.task_id
    await runtime.aclose()
    runtime = await harness.start(handler, "replay_safe")
    await runtime.answer(
        SCOPE,
        task.task_id,
        command_id="answer-one",
        request_id="color",
        answers=(
            TaskAnswer(question="Which color?", selected_options=("Blue",)),
        ),
    )
    done = await status(harness, task.task_id, "succeeded")
    assert done.result_data == {"answer": "Blue"}
    assert len(done.output_refs) == 1
    assert len(calls) == 2
    assert len((await harness.artifacts.list(SCOPE)).items) == 1
    ref = done.output_refs[0]
    # No originating session is needed to reuse an artifact within
    # user/workspace/App.
    assert (await harness.artifacts.read(SCOPE, ref.artifact_id, ref.version))[
        1
    ] == b"reusable"
    other_origin = ORIGIN.model_copy(
        update={"origin_ref": "second", "return_session_ref": "chat-two"},
    )
    assert (
        await dispatch(runtime, "two", other_origin)
    ).task_id != done.task_id
    for update in [
        {"principal_id": "bob"},
        {"workspace_id": "other"},
        {"app_id": "other-app"},
    ]:
        with pytest.raises(TaskStoreError):
            await harness.artifacts.read(
                SCOPE.model_copy(update=update),
                ref.artifact_id,
                ref.version,
            )
    # The command receipt survives completion and reconnect.
    receipt = await runtime.answer(
        SCOPE,
        task.task_id,
        command_id="answer-one",
        request_id="color",
        answers=(
            TaskAnswer(question="Which color?", selected_options=("Blue",)),
        ),
    )
    assert receipt.state == "accepted"


async def test_default_recovery_interrupts_unknown_effects(harness):
    calls = []

    async def handler(ctx):
        calls.append(ctx.submission_id)
        await ctx.request_input(QUESTION)

    runtime = await harness.start(handler)
    task = await dispatch(runtime)
    await status(harness, task.task_id, "waiting_for_input")
    await runtime.aclose()
    await harness.start(handler)
    await status(harness, task.task_id, "interrupted")
    assert len(calls) == 1


async def test_cancel_is_durable_and_result_schema_is_enforced(harness):
    async def waiting(ctx):
        await ctx.request_input(QUESTION)

    runtime = await harness.start(waiting)
    task = await dispatch(runtime)
    await status(harness, task.task_id, "waiting_for_input")
    await runtime.cancel(SCOPE, task.task_id)
    await status(harness, task.task_id, "cancelled")
    await runtime.aclose()

    async def invalid(_ctx):
        return ActionResult("Wrong shape", {"answer": 42})

    runtime = await harness.start(invalid)
    task = await dispatch(runtime, "invalid")
    await status(harness, task.task_id, "failed")


def test_additive_models_preserve_old_grant_and_event_digests():
    old = ACTION.model_dump(mode="json", exclude={"guidance", "result_schema"})
    descriptor = ActionDescriptor.model_validate(old)
    assert descriptor.descriptor_digest == content_digest(old)
    assert (
        descriptor.model_copy(
            update={"guidance": "Explain choices"},
        ).descriptor_digest
        == descriptor.descriptor_digest
    )
    fields = {
        "run_ref": ExecutorRunRef(executor_id="x", session_id="s", run_id="r"),
        "sequence": 0,
        "cursor": "0",
        "status": "waiting_for_input",
    }
    legacy = ExecutorEvent(
        **fields,
        detail={"input_request": QUESTION.model_dump(mode="json")},
    )
    typed = ExecutorEvent(**fields, input_request=QUESTION)
    assert legacy.replay_digest == typed.replay_digest
    assert legacy.replay_digest == content_digest(
        legacy.model_dump(
            mode="json",
            exclude={
                "project_ref",
                "artifact_ref",
                "input_request",
                "approval_request",
                "experience_update",
                "result_data",
            },
        ),
    )
    with pytest.raises(ValueError):
        ExecutorEvent(
            **fields,
            input_request=QUESTION,
            detail={"input_request": {}},
        )


async def test_delegated_catalog_omits_direct_only_actions(harness):
    direct = ACTION.model_copy(update={"engagements": ("direct",)})
    harness.policy.write_text(
        TaskPolicy(
            grants=(
                TaskGrant(
                    scope=SCOPE,
                    action_id=direct.action_id,
                    descriptor_digest=direct.descriptor_digest,
                ),
            ),
        ).model_dump_json(),
    )
    runtime = await harness.start(AsyncMock(), action=direct)
    assert len(await runtime.catalog("alice", "sales")) == 1
    assert (
        await runtime.catalog("alice", "sales", engagement="delegated") == []
    )


async def test_simple_handler_projects_generic_experience_and_project(harness):
    experience = TaskExperienceDefinition(
        action_id=ACTION.action_id,
        title={"default": "Inspection"},
        steps=({"id": "inspect", "label": {"default": "Inspect"}},),
    )
    project = ProjectRef(
        app_id=SCOPE.app_id,
        project_id="project-one",
        kind="inspection",
        revision=1,
    )

    async def handler(ctx):
        await ctx.report(
            "inspected",
            experience={
                "step_states": [{"step_id": "inspect", "status": "complete"}],
            },
            project=project,
        )
        return ActionResult("Inspected", {"answer": "Ready"}, project)

    runtime = await harness.start(handler, experience=experience)
    task = await dispatch(runtime)
    done = await status(harness, task.task_id, "succeeded")
    assert done.project_ref == project
    assert done.experience.step_states[0].status == "complete"
