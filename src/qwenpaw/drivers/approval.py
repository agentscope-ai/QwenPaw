# -*- coding: utf-8 -*-
"""Driver approval boundary contracts."""

from __future__ import annotations

from typing import Protocol

from .policy import DriverInvocationContext


class ApprovalGate(Protocol):
    """Application-provided gate for Driver policy approvals.

    Driver core owns policy evaluation, but it does not know how a concrete
    product asks a human for approval.  The application shell injects this
    boundary when it wants ``ask`` policy effects to pause and resume.
    """

    async def request_approval(
        self,
        context: DriverInvocationContext,
    ) -> None:
        """Block until the app-level approval flow approves or denies."""
