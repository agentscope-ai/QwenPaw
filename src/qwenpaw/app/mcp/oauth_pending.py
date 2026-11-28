# -*- coding: utf-8 -*-
"""Private OAuth attempts; tokens never enter routing/status metadata."""

import time
from dataclasses import dataclass, field

from ...plugins._driver_management import CredentialOverlayGrant

TTL_SECONDS = 600
CANDIDATE_OWNER = "mcp-oauth-attempt"


@dataclass
class PendingAuthorization:
    overlay: CredentialOverlayGrant = field(repr=False)
    expected_credentials: dict[str, int | None] = field(repr=False)
    binding_token: str = field(repr=False)
    phase: str = "pending"
    retain_until: float = 0

    def finish(self, phase, now):
        self.phase = phase
        self.retain_until = now + TTL_SECONDS
        self.overlay.close()
        self.binding_token = ""


def attempts(request):
    state = request.app.state
    if not hasattr(state, "mcp_oauth_attempts"):
        state.mcp_oauth_attempts = {}
    return state.mcp_oauth_attempts


def purge(request, grants, now):
    saved = attempts(request)
    for key, attempt in tuple(saved.items()):
        if attempt.phase == "pending" and attempt.overlay.expires_at <= now:
            attempt.finish("expired", now)
            grants.pop(key, None)
        if attempt.phase != "pending" and attempt.retain_until <= now:
            saved.pop(key, None)


def candidate_meta(existing):
    return {
        **existing,
        "candidate_owner": CANDIDATE_OWNER,
        "candidate_expires_at": time.time() + TTL_SECONDS,
    }
