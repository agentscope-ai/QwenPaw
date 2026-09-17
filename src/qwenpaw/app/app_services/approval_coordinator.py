# -*- coding: utf-8 -*-
"""Façade over the existing ``ApprovalService`` singleton.

A thin pass-through that lets callers use
``ctx.app_services.approval_coordinator`` *without* changing behavior.
The wrapper is the future seam where cross-workspace approval
orchestration will land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..approvals.service import ApprovalService


class ApprovalCoordinator:
    """Wrap one ``ApprovalService`` instance and forward all attribute access.

    The default constructor binds to the process-wide singleton so the
    transitional period keeps behaving like today. Tests (and the future
    lifespan-managed instance) inject their own service explicitly.
    """

    def __init__(self, service: "ApprovalService | None" = None) -> None:
        if service is None:
            from ..approvals.service import get_approval_service

            service = get_approval_service()
        self._svc = service

    @property
    def service(self) -> "ApprovalService":
        """Expose the underlying service.

        Escape hatch for code that needs the concrete type.
        """
        return self._svc

    def __getattr__(self, name: str) -> Any:
        """Forward every undefined attribute to the wrapped service."""
        return getattr(self._svc, name)


__all__ = ["ApprovalCoordinator"]
