# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Review-pending admission for paid media generation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from domain.errors import ConflictError, ReviewPendingError
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.review_admission import assert_media_review_admission
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ArtifactVersion,
    EntityCollection,
    Project,
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
    metadata = {"commandType": "GENERATE_ASSET", "targetRef": target_ref}
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


def _admit(reviews, *, variant_id=None):
    return assert_media_review_admission(
        reviews=reviews,
        command_type="GENERATE_ASSET",
        target_ref="asset:char:hero",
        variant_id=variant_id,
        reference_version_ids=(),
    )


def test_pending_review_blocks_same_variant_but_not_another_variant() -> None:
    reviews = [_review()]

    with pytest.raises(ReviewPendingError, match="不要重试同一目标") as captured:
        _admit(reviews, variant_id="variant:hero-peak")
    assert captured.value.code == "WAITING_REVIEW"
    assert captured.value.details["reason"] == "TARGET_PENDING_REVIEW"

    _admit(reviews, variant_id="variant:hero-fallen")
    _admit(
        [
            _review(
                status=ReviewStatus.RESOLVED,
                decision=ReviewOperationDecision.REJECTED,
            ),
        ],
        variant_id="variant:hero-peak",
    )


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
        required_variant_ids=["variant:hero-peak", "variant:hero-fallen"],
        variants=variants,
    )
    project.visual.entities.order.append("char:hero")
    services.projects.create(project)
    provider = _CountingImageProvider()
    worker = FileImageExecutionService(services, provider=provider)

    def _generate(prompt: str, variant_id: str, key: str):
        return asyncio.run(
            worker.execute(
                project_id=project.project_id,
                command="GENERATE_ASSET",
                target_ref="asset:char:hero",
                arguments={"prompt": prompt, "variantId": variant_id},
                idempotency_key=key,
            ),
        )

    first = _generate("peak hero", "variant:hero-peak", "peak-first")
    with pytest.raises(ConflictError, match="不要重试同一目标"):
        _generate("peak hero", "variant:hero-peak", "peak-retry")

    fallen = _generate("fallen hero", "variant:hero-fallen", "fallen-first")

    assert provider.calls == 2
    snapshot = services.projects.read(project.project_id).project
    hero = snapshot.visual.entities.items["char:hero"]
    assert (
        hero.variants.items["variant:hero-peak"].selected_artifact_version_id
        == first.artifact_version_id
    )
    assert (
        hero.variants.items["variant:hero-fallen"].selected_artifact_version_id
        == fallen.artifact_version_id
    )
    assert hero.selected_artifact_version_id is None


def test_validate_local_media_execution_rejects_pending_review_inputs(
    tmp_path,
    monkeypatch,
) -> None:
    """The route-level precheck must mirror execute()'s review admission,
    or the render route returns 202 with a taskId that never materializes
    (auto-compose regression on the review-pending path)."""

    from types import SimpleNamespace

    from domain.enums import CreatorCommandType
    from services.media_files import local_execution

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id="project-validate-review", name="Validate"),
    )

    resolved = SimpleNamespace(
        command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
        target_ref="timeline:timeline:main",
        inputs=(SimpleNamespace(version_id="artifact-version-pending"),),
    )
    monkeypatch.setattr(
        local_execution,
        "_resolve_execution",
        lambda **_kwargs: resolved,
    )
    monkeypatch.setattr(
        services.reviews,
        "all_pending",
        lambda _project_id: [_review()],
    )

    def _validate():
        local_execution.validate_local_media_execution(
            services,
            project_id="project-validate-review",
            command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
            target_ref="timeline:timeline:main",
        )

    with pytest.raises(ReviewPendingError, match="不要继续下游生成"):
        _validate()

    # Once no review is pending the same precheck admits the compose.
    monkeypatch.setattr(
        services.reviews,
        "all_pending",
        lambda _project_id: [],
    )
    _validate()
