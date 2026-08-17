# -*- coding: utf-8 -*-
"""Independent submissions of the same R2V command attach to one task.

Reproduces the 2026-08 production incident: consecutive review approvals
interrupt the delegating director mid-generation; the re-delegated
director resubmits the identical command under a fresh tool-call id and
the provider renders (and bills) the same video twice.
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

_PNG = b"\x89PNG\r\n\x1a\n" + b"dedup-storyboard" * 16

PROJECT_ID = "r2v-dedup-project"
ELEMENT_ID = "r2v-dedup-1"


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
    project = Project.new(project_id=PROJECT_ID, name="R2V Dedup")
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


def test_second_dispatch_attaches_to_in_flight_duplicate(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services_with_storyboard(tmp_path, monkeypatch)

    async def scenario():
        worker = FileR2VExecutionService(services)
        first = await worker.dispatch(
            project_id=PROJECT_ID,
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="video-from-first-tool-call",
            start=False,
        )
        # A different tool call (fresh idempotency key) submits the same
        # command while the first task is still live.
        second = await worker.dispatch(
            project_id=PROJECT_ID,
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="video-from-second-tool-call",
            start=False,
        )
        await worker.shutdown()
        return first, second

    first, second = asyncio.run(scenario())

    assert first.replayed is False
    assert second.replayed is True
    assert second.task_id == first.task_id
    r2v_tasks = [
        task
        for task in ProjectExecutionStore(services.root).list_tasks(
            PROJECT_ID,
        )
        if task.kind.value == "r2v_generation"
    ]
    assert len(r2v_tasks) == 1


def test_different_command_conflicts_while_target_is_in_flight(
    tmp_path,
    monkeypatch,
) -> None:
    """One Element, one in-flight render — different content fails closed.

    The old contract let a different command hash open a second task for
    the same Element; field run 2026-08-11 double-billed exactly that
    way (scheduler rendered the committed video_prompt while a
    specialist re-submitted its own inline rewrite 39s later). The
    Element owns a single video slot, so the loser of the race would be
    silently discarded anyway.
    """

    services = _services_with_storyboard(tmp_path, monkeypatch)

    async def scenario():
        worker = FileR2VExecutionService(services)
        first = await worker.dispatch(
            project_id=PROJECT_ID,
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="video-plain",
            start=False,
        )
        try:
            with pytest.raises(ConflictError, match="不同内容的视频任务"):
                await worker.dispatch(
                    project_id=PROJECT_ID,
                    target_ref=f"element:{ELEMENT_ID}",
                    arguments={"prompt": "另一版：慢动作追逐"},
                    idempotency_key="video-slowmo",
                    start=False,
                )
        finally:
            await worker.shutdown()
        return first

    first = asyncio.run(scenario())

    assert first.replayed is False
    r2v_tasks = [
        task
        for task in ProjectExecutionStore(services.root).list_tasks(
            PROJECT_ID,
        )
        if task.kind.value == "r2v_generation"
    ]
    assert len(r2v_tasks) == 1
