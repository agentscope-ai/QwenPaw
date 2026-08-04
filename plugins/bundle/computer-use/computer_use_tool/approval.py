# -*- coding: utf-8 -*-
"""Translate native App approval requests into the Core approval service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qwenpaw.app.approvals import ApprovalRequestSummary, get_approval_service
from qwenpaw.config.context import (
    get_current_session_id as get_tool_session_id,
)
from qwenpaw.constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
from qwenpaw.security.tool_guard.approval import ApprovalDecision

from .access import (
    AppApprovalRequest,
    get_computer_use_access_store,
)


def _agent_context():
    """Load request-scoped context only while resolving an approval."""
    from qwenpaw.app import agent_context

    return agent_context


class ComputerUseApprovalCoordinator:
    """The plugin-side adapter for native-originated App approval events.

    Holds no state: the recency guard on the helper no longer takes a
    post-approval exemption, so there is nothing to arm here. An action issued
    right after an approval is refused as retryable ``user_intervention`` and
    succeeds once the caller observes again and reissues.
    """

    async def decide(self, message: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve one reverse approval request without widening its scope."""
        request = self._app_request(message)
        if request is None:
            return {"allowed": False, "source": "invalid"}
        if not self._matches_active_session(request):
            return {"allowed": False, "source": "session_mismatch"}

        store = get_computer_use_access_store()
        existing = store.resolve(request)
        if existing is not None:
            return {"allowed": existing.allowed, "source": existing.source}

        pending = await self._create_pending(request)
        try:
            decision = await get_approval_service().wait_for_approval(
                pending.request_id,
                TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001 - approval failures deny by default
            decision = ApprovalDecision.DENIED
        allowed = decision == ApprovalDecision.APPROVED
        store.record_session(request, allowed=allowed)
        return {"allowed": allowed, "source": "session"}

    @staticmethod
    def _matches_active_session(request: AppApprovalRequest) -> bool:
        agent_context = _agent_context()
        active_session = (
            agent_context.get_current_session_id()
            or get_tool_session_id()
            or ""
        )
        return bool(active_session and active_session == request.session_id)

    @staticmethod
    def _app_request(message: Mapping[str, Any]) -> AppApprovalRequest | None:
        params = message.get("params")
        meta = message.get("meta")
        if not isinstance(params, Mapping) or not isinstance(meta, Mapping):
            return None
        app_id = str(params.get("canonical_app_id") or "").strip()
        session_id = str(meta.get("session_id") or "").strip()
        request_id = str(message.get("request_id") or "").strip()
        evidence = params.get("identity_evidence")
        if (
            not app_id
            or not session_id
            or not request_id
            or not isinstance(evidence, Mapping)
        ):
            return None
        return AppApprovalRequest(
            request_id=request_id,
            session_id=session_id,
            canonical_app_id=app_id,
            display_name=str(params.get("display_name") or app_id),
            identity_evidence={
                str(key): str(value) for key, value in evidence.items()
            },
            risk=str(params.get("risk") or "unknown"),
            warning=str(params.get("warning") or ""),
        )

    @staticmethod
    async def _create_pending(request: AppApprovalRequest):
        agent_context = _agent_context()
        current_session = (
            agent_context.get_current_session_id() or request.session_id
        )
        root_session = (
            agent_context.get_current_root_session_id() or current_session
        )
        agent_id = agent_context.get_current_agent_id() or "unknown"
        summary = (
            f"Computer Use requests access to {request.display_name} "
            "for this session."
        )
        return await get_approval_service().create_pending_summary(
            session_id=current_session,
            root_session_id=root_session,
            owner_agent_id=agent_id,
            user_id=agent_context.get_current_user_id() or "",
            channel=agent_context.get_current_channel() or "",
            agent_id=agent_id,
            summary=ApprovalRequestSummary(
                source_type="computer_use_app_access",
                name="Computer Use",
                severity="medium",
                findings_count=1,
                result_summary=summary,
                payload={
                    "canonical_app_id": request.canonical_app_id,
                    "display_name": request.display_name,
                    "risk": request.risk,
                },
            ),
            timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
            extra={
                "display": {
                    "tool_name": "Computer Use",
                    "tool_source": "app access",
                    "exact_target": f"{request.display_name} for this session",
                    "is_generalized": False,
                },
                "tool_call": {
                    "id": f"computer_use:{request.request_id}",
                    "name": "Computer Use",
                    "input": {
                        "canonical_app_id": request.canonical_app_id,
                        "display_name": request.display_name,
                        "risk": request.risk,
                        "warning": request.warning,
                    },
                },
                "computer_use_app": {
                    "canonical_app_id": request.canonical_app_id,
                    "display_name": request.display_name,
                },
            },
        )
