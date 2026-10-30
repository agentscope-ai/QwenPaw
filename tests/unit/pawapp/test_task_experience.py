# -*- coding: utf-8 -*-
"""App-owned task presentation remains bounded and durable."""

import pytest

from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    ExecutorEvent,
    ExecutorRunRef,
    LocalizedText,
    TaskExperienceContextItem,
    TaskExperienceDefinition,
    TaskExperienceStepDefinition,
    TaskExperienceStepState,
    TaskExperienceUpdate,
    TaskExperienceViewDefinition,
    TaskOrigin,
    TaskScope,
    TaskStore,
    TaskStoreError,
)
from qwenpaw.pawapp.tasks.binding import ActionRegistration


def definition(title="Data analysis"):
    return TaskExperienceDefinition(
        action_id="analyze",
        title=LocalizedText(default=title),
        steps=(
            TaskExperienceStepDefinition(
                id="read",
                label=LocalizedText(default="Read data"),
            ),
            TaskExperienceStepDefinition(
                id="report",
                label=LocalizedText(default="Publish report"),
            ),
        ),
        views=(
            TaskExperienceViewDefinition(
                id="summary",
                label=LocalizedText(default="Summary"),
                open_label=LocalizedText(default="Open analysis"),
            ),
        ),
        default_view_id="summary",
    )


def action():
    return ActionDescriptor(
        app_id="qwenpaw-data",
        action_id="analyze",
        summary="Analyze data",
        engagements=("delegated",),
        input_schema={"type": "object", "additionalProperties": False},
        output_types=("qwenpaw:file",),
        adapter_ref="test",
    )


class _Adapter:
    submission_protocol_version = 1


def test_display_copy_is_not_part_of_the_action_grant_digest():
    descriptor = action()
    first = ActionRegistration(
        action=descriptor,
        factory=_Adapter,
        settings_entry="/apps/qwenpaw-data",
        experience=definition("Data analysis"),
    )
    second = ActionRegistration(
        action=descriptor,
        factory=_Adapter,
        settings_entry="/apps/qwenpaw-data",
        experience=definition("Analyze business data"),
    )

    assert first.action.descriptor_digest == second.action.descriptor_digest
    assert (
        first.experience.definition_digest
        != second.experience.definition_digest
    )


@pytest.mark.asyncio
async def test_experience_projection_is_validated_and_persisted(tmp_path):
    store = await TaskStore.open(tmp_path / "tasks.sqlite3")
    scope = TaskScope(
        principal_id="alice",
        workspace_id="sales",
        app_id="qwenpaw-data",
    )
    submission = await store.create(
        scope,
        action(),
        request_id="request-1",
        inputs={},
        origin=TaskOrigin(
            engagement="delegated",
            origin_ref="chat-1",
            return_session_ref="chat-1",
        ),
        experience=definition(),
    )
    assert submission.handle.experience is not None
    assert [
        state.status for state in submission.handle.experience.step_states
    ] == [
        "pending",
        "pending",
    ]
    assert submission.handle.experience.view_id == "summary"

    await store.begin_submission(scope, submission.handle.task_id)
    run = ExecutorRunRef(
        executor_id="data:test",
        session_id="session-1",
        run_id="run-1",
    )
    submission = await store.record_accepted(
        scope,
        submission.handle.task_id,
        run,
    )
    update = TaskExperienceUpdate(
        step_states=(
            TaskExperienceStepState(step_id="read", status="complete"),
            TaskExperienceStepState(step_id="report", status="running"),
        ),
        active_step_id="report",
        context_items=(
            TaskExperienceContextItem(
                id="datasource",
                label=LocalizedText(default="Data source"),
                value="sales",
            ),
        ),
        view_id="summary",
    )
    submission = await store.apply_event(
        scope,
        submission.handle.task_id,
        ExecutorEvent(
            run_ref=run,
            sequence=0,
            cursor="0",
            status="running",
            detail={"experience_update": update.model_dump(mode="json")},
        ),
    )
    assert submission.handle.experience is not None
    assert submission.handle.experience.active_step_id == "report"
    assert submission.handle.experience.context_items[0].value == "sales"

    reopened = await TaskStore.open(store.path)
    persisted = await reopened.get(scope, submission.handle.task_id)
    assert persisted.handle.experience == submission.handle.experience

    with pytest.raises(TaskStoreError, match="invalid_experience_update"):
        await store.apply_event(
            scope,
            submission.handle.task_id,
            ExecutorEvent(
                run_ref=run,
                sequence=1,
                cursor="1",
                detail={
                    "experience_update": {
                        "step_states": [
                            {"step_id": "undeclared", "status": "running"},
                        ],
                    },
                },
            ),
        )
