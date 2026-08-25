# -*- coding: utf-8 -*-
"""media_review auto_approve: the last gate of the unattended ladder.

``required`` (default) parks generated media behind a pending Review;
``auto_approve`` reuses the AUTO_FIX acceptance path.
"""
from __future__ import annotations

import asyncio

import pytest

from services.media_files.image_execution import FileImageExecutionService
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ElementLocation,
    EntityCollection,
    Project,
    R2VCreation,
    Shot,
    TimelineElement,
    TimelineSpan,
)
from services.runtime_files.models import ReviewStatus


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"yolo-image" * 16

PROJECT_ID = "media-review-mode-project"
ELEMENT_ID = "r2v-yolo-1"


class _GoodProvider:
    async def generate(self, **_kwargs):
        return {"content": _PNG, "media_type": "image/png"}


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    shot = Shot(
        shot_id=f"{ELEMENT_ID}-shot",
        description="主角走向舞台中央",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=4,
    )
    project = Project.new(project_id=PROJECT_ID, name="Media Review Mode")
    project.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ] = TimelineElement(
        element_id=ELEMENT_ID,
        label="走向舞台",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="主角走向舞台中央",
            storyboard_prompt="动画分镜：主角走向舞台中央",
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
        ),
    )
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )
    return services


def _generate(services) -> None:
    asyncio.run(
        FileImageExecutionService(services, provider=_GoodProvider()).execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="yolo-storyboard",
        ),
    )


def _active_review(services):
    return services.reviews.active(PROJECT_ID)


def test_required_mode_parks_media_behind_a_pending_review(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch)

    _generate(services)

    review = _active_review(services)
    assert review is not None
    assert review.status is ReviewStatus.PENDING


def test_auto_approve_mode_accepts_media_without_review(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "services.media_files.review_admission.get_media_review_mode",
        lambda: "auto_approve",
    )

    _generate(services)

    assert _active_review(services) is None
    snapshot = services.projects.read(PROJECT_ID)
    # The storyboard artifact is accepted directly into the Project.
    slots = snapshot.project.assets.artifact_slots_by_id
    assert any(
        slot.kind == "r2v_storyboard_image"
        and slot.selected_version_id is not None
        for slot in slots.values()
    )
