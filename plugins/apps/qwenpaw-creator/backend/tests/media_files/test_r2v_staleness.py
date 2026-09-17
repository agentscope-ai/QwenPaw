# -*- coding: utf-8 -*-
"""Staleness policy for R2V publishes when the Project moves mid-render."""
from __future__ import annotations

import asyncio

import pytest

from domain.errors import ConflictError
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.r2v_execution import FileR2VExecutionService
from services.project_files.facade import CreatorFileServices
from services.project_files.review import ReviewDecisionItem
from services.project_files.models import (
    ElementLocation,
    EntityCollection,
    Project,
    R2VCreation,
    Shot,
    TimelineElement,
    TimelineSpan,
)
from services.runtime_files.models import ChangeOrigin, ReviewPolicy

# pylint: disable=no-name-in-module
from utils.paths import unique_task_work_path

# pylint: enable=no-name-in-module


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"stale-storyboard" * 16
_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"stale-video" * 64

PROJECT_ID = "r2v-stale-project"
ELEMENT_ID = "r2v-1"


class _ImageProvider:
    async def generate(self, **_kwargs):
        return {"content": _PNG, "media_type": "image/png"}


class _MutatingR2VProvider:
    """Succeeds normally, but commits a Project change before polling.

    This reproduces the production race: a commit (typically a review
    approval) lands while the provider renders, so the task's frozen
    input etag no longer matches at publish time.
    """

    def __init__(self, services: CreatorFileServices, mutate) -> None:
        self._services = services
        self._mutate = mutate
        self._mutated = False

    @property
    def mutated(self) -> bool:
        return self._mutated

    async def submit(self, **_kwargs) -> str:
        return "provider-task-stale"

    async def poll(self, provider_task_id: str):
        if not self._mutated:
            self._mutated = True
            base = self._services.projects.read(PROJECT_ID)
            candidate = base.project.model_dump(mode="json")
            self._mutate(candidate)
            self._services.commits.commit(
                base=base,
                candidate=candidate,
                origin=ChangeOrigin.RUNTIME_TASK,
                review_policy=ReviewPolicy.AUTO_FIX,
            )
        path = unique_task_work_path("video", ".mp4", prefix="stale-test-")
        path.write_bytes(_MP4)
        return {
            "task_id": provider_task_id,
            "status": "SUCCEEDED",
            "result_url": path.resolve().as_uri(),
            "media_type": "video/mp4",
            "durationSeconds": 4,
        }


def _r2v_element() -> TimelineElement:
    shot = Shot(
        shot_id=f"{ELEMENT_ID}-shot",
        description="猫追逐老鼠",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=4,
    )
    return TimelineElement(
        element_id=ELEMENT_ID,
        label="猫追老鼠",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="猫发现老鼠后追逐",
            storyboard_prompt="动画分镜：猫发现并追逐老鼠",
            video_prompt="动画，猫从左向右追逐老鼠，动作连续",
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
        ),
    )


def _project_with_storyboard(
    tmp_path,
    monkeypatch,
    *,
    accept_review: bool = True,
) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="R2V Stale")
    project.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ] = _r2v_element()
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )
    asyncio.run(
        FileImageExecutionService(services, provider=_ImageProvider()).execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="storyboard-1",
        ),
    )
    if accept_review:
        for review in services.reviews.all_pending(PROJECT_ID):
            services.reviews.decide(
                project_id=PROJECT_ID,
                review_id=review.review_id,
                decision_token=review.decision_token,
                decisions=[
                    ReviewDecisionItem(
                        operation_id=operation.operation_id,
                        decision="ACCEPT",
                    )
                    for operation in review.operations
                ],
            )
    return services


def _run_video(services: CreatorFileServices, provider):
    async def scenario():
        worker = FileR2VExecutionService(
            services,
            provider=provider,
            poll_interval_seconds=0.01,
            poll_lease_seconds=0.1,
        )
        dispatched = await worker.dispatch(
            project_id=PROJECT_ID,
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="video-1",
        )
        task = await worker.wait_for_task(
            PROJECT_ID,
            dispatched.task_id,
            timeout_seconds=5,
        )
        await worker.shutdown()
        return task

    return asyncio.run(scenario())


def test_unrelated_commit_during_render_does_not_quarantine(
    tmp_path,
    monkeypatch,
) -> None:
    """An etag drift that leaves the render inputs intact still publishes.

    Reproduces the production incident where approving the storyboard
    review while the video rendered quarantined a finished video with
    PROJECT_INPUT_SNAPSHOT_STALE.
    """

    services = _project_with_storyboard(tmp_path, monkeypatch)

    def bump_description(candidate: dict) -> None:
        candidate["description"] = "updated while the video was rendering"

    provider = _MutatingR2VProvider(services, bump_description)
    task = _run_video(services, provider)

    assert task.status.value == "SUCCEEDED"
    finished = services.projects.read(PROJECT_ID).project
    element = finished.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ]
    assert element.outputs["main"].slot_id == f"element:{ELEMENT_ID}:main"


def test_pending_storyboard_review_blocks_r2v_dispatch(
    tmp_path,
    monkeypatch,
) -> None:
    services = _project_with_storyboard(
        tmp_path,
        monkeypatch,
        accept_review=False,
    )
    provider = _MutatingR2VProvider(services, lambda _candidate: None)

    with pytest.raises(ConflictError, match="不要继续下游生成"):
        _run_video(services, provider)

    assert not provider.mutated


def test_changed_render_inputs_during_render_still_quarantine(
    tmp_path,
    monkeypatch,
) -> None:
    """Losing the storyboard selection mid-render keeps fail-closed."""

    services = _project_with_storyboard(tmp_path, monkeypatch)

    def clear_storyboard_selection(candidate: dict) -> None:
        slot = candidate["assets"]["artifact_slots_by_id"][
            f"element:{ELEMENT_ID}:storyboard"
        ]
        slot["selected_version_id"] = None

    provider = _MutatingR2VProvider(services, clear_storyboard_selection)
    task = _run_video(services, provider)

    assert task.status.value == "QUARANTINED"
    assert (task.error or {}).get("code") == "PROJECT_INPUT_SNAPSHOT_STALE"
