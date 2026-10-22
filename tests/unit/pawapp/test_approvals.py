# -*- coding: utf-8 -*-
"""Approval is a scoped user decision, not an agent-generated answer."""
# pylint: disable=redefined-outer-name
import asyncio
import time

import pytest
from pydantic import ValidationError

from qwenpaw.pawapp.tasks import (
    ActionResult,
    ApprovalChoice,
    ApprovalDecision,
    ApprovalRequest,
    ExecutorEvent,
    TaskStoreError,
)
from qwenpaw.pawapp.tasks.approvals import prepare_decision
from tests.unit.pawapp.test_managed_actions import (
    SCOPE,
    dispatch,
    harness as managed_harness,
    status,
)

harness = managed_harness

PROPOSAL = ApprovalRequest(
    request_id="generate-1",
    kind="execution",
    subject_digest="sha256:" + "a" * 64,
    title="Generate a report",
    summary="Run this operation once.",
    choices=(
        ApprovalChoice(decision_id="approve_once", label="允许一次"),
        ApprovalChoice(decision_id="reject", label="拒绝"),
    ),
)


def decision(proposal=PROPOSAL, choice="approve_once"):
    return ApprovalDecision(
        request_id=proposal.request_id,
        subject_digest=proposal.subject_digest,
        decision_id=choice,
    )


async def waiting(harness, proposal=PROPOSAL):
    executed = []

    async def handler(ctx):
        answer = await ctx.request_approval(proposal)
        if answer.decision_id == "approve_once":
            executed.append(answer.subject_digest)
        return ActionResult(
            summary="Handled",
            data={"answer": answer.decision_id},
        )

    runtime = await harness.start(handler, recovery="replay_safe")
    task = await dispatch(runtime)
    await status(harness, task.task_id, "waiting_for_approval")
    return runtime, task, executed


@pytest.mark.parametrize("choice", ["approve_once", "reject"])
async def test_managed_user_decision_resumes_same_task_once(harness, choice):
    runtime, task, executed = await waiting(harness)
    assert not executed
    with pytest.raises(TaskStoreError, match="human_approval_required"):
        await runtime.answer(
            SCOPE,
            task.task_id,
            command_id="agent",
            request_id=PROPOSAL.request_id,
            answers=[],
        )
    command = await runtime.decide(
        SCOPE,
        task.task_id,
        command_id="user",
        decision=decision(choice=choice),
    )
    assert command.state == "accepted"
    assert command.payload["actor"] == {
        "principal_id": "alice",
        "source": "user_interface",
    }
    finished = await status(harness, task.task_id, "succeeded")
    assert finished.approval_request is None
    replay = await runtime.decide(
        SCOPE,
        task.task_id,
        command_id="user",
        decision=decision(choice=choice),
    )
    assert replay.state == "accepted"
    assert executed == (
        [PROPOSAL.subject_digest] if choice == "approve_once" else []
    )


async def test_scope_expiry_and_changed_proposal_cannot_authorize(harness):
    runtime, task, executed = await waiting(harness)
    for field in ("principal_id", "workspace_id", "app_id"):
        with pytest.raises(TaskStoreError, match="task_not_found"):
            await prepare_decision(
                harness.store,
                SCOPE.model_copy(update={field: "other"}),
                task.task_id,
                command_id="bad",
                decision=decision(),
            )
    with pytest.raises(TaskStoreError, match="stale_approval"):
        await runtime.decide(
            SCOPE,
            task.task_id,
            command_id="stale",
            decision=decision().model_copy(
                update={"subject_digest": "sha256:" + "b" * 64},
            ),
        )
    assert not executed


async def test_expired_proposal_is_never_executed(harness):
    expired = PROPOSAL.model_copy(update={"expires_at": time.time() - 1})
    runtime, task, executed = await waiting(harness, expired)
    with pytest.raises(TaskStoreError, match="approval_expired"):
        await runtime.decide(
            SCOPE,
            task.task_id,
            command_id="late",
            decision=decision(expired),
        )
    assert not executed


async def test_two_surfaces_cannot_decide_the_same_proposal_differently(
    harness,
):
    _runtime, task, executed = await waiting(harness)
    results = await asyncio.gather(
        *[
            prepare_decision(
                harness.store,
                SCOPE,
                task.task_id,
                command_id=choice,
                decision=decision(choice=choice),
            )
            for choice in ("approve_once", "reject")
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(result, TaskStoreError) for result in results) == 1
    winner = next(
        result for result in results if not isinstance(result, Exception)
    )
    with pytest.raises(TaskStoreError, match="command_conflict"):
        await prepare_decision(
            harness.store,
            SCOPE,
            task.task_id,
            command_id=winner.command_id,
            decision=decision(
                choice="reject"
                if winner.command_id == "approve_once"
                else "approve_once",
            ),
        )
    assert not executed


async def test_replacement_invalidates_old_card_and_ordinary_answer(harness):
    _runtime, task, executed = await waiting(harness)
    current = (await harness.store.get(SCOPE, task.task_id)).handle
    replacement = PROPOSAL.model_copy(
        update={
            "request_id": "generate-2",
            "subject_digest": "sha256:" + "b" * 64,
        },
    )
    await harness.store.apply_event(
        SCOPE,
        task.task_id,
        ExecutorEvent(
            run_ref=current.executor_run_ref,
            sequence=current.executor_sequence + 1,
            cursor="replacement",
            status="waiting_for_approval",
            approval_request=replacement,
        ),
    )
    with pytest.raises(TaskStoreError, match="stale_approval"):
        await prepare_decision(
            harness.store,
            SCOPE,
            task.task_id,
            command_id="old",
            decision=decision(),
        )
    with pytest.raises(TaskStoreError):
        await harness.store.prepare_answer(
            SCOPE,
            task.task_id,
            command_id="answer",
            request_id=replacement.request_id,
            answers=[],
        )
    assert not executed


def test_contract_rejects_duplicate_choices_and_spoofed_actor():
    with pytest.raises(ValidationError):
        ApprovalRequest.model_validate(
            {**PROPOSAL.model_dump(), "choices": [PROPOSAL.choices[0]] * 2},
        )
    with pytest.raises(ValidationError):
        ApprovalDecision.model_validate(
            {**decision().model_dump(), "actor": {"principal_id": "admin"}},
        )


async def test_approval_survives_restart_without_repeating_effect(harness):
    calls = []
    effects = []

    async def handler(ctx):
        calls.append(ctx.submission_id)
        answer = await ctx.request_approval(PROPOSAL)
        if answer.decision_id == "approve_once":
            effects.append(ctx.submission_id)
        return ActionResult("Handled", {"answer": answer.decision_id})

    runtime = await harness.start(handler, "replay_safe")
    task = await dispatch(runtime)
    await status(harness, task.task_id, "waiting_for_approval")
    await runtime.aclose()
    runtime = await harness.start(handler, "replay_safe")
    command = await runtime.decide(
        SCOPE,
        task.task_id,
        command_id="restart-decision",
        decision=decision(),
    )
    assert command.state == "accepted"
    await status(harness, task.task_id, "succeeded")
    assert len(calls) == 2
    assert effects == [task.submission_id]
    assert (
        await runtime.decide(
            SCOPE,
            task.task_id,
            command_id="restart-decision",
            decision=decision(),
        )
    ).state == "accepted"
    assert len(effects) == 1


async def test_proposal_identity_is_immutable_after_replacement(harness):
    _runtime, task, _executed = await waiting(harness)
    handle = (await harness.store.get(SCOPE, task.task_id)).handle
    await harness.store.apply_event(
        SCOPE,
        task.task_id,
        ExecutorEvent(
            run_ref=handle.executor_run_ref,
            sequence=handle.executor_sequence + 1,
            cursor="next",
            status="waiting_for_approval",
            approval_request=PROPOSAL.model_copy(
                update={"request_id": "next"},
            ),
        ),
    )
    with pytest.raises(TaskStoreError, match="approval_request_conflict"):
        await harness.store.apply_event(
            SCOPE,
            task.task_id,
            ExecutorEvent(
                run_ref=handle.executor_run_ref,
                sequence=handle.executor_sequence + 2,
                cursor="recycled",
                status="waiting_for_approval",
                approval_request=PROPOSAL.model_copy(
                    update={"summary": "Different effects"},
                ),
            ),
        )
