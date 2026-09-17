# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from services.runtime_files import (
    ChangeOrigin,
    ChangeRoundRecord,
    ProjectChangeKind,
    ReviewBoundary,
    ReviewOperation,
    ReviewPolicy,
    ReviewRecord,
    ReviewStatus,
    RuntimeProjectState,
)


pytestmark = pytest.mark.unit


def boundary() -> ReviewBoundary:
    return ReviewBoundary(
        request_message_seq=2,
        request_id="request-2",
        interrupted_run_id="run-1",
        accepted_generation=3,
        accepted_etag="sha256:accepted",
        captured_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


def operation() -> ReviewOperation:
    return ReviewOperation(
        operation_id="operation-1",
        kind=ProjectChangeKind.UPDATE,
        json_pointer="/story/title",
        before_hash="sha256:before",
        after_hash="sha256:after",
        before="old",
        after="new",
    )


def test_only_review_capable_origins_can_require_review():
    for origin in (
        ChangeOrigin.AGENTDOCK_INTERRUPT,
        ChangeOrigin.AGENTDOCK_IDLE_GOAL,
        ChangeOrigin.RUNTIME_TASK,
    ):
        record = ChangeRoundRecord(
            round_id="round-1",
            project_id="project-1",
            origin=origin,
            review_policy=ReviewPolicy.REQUIRE_REVIEW,
            review_boundary=boundary(),
            caused_by_request_id="request-2",
            caused_by_message_seq=2,
        )
        assert record.review_boundary is not None

    with pytest.raises(ValidationError, match="only an AgentDock interrupt"):
        ChangeRoundRecord(
            round_id="round-2",
            project_id="project-1",
            origin=ChangeOrigin.INITIAL_CREATION,
            review_policy=ReviewPolicy.REQUIRE_REVIEW,
            review_boundary=boundary(),
        )
    with pytest.raises(ValidationError, match="cannot carry a ReviewBoundary"):
        ChangeRoundRecord(
            round_id="round-3",
            project_id="project-1",
            origin=ChangeOrigin.INITIAL_CREATION,
            review_policy=ReviewPolicy.AUTO_FIX,
            review_boundary=boundary(),
        )


def test_idle_goal_review_boundary_needs_no_interrupted_run():
    idle_boundary = boundary().model_copy(
        update={"interrupted_run_id": None},
    )
    record = ChangeRoundRecord(
        round_id="round-idle",
        project_id="project-1",
        origin=ChangeOrigin.AGENTDOCK_IDLE_GOAL,
        review_policy=ReviewPolicy.REQUIRE_REVIEW,
        review_boundary=idle_boundary,
        caused_by_request_id="request-2",
        caused_by_message_seq=2,
    )
    assert record.review_boundary is not None
    assert record.review_boundary.interrupted_run_id is None


def test_runtime_project_state_rejects_impossible_accepted_baseline():
    with pytest.raises(ValidationError, match="cannot exceed"):
        RuntimeProjectState(
            project_id="project-1",
            last_project_generation=3,
            last_project_etag="sha256:current",
            accepted_generation=4,
            accepted_etag="sha256:accepted",
        )


def test_pending_review_requires_a_real_pending_runtime_operation():
    review = ReviewRecord(
        review_id="review-1",
        round_id="round-1",
        request_id="request-2",
        request_message_seq=2,
        interrupted_run_id="run-1",
        baseline_generation=3,
        baseline_etag="sha256:accepted",
        candidate_generation=4,
        candidate_etag="sha256:candidate",
        decision_token="token-1",
        operations=[operation()],
    )
    assert review.status is ReviewStatus.PENDING

    accepted = operation().model_copy(update={"decision": "ACCEPTED"})
    with pytest.raises(ValidationError, match="pending operation"):
        ReviewRecord(
            review_id="review-2",
            round_id="round-1",
            request_id="request-2",
            request_message_seq=2,
            interrupted_run_id="run-1",
            baseline_generation=3,
            baseline_etag="sha256:accepted",
            candidate_generation=4,
            candidate_etag="sha256:candidate",
            decision_token="token-2",
            operations=[accepted],
        )

    # Transition code commonly uses model_copy.  Persistence validation must
    # still reject a copied model whose cross-field state was not resolved.
    invalid_copy = review.model_copy(update={"status": ReviewStatus.RESOLVED})
    with pytest.raises(ValidationError, match="cannot contain pending"):
        ReviewRecord.model_validate(invalid_copy)
