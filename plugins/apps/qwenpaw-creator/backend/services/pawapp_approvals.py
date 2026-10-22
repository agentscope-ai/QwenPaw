# -*- coding: utf-8 -*-
"""Creator decisions mapped onto the Host approval contract."""

import asyncio

from pydantic import BaseModel

from services.file_agent_runtime import notify_creator_agent_runtime
from services.project_files.review import (
    ReviewDecisionConflict,
    ReviewDecisionItem,
    ReviewRejectionAction,
    ReviewRejectionFeedback,
)
from services.project_files.review_bookkeeping import is_human_review_change
from services.runtime_files.models import ReviewOperationDecision

from qwenpaw.pawapp.tasks import (
    ApprovalChoice,
    ApprovalCost,
    ApprovalDecision,
    ApprovalRequest,
    CommandLookup,
    TaskStoreError,
)
from qwenpaw.pawapp.tasks.contracts import content_digest


class ReviewCommandReceipt(BaseModel):
    meaning: str
    result: CommandLookup


def generation_request(workflow, authorization, *, request_id, summary):
    # Exclude mutable decision bookkeeping; never expose the secret token,
    # raw prompt or source paths in the public card.
    subject = authorization.model_dump(
        mode="json",
        exclude={
            "status",
            "decision",
            "updated_at",
            "decided_at",
            "estimated_cost",
        },
    )
    return ApprovalRequest(
        request_id=request_id,
        kind="execution",
        subject_digest="sha256:"
        + content_digest(
            {
                "submission_id": workflow.submission_id,
                "authorization": subject,
            },
        ),
        title="Creator generation approval",
        summary=summary,
        effects=(
            "Generate media using the configured provider. "
            "Provider charges may apply.",
        ),
        choices=(
            ApprovalChoice(decision_id="approve_once", label="Approve once"),
            ApprovalChoice(decision_id="reject", label="Do not run"),
        ),
        cost=ApprovalCost(
            description="The provider cost is not available before execution.",
        ),
        expires_at=authorization.expires_at.timestamp()
        if authorization.expires_at
        else None,
    )


def review_operations(review):
    return [
        operation
        for operation in review.operations
        if operation.decision == ReviewOperationDecision.PENDING
        and is_human_review_change(operation)
    ]


def review_request(workflow, review):
    digest = content_digest(
        {
            "submission_id": workflow.submission_id,
            "review": review.model_dump(mode="json"),
        },
    )
    operations = review_operations(review)
    return ApprovalRequest(
        request_id="creator-review-" + digest[:32],
        kind="review",
        subject_digest="sha256:" + digest,
        title="Review Creator changes",
        summary=(
            f"Review {len(operations)} proposed content changes at revision "
            f"{review.candidate_generation}. "
            "Open the project to inspect the content. "
            "Your decision applies to all changes in this review; "
            "use Creator for individual decisions."
        ),
        effects=(
            "Accept the proposed changes and continue production, "
            "or undo them.",
        ),
        choices=(
            ApprovalChoice(decision_id="approve_once", label="Accept changes"),
            ApprovalChoice(decision_id="reject", label="Undo changes"),
            ApprovalChoice(
                decision_id="request_changes",
                label="Request changes",
                requires_comment=True,
            ),
        ),
    )


async def decide_review(services, workflow, event, command):
    """Replay the same Creator journal after an uncertain Host response."""
    review = event.review_snapshot
    decision = ApprovalDecision.model_validate(command.payload["decision"])
    proposal = review_request(workflow, review)
    if (
        decision.request_id != proposal.request_id
        or decision.subject_digest != proposal.subject_digest
    ):
        return CommandLookup(state="rejected", reason="stale_approval")
    if (
        decision.decision_id == "request_changes"
        and not (decision.comment or "").strip()
    ):
        return CommandLookup(
            state="rejected",
            reason="invalid_approval_decision",
        )
    feedback = None
    if decision.decision_id != "approve_once":
        feedback = ReviewRejectionFeedback(
            action=(
                ReviewRejectionAction.UNDO_AND_REGENERATE
                if decision.decision_id == "request_changes"
                else ReviewRejectionAction.UNDO_ONLY
            ),
            feedback_note=decision.comment,
        )
    decision_id = "pawapp-" + content_digest(
        {"task": command.task_id, "command": command.command_id},
    )
    try:
        await services.decide_review(
            project_id=workflow.project_id,
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[
                ReviewDecisionItem(
                    operation_id=operation.operation_id,
                    decision="ACCEPT"
                    if decision.decision_id == "approve_once"
                    else "REJECT",
                )
                for operation in review_operations(review)
            ],
            rejection_feedback=feedback,
            decision_id=decision_id,
        )
        await services.publish_review_followup(
            project_id=workflow.project_id,
            review_id=review.review_id,
            decision_id=decision_id,
        )
    except ReviewDecisionConflict:
        return CommandLookup(state="rejected", reason="stale_approval")
    notify_creator_agent_runtime(workflow.project_id)
    return CommandLookup(state="accepted")


async def review_command(services, workflow, command):
    """Select only a review previously offered by this delegated workflow."""
    prior = await query_review_command(services, workflow, command)
    if prior.state != "not_found":
        return prior
    for event in reversed(workflow.events):
        if (
            event.review_snapshot is not None
            and event.approval_request is not None
            and event.approval_request.request_id == command.request_id
        ):
            result = await decide_review(services, workflow, event, command)
            await asyncio.to_thread(
                _receipt_store(services, workflow, command).try_create,
                ReviewCommandReceipt(meaning=_meaning(command), result=result),
            )
            return result
    return CommandLookup(state="rejected", reason="stale_approval")


def _receipt_store(services, workflow, command):
    from services.runtime_files.atomic_store import AtomicJsonRecordStore

    key = content_digest(
        {"task": command.task_id, "command": command.command_id},
    )
    return AtomicJsonRecordStore(
        services.projects.project_root(workflow.project_id)
        / "runtime"
        / "pawapp-decisions"
        / (key + ".json"),
        ReviewCommandReceipt,
    )


def _meaning(command):
    return content_digest(
        {"request_id": command.request_id, "payload": command.payload},
    )


async def query_review_command(services, workflow, command):
    receipt = await asyncio.to_thread(
        _receipt_store(services, workflow, command).read_or_none,
    )
    if receipt is None:
        return CommandLookup(state="not_found")
    if receipt.meaning != _meaning(command):
        return CommandLookup(state="rejected", reason="command_conflict")
    return receipt.result


def validate_generation_command(workflow, command):
    """Return the expected subject; labels are only for legacy receipts."""
    if command.kind != "decide":
        return None
    decision = ApprovalDecision.model_validate(command.payload["decision"])
    offered = next(
        (
            event.approval_request
            for event in workflow.events
            if event.approval_request is not None
            and event.approval_request.request_id == command.request_id
        ),
        None,
    )
    if offered is None or offered.subject_digest != decision.subject_digest:
        raise TaskStoreError("stale_approval")
    return decision.subject_digest
