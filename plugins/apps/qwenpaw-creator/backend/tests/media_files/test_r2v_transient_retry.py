# -*- coding: utf-8 -*-
"""Transient R2V failures reopen a retry slot; deterministic ones stay walls.

Mirrors test_image_transient_retry for the video path: a network blip
failed the R2V Task terminally, and because identical retries derive the
same durable slot, every same-argument resend replayed the FAILED task
forever.
"""
from __future__ import annotations

import asyncio

import pytest

from domain.errors import ConflictError
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.r2v_execution import FileR2VExecutionService
from services.project_files.facade import CreatorFileServices
from services.project_files.review import ReviewDecisionItem
from services.runtime_files.execution_store import ProjectExecutionStore
from services.project_files.models import (
    ElementLocation,
    EntityCollection,
    Project,
    R2VCreation,
    Shot,
    TimelineElement,
    TimelineSpan,
)


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"retry-storyboard" * 16

PROJECT_ID = "r2v-retry-project"
ELEMENT_ID = "r2v-retry-1"


class _ImageProvider:
    async def generate(self, **_kwargs):
        return {"content": _PNG, "media_type": "image/png"}


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


def _services_with_storyboard(tmp_path, monkeypatch) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="R2V Retry")
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


def _dispatch(services, key="video-retry-key"):
    async def scenario():
        worker = FileR2VExecutionService(services)
        try:
            return await worker.dispatch(
                project_id=PROJECT_ID,
                target_ref=f"element:{ELEMENT_ID}",
                arguments={},
                idempotency_key=key,
                start=False,
            )
        finally:
            await worker.shutdown()

    return asyncio.run(scenario())


def _fail_task(services, task_id: str, message: str) -> None:
    ProjectExecutionStore(services.root).transition_task(
        PROJECT_ID,
        task_id,
        expected_status="QUEUED",
        status="FAILED",
        updates={
            "error": {
                "code": "R2V_SUPERVISOR_FAILED",
                "message": message,
                "retryable": False,
            },
        },
    )


def test_transient_failure_reopens_a_retry_slot(tmp_path, monkeypatch):
    services = _services_with_storyboard(tmp_path, monkeypatch)

    first = _dispatch(services)
    assert first.replayed is False
    _fail_task(services, first.task_id, "All connection attempts failed")

    # The identical retry must open a fresh slot instead of replaying
    # the FAILED task.
    second = _dispatch(services)
    assert second.replayed is False
    assert second.task_id != first.task_id


def test_deterministic_failure_keeps_the_terminal_wall(
    tmp_path,
    monkeypatch,
):
    services = _services_with_storyboard(tmp_path, monkeypatch)

    first = _dispatch(services)
    _fail_task(
        services,
        first.task_id,
        "provider status=FAILED: input storyboard contains a real human face",
    )

    with pytest.raises(ConflictError) as caught:
        _dispatch(services)
    message = str(caught.value)
    assert "原失败原因" in message
    assert "real human face" in message
    assert "调整 arguments" in message


def test_exhausted_transient_slots_stop_retrying(tmp_path, monkeypatch):
    services = _services_with_storyboard(tmp_path, monkeypatch)

    for _ in range(4):  # original slot + 3 retry slots
        result = _dispatch(services)
        _fail_task(services, result.task_id, "connection timeout")

    with pytest.raises(ConflictError, match="瞬态重试槽位已用尽"):
        _dispatch(services)
