# -*- coding: utf-8 -*-
"""Durable, scoped user decisions. Ordinary agent answers cannot authorize."""

import time

from .contracts import (
    ApprovalActor,
    ApprovalReceipt,
    ApprovalDecision,
    TaskCommand,
    TaskStoreError,
    content_digest,
)

# This module shares TaskStore's transactional implementation boundary.
# pylint: disable=protected-access


def validate_decision(request, decision):
    """Validate the immutable proposal, choice and deadline at delivery too."""
    if request is None or (
        request.request_id != decision.request_id
        or request.subject_digest != decision.subject_digest
    ):
        raise TaskStoreError("stale_approval")
    if request.expires_at is not None and request.expires_at <= time.time():
        raise TaskStoreError("approval_expired")
    choice = next(
        (c for c in request.choices if c.decision_id == decision.decision_id),
        None,
    )
    if choice is None or (
        choice.requires_comment and not (decision.comment or "").strip()
    ):
        raise TaskStoreError("invalid_approval_decision")


def record_receipt(store, connection, submission, command):
    """Publish decision delivery facts without claiming App progress."""
    proposal = submission.handle.approval_request
    if (
        command.kind != "decide"
        or proposal is None
        or proposal.request_id != command.request_id
    ):
        return
    receipt = ApprovalReceipt(
        command_id=command.command_id,
        decision=command.payload["decision"],
        actor=command.payload["actor"],
        state=command.state,
        reason=command.reason,
    )
    handle = submission.handle.model_copy(update={"approval_receipt": receipt})
    store._event(
        connection,
        submission.model_copy(update={"handle": handle}),
        "command",
        {"kind": "decide", "receipt": receipt.model_dump(mode="json")},
    )


async def prepare_decision(store, scope, task_id, *, command_id, decision):
    decision = ApprovalDecision.model_validate(decision)
    payload = {
        "decision": decision.model_dump(mode="json"),
        "actor": ApprovalActor(principal_id=scope.principal_id).model_dump(
            mode="json",
        ),
    }
    meaning = content_digest(
        {
            "kind": "decide",
            "request_id": decision.request_id,
            "payload": payload,
        },
    )

    def operation(connection):
        submission = store._get(connection, scope, task_id)
        existing = store._command(connection, task_id, command_id)
        if existing is not None:
            if existing[1] != meaning:
                raise TaskStoreError("command_conflict")
            return existing[0]
        handle = submission.handle
        if handle.status != "waiting_for_approval" or handle.cancel_requested:
            raise TaskStoreError("stale_approval")
        validate_decision(handle.approval_request, decision)
        # One decision per proposal, including concurrent clicks in two tabs.
        for row in connection.execute(
            "SELECT command_json FROM task_commands WHERE task_id=?",
            (task_id,),
        ).fetchall():
            prior = TaskCommand.model_validate_json(row[0])
            if (
                prior.kind == "decide"
                and prior.request_id == decision.request_id
            ):
                raise TaskStoreError("approval_already_decided")
        now = time.time()
        command = TaskCommand(
            task_id=task_id,
            command_id=command_id,
            kind="decide",
            request_id=decision.request_id,
            payload=payload,
            created_at=now,
            updated_at=now,
        )
        connection.execute(
            "INSERT INTO task_commands VALUES (?, ?, ?, ?)",
            (task_id, command_id, meaning, command.model_dump_json()),
        )
        record_receipt(store, connection, submission, command)
        return command

    return await store._run(operation, write=True)


def validate_request_identity(connection, task_id, proposal):
    """An App cannot recycle a request ID for a different proposal later."""
    from .contracts import ApprovalRequest

    row = connection.execute(
        """SELECT json_extract(event_json, '$.payload.detail.approval_request')
        FROM task_events WHERE task_id=? AND
        json_extract(event_json,
          '$.payload.detail.approval_request.request_id')=?
        LIMIT 1""",
        (task_id, proposal.request_id),
    ).fetchone()
    if (
        row is not None
        and ApprovalRequest.model_validate_json(row[0]) != proposal
    ):
        raise TaskStoreError("approval_request_conflict")
