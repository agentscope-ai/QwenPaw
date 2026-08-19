# -*- coding: utf-8 -*-
"""Transient image failures reopen a retry slot; deterministic ones stay walls.

Reproduces the 2026-08 production deadlock: a network blip failed the
image Task terminally, and because identical retries derive the same
durable slot, every same-argument resend hit "图片 Task 已终止: FAILED"
forever.
"""
from __future__ import annotations

import asyncio

import pytest

from domain.errors import ConflictError
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.transient_errors import is_transient_task_error
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
from utils.exceptions import ModelError


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"retry-image" * 16

PROJECT_ID = "image-retry-project"
ELEMENT_ID = "r2v-retry-1"


class _GoodProvider:
    async def generate(self, **_kwargs):
        return {"content": _PNG, "media_type": "image/png"}


class _FailingProvider:
    def __init__(self, message: str) -> None:
        self._message = message

    async def generate(self, **_kwargs):
        raise RuntimeError(self._message)


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    shot = Shot(
        shot_id=f"{ELEMENT_ID}-shot",
        description="猫追逐老鼠",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=4,
    )
    project = Project.new(project_id=PROJECT_ID, name="Image Retry")
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
    return services


def _execute(services, provider, key="storyboard-key"):
    return asyncio.run(
        FileImageExecutionService(services, provider=provider).execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key=key,
        ),
    )


def test_transient_failure_reopens_a_retry_slot(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="All connection attempts failed"):
        _execute(
            services,
            _FailingProvider("All connection attempts failed"),
        )

    # The identical retry must run again instead of hitting the wall.
    result = _execute(services, _GoodProvider())
    assert result.replayed is False
    assert result.artifact_version_id


def test_deterministic_rejection_keeps_the_terminal_wall(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch)
    safety_message = (
        "Image generation failed with status 400: Your request was "
        "rejected by the safety system"
    )

    # Safety refusals surface as non-retryable ModelError (and carry the
    # reference-vs-prompt guidance tested in test_image_safety_rejection).
    with pytest.raises(ModelError):
        _execute(services, _FailingProvider(safety_message))

    with pytest.raises(ConflictError) as caught:
        _execute(services, _GoodProvider())
    message = str(caught.value)
    assert "原失败原因" in message
    assert "rejected by the safety system" in message
    assert "调整 arguments" in message


def test_exhausted_transient_slots_stop_retrying(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)
    flaky = _FailingProvider("connection timeout")

    for _ in range(4):  # original slot + 3 retry slots
        with pytest.raises(RuntimeError):
            _execute(services, flaky)

    with pytest.raises(ConflictError, match="瞬态重试槽位已用尽"):
        _execute(services, _GoodProvider())


def test_transient_error_classifier():
    assert is_transient_task_error(
        {"message": "All connection attempts failed"},
    )
    assert is_transient_task_error({"message": "Read Timed Out"})
    assert is_transient_task_error({"message": "status 503 from provider"})
    # DNS resolution failures: no billable request ever left the machine,
    # so a bounded retry is free (field run 2026-08-07: one [Errno 8]
    # blip permanently locked three nodes under the old classification).
    assert is_transient_task_error(
        {
            "message": (
                "[Errno 8] nodename nor servname provided, or not known"
            ),
        },
    )
    assert is_transient_task_error(
        {"message": "[Errno -2] Name or service not known"},
    )
    assert is_transient_task_error(
        {"message": "getaddrinfo failed"},
    )
    # httpx transport errors (WriteError/ReadError/ConnectError) stringify
    # empty; the provider now labels them "connection failure: <type>" so
    # they classify as transient instead of locking the node (field run
    # 2026-08-10: an upload burst walled two storyboards).
    assert is_transient_task_error(
        {"message": "Image generation connection failure: WriteError"},
    )
    assert is_transient_task_error(
        {"message": "opaque failure", "retryable": True},
    )
    assert not is_transient_task_error(
        {"message": "rejected by the safety system"},
    )
    assert not is_transient_task_error(None)
