# -*- coding: utf-8 -*-
"""Authenticated plugin API for desktop recording controls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from qwenpaw.app.utils import schedule_agent_reload
from .errors import (
    RecordingConsentError,
    RecordingDraftError,
    RecordingLearnError,
    RecordingProtocolError,
    RecordingStateError,
    RecordingStoreError,
)
from .learn_models import (
    LearnEvidencePreview,
    MaterializedSkill,
    RecordingReview,
    ReviewedSkillDraft,
)
from .learning import DesktopLearningService
from .models import RecordingStatus
from .service import DesktopRecordingService

_ResultT = TypeVar("_ResultT")


class PrepareLearnRequest(BaseModel):
    """User intent and optional event selection for local evidence preview."""

    model_config = ConfigDict(extra="forbid")

    recording_id: UUID
    goal: str = Field(min_length=1, max_length=500)
    confirmed_context: str = Field(default="", max_length=2000)
    selected_sequences: list[int] | None = Field(default=None, max_length=2000)


class ReviewRecordingRequest(BaseModel):
    """Select one completed recording for local timeline review."""

    model_config = ConfigDict(extra="forbid")

    recording_id: UUID


class GenerateLearnRequest(BaseModel):
    """One-time consent challenge accepted by the user."""

    model_config = ConfigDict(extra="forbid")

    consent_token: UUID
    consent: Literal[True]


class MaterializeSkillRequest(BaseModel):
    """Reviewed Skill content explicitly approved for workspace creation."""

    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    name: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)
    content: str = Field(min_length=1, max_length=100_000)
    approved: Literal[True]


def _service(request: Request) -> DesktopRecordingService:
    service = getattr(request.state, "desktop_recording_service", None)
    if not isinstance(service, DesktopRecordingService):
        raise HTTPException(status_code=503, detail="recording_unavailable")
    return service


def _learning_service(request: Request) -> DesktopLearningService:
    service = getattr(request.state, "desktop_learning_service", None)
    if not isinstance(service, DesktopLearningService):
        raise HTTPException(
            status_code=503,
            detail="recording_learn_unavailable",
        )
    return service


async def _run(
    operation: Callable[[], Awaitable[RecordingStatus]],
) -> RecordingStatus:
    try:
        return await operation()
    except RecordingStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RecordingProtocolError as exc:
        code = str(exc)
        # EventStream errors carry a stable code followed by native detail.
        # Permission denial is not a transport outage, including on the first
        # request before a recording has been created.
        permission_codes = {
            "input_monitoring_denied",
            "input_monitoring_permission_required",
            "accessibility_permission_required",
            "screen_recording_permission_required",
            "recording_permission_revoked",
        }
        environment_codes = {
            "recording_screen_locked",
            "recording_secure_input",
            "recording_session_inactive",
            "recording_environment_changed",
        }
        reason = code.split(":", 1)[0]
        if reason in permission_codes:
            status_code = 403
        elif reason in environment_codes:
            status_code = 409
        else:
            status_code = 503
        raise HTTPException(status_code=status_code, detail=code) from exc
    except RecordingStoreError as exc:
        raise HTTPException(
            status_code=500,
            detail="recording_store_failed",
        ) from exc


async def _run_learn(operation: Callable[[], Awaitable[_ResultT]]) -> _ResultT:
    try:
        return await operation()
    except RecordingConsentError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RecordingDraftError as exc:
        code = str(exc)
        status_code = (
            409
            if code
            in {
                "skill_name_conflict",
                "skill_draft_has_unresolved_ambiguities",
            }
            else 422
        )
        raise HTTPException(status_code=status_code, detail=code) from exc
    except RecordingLearnError as exc:
        code = str(exc)
        status_code = (
            503
            if code
            in {
                "learn_model_unavailable",
                "learn_provider_unavailable",
                "learn_model_timeout",
                "learn_model_failed",
            }
            else 400
        )
        raise HTTPException(status_code=status_code, detail=code) from exc
    except RecordingStoreError as exc:
        raise HTTPException(
            status_code=404,
            detail="recording_not_found",
        ) from exc


def build_router(
    request_guard: Callable | None = None,
    *,
    prefix: str = "",
) -> APIRouter:
    """Create product routes bound to one optional plugin request lifetime."""
    recording_router = APIRouter(
        prefix=prefix,
        tags=["desktop-recording"],
        dependencies=[Depends(request_guard)] if request_guard else [],
    )

    @recording_router.get("", response_model=RecordingStatus)
    async def get_recording_status(request: Request) -> RecordingStatus:
        """Return availability and current global recording state."""
        return await _run(_service(request).status)

    @recording_router.post("/start", response_model=RecordingStatus)
    async def start_recording(request: Request) -> RecordingStatus:
        """Start in the current agent workspace.

        Paths never come from clients.
        """
        from qwenpaw.app.agent_context import get_agent_for_request

        workspace = await get_agent_for_request(request)
        user_id = str(getattr(request.state, "user", "local-console"))
        service = _service(request)
        return await _run(
            lambda: service.start(
                workspace_dir=workspace.workspace_dir,
                agent_id=workspace.agent_id,
                user_id=user_id,
            ),
        )

    @recording_router.post(
        "/permission/request",
        response_model=RecordingStatus,
    )
    async def request_recording_permission(
        request: Request,
    ) -> RecordingStatus:
        """Request permissions from the selected recording runtime."""
        return await _run(_service(request).request_permissions)

    @recording_router.post("/pause", response_model=RecordingStatus)
    async def pause_recording(request: Request) -> RecordingStatus:
        """Pause the active recording after draining its sequence barrier."""
        return await _run(_service(request).pause)

    @recording_router.post("/resume", response_model=RecordingStatus)
    async def resume_recording(request: Request) -> RecordingStatus:
        """Resume the paused recording."""
        return await _run(_service(request).resume)

    @recording_router.post("/stop", response_model=RecordingStatus)
    async def stop_recording(request: Request) -> RecordingStatus:
        """Finalize the active recording and return its terminal metadata."""
        return await _run(_service(request).stop)

    @recording_router.post(
        "/learn/prepare",
        response_model=LearnEvidencePreview,
    )
    async def prepare_recording_learn(
        request: Request,
        body: PrepareLearnRequest,
    ) -> LearnEvidencePreview:
        """Build evidence locally and preview the exact model transfer."""
        from qwenpaw.app.agent_context import get_agent_for_request

        workspace = await get_agent_for_request(request)
        return await _run_learn(
            lambda: _learning_service(request).prepare(
                workspace_dir=Path(workspace.workspace_dir),
                agent_id=workspace.agent_id,
                recording_id=body.recording_id,
                goal=body.goal,
                confirmed_context=body.confirmed_context,
                selected_sequences=body.selected_sequences,
            ),
        )

    @recording_router.post("/learn/review", response_model=RecordingReview)
    async def review_recording_for_learn(
        request: Request,
        body: ReviewRecordingRequest,
    ) -> RecordingReview:
        """Return the local semantic event timeline without file paths."""
        from qwenpaw.app.agent_context import get_agent_for_request

        workspace = await get_agent_for_request(request)
        return await _run_learn(
            lambda: _learning_service(request).review(
                workspace_dir=Path(workspace.workspace_dir),
                agent_id=workspace.agent_id,
                recording_id=body.recording_id,
            ),
        )

    @recording_router.post(
        "/learn/generate",
        response_model=ReviewedSkillDraft,
    )
    async def generate_recording_skill_draft(
        request: Request,
        body: GenerateLearnRequest,
    ) -> ReviewedSkillDraft:
        """Consume explicit consent and create one grounded review draft."""
        from qwenpaw.app.agent_context import get_agent_for_request

        workspace = await get_agent_for_request(request)
        return await _run_learn(
            lambda: _learning_service(request).generate(
                workspace_dir=Path(workspace.workspace_dir),
                agent_id=workspace.agent_id,
                consent_token=body.consent_token,
            ),
        )

    @recording_router.get(
        "/learn/draft/{recording_id}",
        response_model=ReviewedSkillDraft | None,
    )
    async def recover_recording_skill_draft(
        request: Request,
        recording_id: UUID,
    ) -> ReviewedSkillDraft | None:
        """Recover an unexpired in-memory draft after a UI remount."""
        from qwenpaw.app.agent_context import get_agent_for_request

        workspace = await get_agent_for_request(request)
        return await _run_learn(
            lambda: _learning_service(request).recover_draft(
                workspace_dir=Path(workspace.workspace_dir),
                agent_id=workspace.agent_id,
                recording_id=recording_id,
            ),
        )

    @recording_router.post(
        "/learn/materialize",
        response_model=MaterializedSkill,
    )
    async def materialize_recording_skill(
        request: Request,
        body: MaterializeSkillRequest,
    ) -> MaterializedSkill:
        """Commit an explicitly approved draft and reload its owning Agent."""
        from qwenpaw.app.agent_context import get_agent_for_request

        workspace = await get_agent_for_request(request)
        result = await _run_learn(
            lambda: _learning_service(request).materialize(
                workspace_dir=Path(workspace.workspace_dir),
                agent_id=workspace.agent_id,
                draft_id=body.draft_id,
                name=body.name,
                content=body.content,
            ),
        )
        schedule_agent_reload(request, workspace.agent_id)
        return result.model_copy(update={"reload_scheduled": True})

    return recording_router


__all__ = [
    "build_router",
    "GenerateLearnRequest",
    "MaterializeSkillRequest",
    "PrepareLearnRequest",
    "ReviewRecordingRequest",
]
