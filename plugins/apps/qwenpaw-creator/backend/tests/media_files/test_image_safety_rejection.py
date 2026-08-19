# -*- coding: utf-8 -*-
"""Safety refusals must name the refs they saw and block verbatim resends.

Reproduces the 2026-08-05 field incident: 22 consecutive 400s because the
model narrated "removing the photo references" while resending the exact
same reference list on every call.
"""
from __future__ import annotations

import asyncio

import pytest

from domain.errors import ConflictError
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
from utils.exceptions import ModelError


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"safety-image" * 16

PROJECT_ID = "image-safety-project"
ELEMENT_ID = "r2v-safety-1"
_SAFETY_MESSAGE = (
    "Image generation failed with status 400: Your request was "
    "rejected by the safety system"
)
_PHOTO_URL = "https://example.com/messi-photo.jpg"


class _CountingProvider:
    def __init__(self, *, fail_with: str | None = None) -> None:
        self.calls = 0
        self._fail_with = fail_with

    async def generate(self, **_kwargs):
        self.calls += 1
        if self._fail_with is not None:
            raise RuntimeError(self._fail_with)
        return {"content": _PNG, "media_type": "image/png"}


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    shot = Shot(
        shot_id=f"{ELEMENT_ID}-shot",
        description="两位球员并肩走向球场",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=4,
    )
    project = Project.new(project_id=PROJECT_ID, name="Image Safety")
    project.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ] = TimelineElement(
        element_id=ELEMENT_ID,
        label="并肩入场",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="两位球员并肩走向球场",
            storyboard_prompt="动画分镜：两位球员并肩入场",
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


def _execute(service, *, key, reference_urls=()):
    arguments = {}
    if reference_urls:
        arguments["referenceImageUrls"] = list(reference_urls)
    return asyncio.run(
        service.execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments=arguments,
            idempotency_key=key,
        ),
    )


def test_safety_rejection_names_the_refs_it_saw(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)
    service = FileImageExecutionService(
        services,
        provider=_CountingProvider(fail_with=_SAFETY_MESSAGE),
    )

    with pytest.raises(ModelError) as caught:
        _execute(service, key="k1", reference_urls=[_PHOTO_URL])

    message = str(caught.value)
    assert _PHOTO_URL in message
    assert "仅修改 prompt 的重试不会成功" in message
    assert caught.value.retryable is False


def test_verbatim_refs_resend_is_blocked_locally(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)
    provider = _CountingProvider(fail_with=_SAFETY_MESSAGE)
    service = FileImageExecutionService(services, provider=provider)

    with pytest.raises(ModelError):
        _execute(service, key="k1", reference_urls=[_PHOTO_URL])
    assert provider.calls == 1

    # Reworded prompt, identical refs, fresh idempotency key: the provider
    # must not be consulted again.
    with pytest.raises(ConflictError, match="已本地拦截"):
        _execute(service, key="k2", reference_urls=[_PHOTO_URL])
    assert provider.calls == 1


def test_dropping_the_refs_unblocks_generation(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)
    provider = _CountingProvider(fail_with=_SAFETY_MESSAGE)
    service = FileImageExecutionService(services, provider=provider)

    with pytest.raises(ModelError):
        _execute(service, key="k1", reference_urls=[_PHOTO_URL])

    # Same service, refs removed: the local block must not apply.
    provider._fail_with = None  # pylint: disable=protected-access
    result = _execute(service, key="k3")
    assert result.artifact_version_id
    assert provider.calls == 2


def test_textual_rejection_points_at_the_prompt(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)
    service = FileImageExecutionService(
        services,
        provider=_CountingProvider(fail_with=_SAFETY_MESSAGE),
    )

    with pytest.raises(ModelError) as caught:
        _execute(service, key="k1")

    assert "prompt 文本本身" in str(caught.value)
