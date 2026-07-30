# -*- coding: utf-8 -*-
"""Session-scoped controls for the Computer Use plugin page."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from qwenpaw.app.approvals import get_approval_service
from qwenpaw.app.computer_use import HostRuntimeProvider
from qwenpaw.security.tool_guard.approval import ApprovalDecision

from .access import (
    get_computer_use_access_store,
)

from .client import (
    is_computer_use_active,
    known_computer_use_sessions,
    stop_all_computer_use_turns,
    stop_computer_use_session,
)
from .feature_state import get_computer_use_feature_state


class SessionRequest(BaseModel):
    """A page action scoped to exactly one active conversation."""

    session_id: str = Field(min_length=1)


class FeatureToggleRequest(BaseModel):
    """A request to enable or disable the Computer Use feature."""

    enabled: bool
    session_id: str | None = None


class PersistentAccessRequest(BaseModel):
    """A request to revoke one installation-scoped grant."""

    canonical_app_id: str = Field(min_length=1)


class PendingDecisionRequest(SessionRequest):
    """A response to one pending native App approval."""

    request_id: str = Field(min_length=1)
    decision: Literal["deny", "session", "always"]


def _is_computer_use_pending(pending) -> bool:
    return pending.extra.get("source_type") == "computer_use_app_access"


def _pending_app(pending) -> tuple[str, str] | None:
    details = pending.extra.get("computer_use_app")
    if not isinstance(details, dict):
        return None
    canonical_app_id = str(details.get("canonical_app_id") or "").strip()
    display_name = str(details.get("display_name") or canonical_app_id).strip()
    if not canonical_app_id or not display_name:
        return None
    return canonical_app_id, display_name


async def _pending_for_session(session_id: str):
    pending = await get_approval_service().list_pending_by_session(session_id)
    return [item for item in pending if _is_computer_use_pending(item)]


def build_router() -> APIRouter:
    """Build routes that do not acquire or start the native runtime."""
    router = APIRouter()

    @router.get("/status")
    def get_status() -> dict[str, bool | str]:
        capability = HostRuntimeProvider.get_capability()
        return {
            "runtime_available": HostRuntimeProvider.is_available(),
            "connection_active": capability is not None,
            "approval_scope": "session_and_persistent",
            "enabled": get_computer_use_feature_state().is_enabled(),
        }

    @router.post("/feature")
    async def set_feature_enabled(
        request: FeatureToggleRequest,
    ) -> dict[str, int | bool]:
        get_computer_use_feature_state().set_enabled(request.enabled)
        if request.enabled:
            return {"enabled": True}
        # Off is a kill switch for every agent, so every session waiting on an
        # approval has to be refused -- not just the one the caller named. A
        # session left waiting would otherwise be granted access later and act
        # on a desktop the user had already switched the feature off for.
        #
        # Denying comes before stopping, for the reason given on /session/stop.
        sessions = set(known_computer_use_sessions())
        if request.session_id:
            sessions.add(request.session_id)
        denied = 0
        for session_id in sorted(sessions):
            denied += await _deny_pending(session_id)
        stopped = await stop_all_computer_use_turns()
        return {"enabled": False, "stopped": stopped, "denied": denied}

    @router.get("/access")
    def list_persistent_access() -> dict[str, list[dict[str, str]]]:
        access = get_computer_use_access_store().list_persistent()
        return {
            "access": [
                {
                    "canonical_app_id": item.canonical_app_id,
                    "display_name": item.display_name,
                }
                for item in access
            ],
        }

    @router.delete("/access")
    def revoke_persistent_access(
        request: PersistentAccessRequest,
    ) -> dict[str, bool]:
        return {
            "revoked": get_computer_use_access_store().revoke_persistent(
                request.canonical_app_id,
            ),
        }

    @router.get("/session")
    async def get_session_state(
        session_id: str = Query(min_length=1),
    ) -> dict[str, bool]:
        return {"automation_active": is_computer_use_active(session_id)}

    @router.post("/session/stop")
    async def stop_automation(
        request: SessionRequest,
    ) -> dict[str, int | bool]:
        # Deny first, then stop. A pending approval is a wait the helper is
        # sitting in, and denying it is what ends that wait -- so it has to
        # happen before anything that waits on the action itself, or the
        # release would be queued behind the thing it releases.
        denied = await _deny_pending(request.session_id)
        stopped = await stop_computer_use_session(request.session_id)
        return {"stopped": stopped, "denied": denied}

    async def _deny_pending(session_id: str) -> int:
        """Refuse every approval this session is waiting on."""
        service = get_approval_service()
        denied = 0
        for pending in await _pending_for_session(session_id):
            resolved = await service.resolve_request(
                pending.request_id,
                ApprovalDecision.DENIED,
            )
            denied += int(resolved is not None)
        return denied

    @router.post("/session/pending/decision")
    async def decide_pending(
        request: PendingDecisionRequest,
    ) -> dict[str, bool | str]:
        pending = await get_approval_service().get_request(request.request_id)
        if (
            pending is None
            or pending.session_id != request.session_id
            or not _is_computer_use_pending(pending)
        ):
            raise HTTPException(
                status_code=404,
                detail="Pending approval not found.",
            )
        decision = (
            ApprovalDecision.DENIED
            if request.decision == "deny"
            else ApprovalDecision.APPROVED
        )
        app = _pending_app(pending)
        access_store = get_computer_use_access_store()
        if request.decision == "always":
            if app is None:
                raise HTTPException(
                    status_code=400,
                    detail="Pending application is invalid.",
                )
            access_store.record_persistent(*app)
        resolved = await get_approval_service().resolve_request(
            request.request_id,
            decision,
        )
        if (
            resolved is None
            and request.decision == "always"
            and app is not None
        ):
            access_store.revoke_persistent(app[0])
        return {
            "resolved": resolved is not None,
            "decision": request.decision,
        }

    return router
