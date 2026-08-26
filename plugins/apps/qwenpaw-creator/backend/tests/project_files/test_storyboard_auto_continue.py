# -*- coding: utf-8 -*-
"""Approved storyboards auto-start their video under allow_all authorization.

The Runtime never auto-resumed a paused specialist: after approval the
mainline had to re-delegate, and models routinely skipped that step while
claiming the video was already running (2026-08 incidents).
"""
# pylint: disable=protected-access
from __future__ import annotations

import asyncio

import pytest

from models import config as creator_config
from services.media_files import r2v_execution
from services.media_files.image_execution import FileImageExecutionService
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


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"auto-continue" * 16

PROJECT_ID = "auto-continue-project"
ELEMENT_ID = "r2v-auto-1"


class _ImageProvider:
    async def generate(self, **_kwargs):
        return {"content": _PNG, "media_type": "image/png"}


def _services_with_pending_review(
    tmp_path,
    monkeypatch,
) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    shot = Shot(
        shot_id=f"{ELEMENT_ID}-shot",
        description="猫追逐老鼠",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=4,
    )
    project = Project.new(project_id=PROJECT_ID, name="Auto Continue")
    project.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ] = TimelineElement(
        element_id=ELEMENT_ID,
        label="猫追老鼠",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="猫发现老鼠后追逐",
            storyboard_prompt="动画分镜：猫发现并追逐老鼠",
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
        ),
    )
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
    return services


def _accept_pending_review(services, decision_id: str) -> str:
    review = services.reviews.all_pending(PROJECT_ID)[0]
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
        decision_id=decision_id,
    )
    return review.review_id


def test_allow_all_auto_starts_video_for_approved_storyboard(
    tmp_path,
    monkeypatch,
):
    services = _services_with_pending_review(tmp_path, monkeypatch)
    review_id = _accept_pending_review(services, "decision-auto-1")
    monkeypatch.setattr(
        creator_config,
        "get_execution_authorization_mode",
        lambda: creator_config.EXECUTION_AUTHORIZATION_ALLOW_ALL,
    )
    dispatched: list[dict] = []

    async def fake_execute(_services, **kwargs):
        dispatched.append(kwargs)

    monkeypatch.setattr(
        r2v_execution,
        "execute_file_r2v_command",
        fake_execute,
    )

    asyncio.run(
        services.publish_review_followup(
            project_id=PROJECT_ID,
            review_id=review_id,
            decision_id="decision-auto-1",
        ),
    )

    assert len(dispatched) == 1
    assert dispatched[0]["target_ref"] == f"element:{ELEMENT_ID}"
    assert dispatched[0]["idempotency_key"].startswith(
        "review-auto-continue-",
    )


def test_required_authorization_mode_never_auto_starts(
    tmp_path,
    monkeypatch,
):
    services = _services_with_pending_review(tmp_path, monkeypatch)
    review_id = _accept_pending_review(services, "decision-auto-2")
    monkeypatch.setattr(
        creator_config,
        "get_execution_authorization_mode",
        lambda: creator_config.EXECUTION_AUTHORIZATION_REQUIRED,
    )
    dispatched: list[dict] = []

    async def fake_execute(_services, **kwargs):
        dispatched.append(kwargs)

    monkeypatch.setattr(
        r2v_execution,
        "execute_file_r2v_command",
        fake_execute,
    )

    asyncio.run(
        services.publish_review_followup(
            project_id=PROJECT_ID,
            review_id=review_id,
            decision_id="decision-auto-2",
        ),
    )

    assert not dispatched
