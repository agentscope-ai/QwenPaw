# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from services.runtime_files import (
    IdempotencyConflictError,
    IdempotencyRecordStore,
    IdempotencyStateConflictError,
    IdempotencyStatus,
)


pytestmark = pytest.mark.unit


def test_concurrent_reserve_has_exactly_one_creator_and_replays_completion(
    tmp_path,
):
    root = tmp_path / "runtime" / "commands" / "idempotency"
    request_hash = IdempotencyRecordStore.request_hash({"value": 1})

    def reserve():
        return IdempotencyRecordStore(root).reserve(
            owner_id="project-1",
            scope="POST /commands",
            idempotency_key="client-command-1",
            request_hash=request_hash,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        reservations = list(executor.map(lambda _index: reserve(), range(8)))

    assert sum(reservation.created for reservation in reservations) == 1
    assert (
        len({reservation.record.record_id for reservation in reservations})
        == 1
    )

    store = IdempotencyRecordStore(root)
    completed = store.complete(
        owner_id="project-1",
        scope="POST /commands",
        idempotency_key="client-command-1",
        request_hash=request_hash,
        response={"body": {"ok": True}},
        response_status=202,
    )
    replay = reserve()
    assert completed.status is IdempotencyStatus.COMPLETED
    assert replay.created is False
    assert replay.record.response == {"body": {"ok": True}}
    assert replay.record.response_status == 202


def test_idempotency_payload_drift_and_terminal_state_drift_are_conflicts(
    tmp_path,
):
    store = IdempotencyRecordStore(tmp_path / "idempotency")
    store.reserve(
        owner_id="project-1",
        scope="POST /messages",
        idempotency_key="message-1",
        request_hash="hash-a",
    )
    with pytest.raises(IdempotencyConflictError):
        store.reserve(
            owner_id="project-1",
            scope="POST /messages",
            idempotency_key="message-1",
            request_hash="hash-b",
        )

    store.fail(
        owner_id="project-1",
        scope="POST /messages",
        idempotency_key="message-1",
        request_hash="hash-a",
        error={"code": "FAILED"},
        response_status=500,
    )
    with pytest.raises(IdempotencyStateConflictError):
        store.complete(
            owner_id="project-1",
            scope="POST /messages",
            idempotency_key="message-1",
            request_hash="hash-a",
            response={"ok": True},
        )


def test_fail_if_in_progress_makes_failure_replayable_and_preserves_terminal_state(
    tmp_path,
) -> None:
    store = IdempotencyRecordStore(tmp_path / "idempotency")
    request_hash = store.request_hash({"value": 1})
    store.reserve(
        owner_id="project-1",
        scope="PATCH /project",
        idempotency_key="command-1",
        request_hash=request_hash,
    )

    failed = store.fail_if_in_progress(
        owner_id="project-1",
        scope="PATCH /project",
        idempotency_key="command-1",
        request_hash=request_hash,
        error={"code": "CAS_CONFLICT"},
        response_status=409,
    )
    repeated = store.fail_if_in_progress(
        owner_id="project-1",
        scope="PATCH /project",
        idempotency_key="command-1",
        request_hash=request_hash,
        error={"code": "DIFFERENT"},
        response_status=500,
    )

    assert failed.status is IdempotencyStatus.FAILED
    assert repeated == failed
    assert repeated.error == {"code": "CAS_CONFLICT"}
    assert repeated.response_status == 409
