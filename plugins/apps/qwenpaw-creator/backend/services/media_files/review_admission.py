# -*- coding: utf-8 -*-
"""Deterministic media admission while generated artifacts await review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from domain.errors import ReviewPendingError
from services.project_files.models import ArtifactVersion
from services.runtime_files.models import ReviewRecord, ReviewStatus
from utils.logger import setup_logger


logger = setup_logger("services.media_files.review_admission")

_ARTIFACT_VERSION_POINTER_PREFIX = "/assets/artifact_versions_by_id/"


@dataclass(frozen=True, slots=True)
class PendingMediaArtifact:
    review_id: str
    version_id: str
    command_type: str
    target_ref: str
    variant_id: str | None


def _pending_media_artifacts(
    reviews: Sequence[ReviewRecord],
) -> tuple[PendingMediaArtifact, ...]:
    pending: list[PendingMediaArtifact] = []
    for review in reviews:
        if review.status is not ReviewStatus.PENDING:
            continue
        for operation in review.operations:
            if not (operation.json_pointer or "").startswith(
                _ARTIFACT_VERSION_POINTER_PREFIX,
            ):
                continue
            if not isinstance(operation.after, dict):
                logger.warning(
                    "ignoring malformed pending artifact review operation "
                    "review=%r operation=%r",
                    review.review_id,
                    operation.operation_id,
                )
                continue
            try:
                artifact = ArtifactVersion.model_validate(operation.after)
            except ValueError:
                logger.warning(
                    "ignoring malformed pending artifact review operation "
                    "review=%r operation=%r",
                    review.review_id,
                    operation.operation_id,
                )
                continue
            metadata = artifact.metadata
            command_type = str(metadata.get("commandType") or "").strip()
            if not command_type:
                continue
            raw_target = metadata.get("targetRef")
            if not isinstance(raw_target, str) or not raw_target.strip():
                raw_target = artifact.owner_ref
            target_ref = raw_target.strip()
            if not target_ref:
                logger.warning(
                    "ignoring pending artifact review operation "
                    "without target review=%r operation=%r",
                    review.review_id,
                    operation.operation_id,
                )
                continue
            raw_variant_id = metadata.get("variantId")
            variant_id = (
                str(raw_variant_id).strip()
                if raw_variant_id is not None
                else None
            )
            pending.append(
                PendingMediaArtifact(
                    review_id=review.review_id,
                    version_id=artifact.version_id,
                    command_type=command_type,
                    target_ref=target_ref,
                    variant_id=variant_id or None,
                ),
            )
    return tuple(pending)


def assert_media_review_admission(
    *,
    reviews: Sequence[ReviewRecord],
    command_type: str,
    target_ref: str,
    reference_version_ids: Sequence[str],
    variant_id: str | None = None,
) -> None:
    """Reject duplicate targets and consumption of unreviewed artifacts."""

    pending = _pending_media_artifacts(reviews)
    for artifact in pending:
        same_target = (
            artifact.command_type == command_type
            and artifact.target_ref == target_ref
            and (
                artifact.variant_id is None
                or artifact.variant_id == variant_id
            )
        )
        if same_target:
            raise ReviewPendingError(
                f"目标 {target_ref} 的生成结果仍在等待用户审阅"
                f"（{artifact.review_id}）；请等待用户审阅，不要重试同一目标。",
                details={
                    "reason": "TARGET_PENDING_REVIEW",
                    "reviewId": artifact.review_id,
                    "artifactVersionId": artifact.version_id,
                    "targetRef": artifact.target_ref,
                    "commandType": command_type,
                },
            )

    referenced = set(reference_version_ids)
    for artifact in pending:
        if artifact.version_id in referenced:
            raise ReviewPendingError(
                f"输入产物 {artifact.version_id} 仍在等待用户审阅"
                f"（{artifact.review_id}）；请等待用户审阅，不要继续下游生成。",
                details={
                    "reason": "INPUT_PENDING_REVIEW",
                    "reviewId": artifact.review_id,
                    "artifactVersionId": artifact.version_id,
                    "targetRef": target_ref,
                    "pendingTargetRef": artifact.target_ref,
                    "commandType": command_type,
                },
            )


__all__ = ["PendingMediaArtifact", "assert_media_review_admission"]
