# -*- coding: utf-8 -*-
"""Typed PawApp setup integration for Creator model configuration."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import Request
from schemas.models import ModelConfigData

from qwenpaw.pawapp import (
    ReadinessResult,
    SetupCheckRegistration,
    SetupEntryDescriptor,
    SetupEntryRegistration,
    SetupOpenAction,
    SetupRequest,
    SetupRequirement,
    SetupResult,
)
from qwenpaw.pawapp.tasks import TaskScope, TaskStoreError
from qwenpaw.pawapp.tasks.contracts import content_digest

APP_ID = "qwenpaw-creator"
LLM_ENTRY_ID = "creator-llm-model"
IMAGE_ENTRY_ID = "creator-image-model"
VIDEO_ENTRY_ID = "creator-video-model"
LLM_REQUIREMENT_ID = "creator-llm"
IMAGE_REQUIREMENT_ID = "storyboard-image"
VIDEO_REQUIREMENT_ID = "shot-video"
_SETUP_REQUIREMENTS = {
    LLM_ENTRY_ID: LLM_REQUIREMENT_ID,
    IMAGE_ENTRY_ID: IMAGE_REQUIREMENT_ID,
    VIDEO_ENTRY_ID: VIDEO_REQUIREMENT_ID,
}
_READINESS_TTL_SECONDS = 30.0


def _configuration_revision(path: Path) -> int:
    """Return a public revision for the current persisted configuration."""
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def _load_snapshot() -> tuple[ModelConfigData, int]:
    # Lazy import avoids a model_routes -> setup_coordination import cycle.
    from api.model_routes import _config_paths, load_model_config

    path = _config_paths()
    return load_model_config(
        include_environment=True,
    ), _configuration_revision(
        path,
    )


_MODEL_REQUIREMENTS = {
    "llm": LLM_REQUIREMENT_ID,
    "image": IMAGE_REQUIREMENT_ID,
    "video": VIDEO_REQUIREMENT_ID,
}


def _model_ready(
    data: ModelConfigData,
    purpose: Literal["llm", "image", "video"],
) -> bool:
    item = getattr(data, purpose)
    if (
        not item.enabled
        or not item.model_name.strip()
        or not item.base_url.strip()
    ):
        return False
    if purpose == "video" and "sglang" in item.protocol.casefold():
        return True
    api_key = item.api_key
    if purpose != "llm" and item.reuse_llm_key and not api_key:
        api_key = data.llm.api_key
    return bool(api_key.strip())


async def _check_model(
    scope: TaskScope,
    purpose: Literal["llm", "image", "video"],
) -> ReadinessResult:
    if scope.app_id != APP_ID:
        raise TaskStoreError("setup_scope_mismatch")
    data, revision = await asyncio.to_thread(_load_snapshot)
    now = time.time()
    requirement_id = _MODEL_REQUIREMENTS[purpose]
    if _model_ready(data, purpose):
        return ReadinessResult(
            requirement_id=requirement_id,
            state="ready",
            checked_revision=revision,
            checked_at=now,
            expires_at=now + _READINESS_TTL_SECONDS,
        )
    label = "planning" if purpose == "llm" else f"{purpose} generation"
    return ReadinessResult(
        requirement_id=requirement_id,
        state="needs_configuration",
        reason_code=f"creator_{purpose}_model_missing",
        reason=f"Configure and enable the Creator {label} model.",
        checked_revision=revision,
        checked_at=now,
        expires_at=now + _READINESS_TTL_SECONDS,
    )


async def check_llm_model(
    scope: TaskScope,
    _inputs: dict[str, Any],
) -> ReadinessResult:
    return await _check_model(scope, "llm")


async def check_image_model(
    scope: TaskScope,
    _inputs: dict[str, Any],
) -> ReadinessResult:
    return await _check_model(scope, "image")


async def check_video_model(
    scope: TaskScope,
    _inputs: dict[str, Any],
) -> ReadinessResult:
    return await _check_model(scope, "video")


async def _open_model_setup(
    request: SetupRequest,
    *,
    entry_id: str,
    purpose: Literal["llm", "image", "video"],
) -> SetupOpenAction:
    if request.scope.app_id != APP_ID or request.entry_id != entry_id:
        raise TaskStoreError("setup_scope_mismatch")
    return SetupOpenAction(
        app_id=APP_ID,
        request_id=request.request_id,
        entry_id=entry_id,
        presentation=request.presentation,
        path=(
            f"/apps/{APP_ID}?setup={purpose}"
            f"&setupRequest={request.request_id}"
        ),
    )


async def open_llm_setup(request: SetupRequest) -> SetupOpenAction:
    return await _open_model_setup(
        request,
        entry_id=LLM_ENTRY_ID,
        purpose="llm",
    )


async def open_image_setup(request: SetupRequest) -> SetupOpenAction:
    return await _open_model_setup(
        request,
        entry_id=IMAGE_ENTRY_ID,
        purpose="image",
    )


async def open_video_setup(request: SetupRequest) -> SetupOpenAction:
    return await _open_model_setup(
        request,
        entry_id=VIDEO_ENTRY_ID,
        purpose="video",
    )


def register_creator_setup(app: Any) -> None:
    """Register Creator-owned setup entries before their readiness checks."""
    app.setup_entry(
        SetupEntryRegistration(
            descriptor=SetupEntryDescriptor(
                id=LLM_ENTRY_ID,
                entry_ref="creator.model-settings",
                focus="llm",
                presentations=("app_entry",),
            ),
            opener=open_llm_setup,
        ),
    ).setup_entry(
        SetupEntryRegistration(
            descriptor=SetupEntryDescriptor(
                id=IMAGE_ENTRY_ID,
                entry_ref="creator.model-settings",
                focus="image-generation",
                presentations=("app_entry",),
            ),
            opener=open_image_setup,
        ),
    ).setup_entry(
        SetupEntryRegistration(
            descriptor=SetupEntryDescriptor(
                id=VIDEO_ENTRY_ID,
                entry_ref="creator.model-settings",
                focus="video-generation",
                presentations=("app_entry",),
            ),
            opener=open_video_setup,
        ),
    )
    app.setup_check(
        SetupCheckRegistration(
            requirement=SetupRequirement(
                id=LLM_REQUIREMENT_ID,
                summary="Configure the Creator planning model.",
                required_for=("create-video",),
                authority="AppLocal",
                setup_entry_ref=LLM_ENTRY_ID,
                check_ref="creator.llm-model-ready",
                type_ref="model@1",
            ),
            checker=check_llm_model,
        ),
    ).setup_check(
        SetupCheckRegistration(
            requirement=SetupRequirement(
                id=IMAGE_REQUIREMENT_ID,
                summary="Configure the Creator image generation model.",
                required_for=("generate-storyboard", "create-video"),
                authority="AppLocal",
                setup_entry_ref=IMAGE_ENTRY_ID,
                check_ref="creator.image-model-ready",
                type_ref="model@1",
            ),
            checker=check_image_model,
        ),
    ).setup_check(
        SetupCheckRegistration(
            requirement=SetupRequirement(
                id=VIDEO_REQUIREMENT_ID,
                summary="Configure the Creator video generation model.",
                required_for=("generate-video", "create-video"),
                authority="AppLocal",
                setup_entry_ref=VIDEO_ENTRY_ID,
                check_ref="creator.video-model-ready",
                type_ref="model@1",
            ),
            checker=check_video_model,
        ),
    )


async def complete_model_setup(
    request: Request,
    request_id: str,
    configuration_revision: int,
) -> None:
    """Send a server-generated setup receipt to the Host coordinator."""
    principal = str(getattr(request.state, "user", None) or "default")
    coordinator = request.app.state.pawapp_setup
    scope, record = await coordinator.backend_request(
        principal,
        APP_ID,
        request_id,
    )
    expected_requirement = _SETUP_REQUIREMENTS.get(record.request.entry_id)
    if expected_requirement is None or record.request.requirement_ids != (
        expected_requirement,
    ):
        raise TaskStoreError("setup_result_scope_mismatch")
    result = SetupResult(
        request_id=request_id,
        result_id="setup_result_"
        + content_digest(
            {
                "request_id": request_id,
                "revision": configuration_revision,
                "requirements": record.request.requirement_ids,
            },
        )[:32],
        outcome="saved",
        changed_requirement_ids=record.request.requirement_ids,
        config_revisions={
            requirement_id: configuration_revision
            for requirement_id in record.request.requirement_ids
        },
    )
    await coordinator.complete(scope, result)
