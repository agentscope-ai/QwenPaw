# -*- coding: utf-8 -*-
"""Review-pending admission for paid media generation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging

import pytest

from domain.errors import ConflictError, ReviewPendingError, ValidationError
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.review_admission import assert_media_review_admission
from services.media_files.visual_reference_resolution import (
    resolve_r2v_visual_reference_version_ids,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ArtifactVersion,
    EntityCollection,
    Project,
    R2VCreation,
    VisualEntity,
    VisualVariant,
)
from services.runtime_files.models import (
    ProjectChangeKind,
    ReviewOperation,
    ReviewOperationDecision,
    ReviewRecord,
    ReviewStatus,
)


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"review-admission" * 16


class _CountingImageProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **_kwargs):
        self.calls += 1
        return {"content": _PNG, "media_type": "image/png"}


def _artifact(
    *,
    version_id: str = "artifact-version-pending",
    target_ref: str = "asset:char:hero",
    variant_id: str | None = "variant:hero-peak",
) -> ArtifactVersion:
    metadata = {
        "commandType": "GENERATE_ASSET",
        "targetRef": target_ref,
    }
    if variant_id is not None:
        metadata["variantId"] = variant_id
    return ArtifactVersion(
        version_id=version_id,
        slot_id="asset:char:hero:image",
        kind="visual_asset_image",
        owner_ref=target_ref,
        name="Hero visual",
        file_id="file-pending",
        checksum="a" * 64,
        based_on_generation=1,
        created_at=datetime.now(UTC),
        metadata=metadata,
    )


def _review(
    *,
    status: ReviewStatus = ReviewStatus.PENDING,
    decision: ReviewOperationDecision = ReviewOperationDecision.PENDING,
    artifact: ArtifactVersion | None = None,
) -> ReviewRecord:
    media = artifact or _artifact()
    return ReviewRecord(
        review_id="review-media-1",
        round_id="round-media-1",
        baseline_generation=0,
        baseline_etag="sha256:baseline",
        candidate_generation=1,
        candidate_etag="sha256:candidate",
        decision_token="token-media-1",
        status=status,
        operations=[
            ReviewOperation(
                kind=ProjectChangeKind.CREATE,
                json_pointer=(
                    "/assets/artifact_versions_by_id/"
                    + media.version_id.replace("~", "~0").replace("/", "~1")
                ),
                before_hash="sha256:missing",
                after_hash="sha256:artifact",
                after=media.model_dump(mode="json"),
                operation_id="operation-media-1",
                decision=decision,
            ),
        ],
    )


def test_pending_review_blocks_same_variant_but_not_another_variant() -> None:
    reviews = [_review()]

    with pytest.raises(
        ReviewPendingError,
        match="不要重试同一目标",
    ) as captured:
        assert_media_review_admission(
            reviews=reviews,
            command_type="GENERATE_ASSET",
            target_ref="asset:char:hero",
            variant_id="variant:hero-peak",
            reference_version_ids=(),
        )
    assert captured.value.code == "WAITING_REVIEW"
    assert captured.value.retryable is False
    assert captured.value.details == {
        "reason": "TARGET_PENDING_REVIEW",
        "reviewId": "review-media-1",
        "artifactVersionId": "artifact-version-pending",
        "targetRef": "asset:char:hero",
        "commandType": "GENERATE_ASSET",
    }

    assert_media_review_admission(
        reviews=reviews,
        command_type="GENERATE_ASSET",
        target_ref="asset:char:hero",
        variant_id="variant:hero-fallen",
        reference_version_ids=(),
    )


def test_pending_review_blocks_exact_artifact_downstream() -> None:
    with pytest.raises(
        ReviewPendingError,
        match="不要继续下游生成",
    ) as captured:
        assert_media_review_admission(
            reviews=[_review()],
            command_type="GENERATE_R2V_VIDEO",
            target_ref="element:shot-1",
            reference_version_ids=("artifact-version-pending",),
        )
    assert captured.value.details["reason"] == "INPUT_PENDING_REVIEW"
    assert captured.value.details["targetRef"] == "element:shot-1"


def test_resolved_or_unrelated_review_does_not_block() -> None:
    rejected = _review(
        status=ReviewStatus.RESOLVED,
        decision=ReviewOperationDecision.REJECTED,
    )
    assert_media_review_admission(
        reviews=[rejected],
        command_type="GENERATE_ASSET",
        target_ref="asset:char:hero",
        variant_id="variant:hero-peak",
        reference_version_ids=(),
    )
    assert_media_review_admission(
        reviews=[_review()],
        command_type="GENERATE_ASSET",
        target_ref="asset:char:other",
        variant_id="variant:other",
        reference_version_ids=(),
    )


def test_missing_target_is_skipped_without_stringifying_none(caplog) -> None:
    artifact = _artifact().model_copy(
        update={
            "owner_ref": "",
            "metadata": {"commandType": "GENERATE_ASSET"},
        },
    )

    with caplog.at_level(logging.WARNING):
        assert_media_review_admission(
            reviews=[_review(artifact=artifact)],
            command_type="GENERATE_ASSET",
            target_ref="",
            variant_id=None,
            reference_version_ids=(),
        )

    assert "without target" in caplog.text


def test_malformed_artifact_operation_is_observable(caplog) -> None:
    review = _review()
    malformed = review.operations[0].model_copy(
        update={"after": {"version_id": "artifact-version-broken"}},
    )
    review = review.model_copy(update={"operations": [malformed]})

    with caplog.at_level(logging.WARNING):
        assert_media_review_admission(
            reviews=[review],
            command_type="GENERATE_ASSET",
            target_ref="asset:char:hero",
            variant_id="variant:hero-peak",
            reference_version_ids=(),
        )

    assert "malformed pending artifact review operation" in caplog.text


def test_image_execution_freezes_only_the_pending_variant(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id="project-review-admission", name="Review")
    variants = EntityCollection[VisualVariant](
        items={
            "variant:hero-peak": VisualVariant(
                variant_id="variant:hero-peak",
                prompt="peak hero",
            ),
            "variant:hero-fallen": VisualVariant(
                variant_id="variant:hero-fallen",
                prompt="fallen hero",
            ),
        },
        order=["variant:hero-peak", "variant:hero-fallen"],
    )
    project.visual.entities.items["char:hero"] = VisualEntity(
        entity_id="char:hero",
        kind="character",
        name="Hero",
        required_variant_ids=[
            "variant:hero-peak",
            "variant:hero-fallen",
        ],
        variants=variants,
    )
    project.visual.entities.order.append("char:hero")
    services.projects.create(project)
    provider = _CountingImageProvider()
    worker = FileImageExecutionService(services, provider=provider)

    first = asyncio.run(
        worker.execute(
            project_id=project.project_id,
            command="GENERATE_ASSET",
            target_ref="asset:char:hero",
            arguments={
                "prompt": "peak hero",
                "variantId": "variant:hero-peak",
            },
            idempotency_key="peak-first",
        ),
    )
    with pytest.raises(ConflictError, match="不要重试同一目标"):
        asyncio.run(
            worker.execute(
                project_id=project.project_id,
                command="GENERATE_ASSET",
                target_ref="asset:char:hero",
                arguments={
                    "prompt": "peak hero",
                    "variantId": "variant:hero-peak",
                },
                idempotency_key="peak-retry",
            ),
        )

    fallen = asyncio.run(
        worker.execute(
            project_id=project.project_id,
            command="GENERATE_ASSET",
            target_ref="asset:char:hero",
            arguments={
                "prompt": "fallen hero",
                "variantId": "variant:hero-fallen",
            },
            idempotency_key="fallen-first",
        ),
    )

    assert provider.calls == 2
    snapshot = services.projects.read(project.project_id).project
    assert (
        snapshot.assets.artifact_versions_by_id[
            first.artifact_version_id
        ].metadata["variantId"]
        == "variant:hero-peak"
    )
    assert (
        snapshot.assets.artifact_versions_by_id[
            fallen.artifact_version_id
        ].metadata["variantId"]
        == "variant:hero-fallen"
    )
    peak_variant = snapshot.visual.entities.items["char:hero"].variants.items[
        "variant:hero-peak"
    ]
    fallen_variant = snapshot.visual.entities.items[
        "char:hero"
    ].variants.items["variant:hero-fallen"]
    assert peak_variant.selected_artifact_version_id == (
        first.artifact_version_id
    )
    assert fallen_variant.selected_artifact_version_id == (
        fallen.artifact_version_id
    )
    assert (
        snapshot.assets.artifact_versions_by_id[
            first.artifact_version_id
        ].slot_id
        != snapshot.assets.artifact_versions_by_id[
            fallen.artifact_version_id
        ].slot_id
    )
    assert (
        snapshot.visual.entities.items[
            "char:hero"
        ].selected_artifact_version_id
        is None
    )

    resolved = resolve_r2v_visual_reference_version_ids(
        snapshot,
        R2VCreation(
            character_refs=["char:hero"],
            visual_variant_refs={
                "char:hero": "variant:hero-fallen",
            },
        ),
        [
            first.artifact_version_id,
            fallen.artifact_version_id,
        ],
    )
    assert resolved == (fallen.artifact_version_id,)


def test_visual_reference_resolution_fails_closed_for_missing_entity() -> None:
    broken = Project.new(
        project_id="project-missing-visual",
        name="Missing visual",
    )

    with pytest.raises(ValidationError, match="视觉引用实体不存在"):
        resolve_r2v_visual_reference_version_ids(
            broken,
            R2VCreation(character_refs=["char:hero"]),
            [],
        )
