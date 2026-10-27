# -*- coding: utf-8 -*-
"""Approval is a scoped user decision, not an agent-generated answer."""
# pylint: disable=redefined-outer-name,protected-access
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
    from qwenpaw.pawapp.tasks.approvals import validate_decision

    with pytest.raises(TaskStoreError, match="approval_expired"):
        validate_decision(expired, decision(expired))

    async def handler(ctx):
        try:
            await ctx.request_approval(expired)
        except TaskStoreError as exc:
            return ActionResult("Expired", {"answer": exc.code})
        raise AssertionError("expired approval returned a decision")

    runtime = await harness.start(handler)
    task = await dispatch(runtime)
    result = await status(harness, task.task_id, "succeeded")
    assert result.result_data == {"answer": "approval_expired"}


async def test_revoked_grant_still_allows_scoped_cancel(harness):
    runtime, task, executed = await waiting(harness)
    harness.policy.unlink()
    control = await runtime.get(SCOPE, task.task_id)
    assert control.handle.task_id == task.task_id
    assert control.handle.status == "waiting_for_approval"
    assert control.handle.approval_request is None
    assert control.handle.recovery_reason == "action_forbidden"
    with pytest.raises(TaskStoreError, match="action_forbidden"):
        await runtime.decide(
            SCOPE,
            task.task_id,
            command_id="blocked",
            decision=decision(),
        )
    with pytest.raises(TaskStoreError, match="task_not_found"):
        await runtime.cancel(
            SCOPE.model_copy(update={"principal_id": "bob"}),
            task.task_id,
        )
    command = await asyncio.wait_for(runtime.cancel(SCOPE, task.task_id), 3)
    assert command.state == "accepted"
    await status(harness, task.task_id, "cancelled")
    assert not executed


async def test_cancel_with_changed_descriptor_preserves_unknown_intent(
    harness,
):
    from unittest.mock import AsyncMock
    from qwenpaw.pawapp.tasks import ActionRegistration
    from tests.unit.pawapp.test_managed_actions import ACTION

    runtime, task, _ = await waiting(harness)
    changed = ACTION.model_copy(update={"summary": "Changed action"})
    registration = ActionRegistration(action=changed, handler=AsyncMock())
    runtime._registrations = lambda: {
        (SCOPE.app_id, changed.action_id): registration,
    }
    command = await runtime.cancel(SCOPE, task.task_id)
    assert command.state == "unknown"
    assert command.reason == "descriptor_changed"
    handle = (await harness.store.get(SCOPE, task.task_id)).handle
    assert handle.cancel_requested
    assert handle.status == "waiting_for_approval"


async def test_removed_action_is_deferred_and_cancel_remains_unconfirmed(
    harness,
):
    runtime, task, _ = await waiting(harness)
    runtime._registrations = lambda: {}
    await runtime._sync()
    await harness.store.reset_recovery_schedule()
    async with asyncio.timeout(3):
        while True:
            handle = (await harness.store.get(SCOPE, task.task_id)).handle
            scheduled = await harness.store.recoverable()
            if handle.recovery_reason == "action_not_found" and all(
                item.handle.task_id != task.task_id for item in scheduled
            ):
                break
            await asyncio.sleep(0.01)
    assert task.task_id not in [
        item.handle.task_id for item in await harness.store.recoverable()
    ]
    command = await runtime.cancel(SCOPE, task.task_id)
    assert command.state == "unknown"
    assert command.reason == "action_not_found"
    assert (
        await harness.store.get(SCOPE, task.task_id)
    ).handle.cancel_requested


async def test_expiry_wakes_handler_without_authorizing(harness):
    proposal = PROPOSAL.model_copy(update={"expires_at": time.time() + 0.5})
    outcomes = []

    async def handler(ctx):
        try:
            await ctx.request_approval(proposal)
        except TaskStoreError as exc:
            outcomes.append(exc.code)
            return ActionResult("Approval expired", {"answer": exc.code})
        raise AssertionError("expired proposal was approved")

    runtime = await harness.start(handler, recovery="replay_safe")
    task = await dispatch(runtime)
    await status(harness, task.task_id, "waiting_for_approval")
    result = await status(harness, task.task_id, "succeeded")
    assert result.result_data == {"answer": "approval_expired"}
    assert outcomes == ["approval_expired"]


async def test_expiry_is_observed_after_host_restart(harness):
    proposal = PROPOSAL.model_copy(update={"expires_at": time.time() + 0.6})
    outcomes = []

    async def handler(ctx):
        try:
            await ctx.request_approval(proposal)
        except TaskStoreError as exc:
            outcomes.append(exc.code)
            return ActionResult("Approval expired", {"answer": exc.code})
        raise AssertionError("expired proposal was approved")

    runtime = await harness.start(handler, recovery="replay_safe")
    task = await dispatch(runtime)
    await status(harness, task.task_id, "waiting_for_approval")
    await runtime.aclose()
    await asyncio.sleep(0.7)
    await harness.start(handler, recovery="replay_safe")
    result = await status(harness, task.task_id, "succeeded")
    assert result.result_data == {"answer": "approval_expired"}
    assert outcomes == ["approval_expired"]


async def test_progress_only_event_does_not_stale_managed_approval(harness):
    from qwenpaw.pawapp.tasks import ApprovalProgress

    runtime, task, executed = await waiting(harness)
    submission = await harness.store.get(SCOPE, task.task_id)
    adapter = runtime._binding(SCOPE, task.action_id).adapter
    event = await adapter.emit(
        submission,
        "progress-only",
        approval_progress=ApprovalProgress(completed=1, pending=1),
    )
    await harness.store.apply_event(SCOPE, task.task_id, event)
    command = await runtime.decide(
        SCOPE,
        task.task_id,
        command_id="progress-decision",
        decision=decision(),
    )
    assert command.state == "accepted"
    await status(harness, task.task_id, "succeeded")
    assert executed == [PROPOSAL.subject_digest]


async def test_blocked_recovery_is_deferred_without_terminal_state(harness):
    runtime, task, _ = await waiting(harness)
    await harness.store.mark_recovery(
        SCOPE,
        task.task_id,
        state="unresolved",
        reason="descriptor_changed",
    )
    await harness.store.defer_recovery(task.task_id, 60)
    assert task.task_id not in [
        item.handle.task_id for item in await harness.store.recoverable()
    ]
    handle = (await harness.store.get(SCOPE, task.task_id)).handle
    assert handle.status == "waiting_for_approval"
    assert handle.recovery_reason == "descriptor_changed"
    # An explicit user action bypasses the background scan delay.
    command = await runtime.cancel(SCOPE, task.task_id)
    assert command.state == "accepted"
    await status(harness, task.task_id, "cancelled")


async def test_approval_wait_does_not_reemit_journal_events(
    harness,
    monkeypatch,
):
    runtime, task, _ = await waiting(harness)
    adapter = runtime._binding(SCOPE, task.action_id).adapter
    emitted = []
    original = adapter.emit

    async def record_emit(*args, **kwargs):
        emitted.append(args[1])
        return await original(*args, **kwargs)

    monkeypatch.setattr(adapter, "emit", record_emit)
    await asyncio.sleep(0.35)
    assert not emitted
    await runtime.cancel(SCOPE, task.task_id)


async def test_cancel_recovery_takes_priority_over_old_decision(harness):
    runtime, task, executed = await waiting(harness)
    await prepare_decision(
        harness.store,
        SCOPE,
        task.task_id,
        command_id="old-decision",
        decision=decision(),
    )
    cancel = await harness.store.prepare_cancel(
        SCOPE,
        task.task_id,
        reason="cancel before delivery",
    )
    await runtime._drive(SCOPE, task.task_id)
    result = await harness.store.command(
        SCOPE,
        task.task_id,
        cancel.command_id,
    )
    assert result.state == "accepted"
    await status(harness, task.task_id, "cancelled")
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


async def test_app_only_review_cannot_be_decided_through_host(harness):
    from qwenpaw.pawapp.tasks import ApprovalInspection

    proposal = PROPOSAL.model_copy(
        update={
            "decision_surface": "app",
            "inspection": ApprovalInspection(
                target_id="review-1",
                label="Inspect changes",
            ),
        },
    )
    runtime, task, executed = await waiting(harness, proposal)
    with pytest.raises(TaskStoreError, match="approval_requires_app"):
        await runtime.decide(
            SCOPE,
            task.task_id,
            command_id="blind-approval",
            decision=decision(proposal),
        )
    assert not executed


async def test_progress_update_does_not_replace_approval_or_receipt(harness):
    from qwenpaw.pawapp.tasks import ApprovalProgress

    _runtime, task, _executed = await waiting(harness)
    await prepare_decision(
        harness.store,
        SCOPE,
        task.task_id,
        command_id="pending",
        decision=decision(),
    )
    before = (await harness.store.get(SCOPE, task.task_id)).handle
    updated = await harness.store.apply_event(
        SCOPE,
        task.task_id,
        ExecutorEvent(
            run_ref=before.executor_run_ref,
            sequence=before.executor_sequence + 1,
            cursor="progress-only",
            approval_progress=ApprovalProgress(
                completed=2,
                pending=3,
                future=4,
                forecast="estimated",
            ),
        ),
    )
    assert updated.handle.approval_request == before.approval_request
    assert updated.handle.approval_receipt == before.approval_receipt
    assert updated.handle.approval_progress.pending == 3


def test_progress_forecast_and_legacy_proposal_wire():
    from qwenpaw.pawapp.tasks import ApprovalProgress

    for fields in ({"future": 3}, {"forecast": "exact"}, {"completed": -1}):
        with pytest.raises(ValidationError):
            ApprovalProgress.model_validate(
                {"completed": 0, "pending": 1, **fields},
            )
    wire = PROPOSAL.model_dump(mode="json")
    assert "subject" not in wire
    assert "inspection" not in wire
    assert "decision_surface" not in wire
    assert ApprovalRequest.model_validate(wire).model_dump(mode="json") == wire


async def test_runtime_inspection_rejects_stale_proposal(harness, tmp_path):
    from types import SimpleNamespace
    from qwenpaw.pawapp.tasks import ApprovalInspection, ProjectRef
    from qwenpaw.pawapp.handoffs import HandoffStore

    proposal = PROPOSAL.model_copy(
        update={
            "inspection": ApprovalInspection(
                target_id="review-7",
                label="Inspect changes",
            ),
        },
    )
    runtime, task, _executed = await waiting(harness, proposal)
    current = (await harness.store.get(SCOPE, task.task_id)).handle
    await harness.store.apply_event(
        SCOPE,
        task.task_id,
        ExecutorEvent(
            run_ref=current.executor_run_ref,
            sequence=current.executor_sequence + 1,
            cursor="project-ref",
            project_ref=ProjectRef(
                app_id=SCOPE.app_id,
                project_id="report",
                kind="report",
                revision=7,
            ),
        ),
    )
    runtime.handoffs = await HandoffStore.open(
        tmp_path / "handoffs.db",
        harness.artifacts,
    )
    reference = SimpleNamespace(
        request_id=proposal.request_id,
        subject_digest=proposal.subject_digest,
    )
    opened = await runtime.open_app(SCOPE, task.task_id, approval=reference)
    ordinary = await runtime.open_app(SCOPE, task.task_id)
    assert ordinary == opened
    resolved = await runtime.resolve_handoff(SCOPE, opened.handoff_id)
    assert resolved.context.approval_request == proposal
    reference.subject_digest = "sha256:" + "b" * 64
    with pytest.raises(TaskStoreError, match="stale_approval"):
        await runtime.open_app(SCOPE, task.task_id, approval=reference)
