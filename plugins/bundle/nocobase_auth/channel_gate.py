# -*- coding: utf-8 -*-
"""External ACL checker that evaluates NocoBase role→channel policy live."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from .config import NocoBaseAuthConfig
from .role_policy import evaluate_role_channel

logger = logging.getLogger(__name__)


AclResult = Optional[str]
AclChecker = Callable[[str, str, dict], AclResult]

# Channels that fail closed: when the integration is enabled, a request with no
# resolved NocoBase identity is denied instead of falling through. The console
# is the QwenPaw web UI whose caller identity is the authenticated login user;
# requiring a resolved NocoBase identity enforces "no NocoBase login, no
# access".
FAIL_CLOSED_CHANNELS = frozenset({"console"})


def build_checker(
    get_config: Callable[[], NocoBaseAuthConfig],
    is_enabled: Callable[[], bool],
) -> AclChecker:
    """Return a checker callable for BaseChannel._external_acl_checkers.

    The checker receives (channel_key, sender_id, meta) and returns:
      - "allow": permitted (explicit role allow, or authenticated user on a
                 fail-closed channel with no explicit opinion).
      - "deny":  explicit role deny, or — on a fail-closed channel while the
                 integration is enabled — no resolved identity.
      - None:    no opinion; fall through to native ACL.

    Roles are read from ``meta['acl_roles']`` (injected by the HTTP layer from
    the live-resolved identity). ``role_channel_map`` comes from config.
    """

    def _safe_enabled() -> bool:
        try:
            return bool(is_enabled())
        except Exception as exc:
            logger.warning("NocoBase enabled-state check failed: %s", exc)
            return False

    def checker(
        channel_key: str,
        sender_id: str,
        meta: dict,
    ) -> AclResult:
        fail_closed = channel_key in FAIL_CLOSED_CHANNELS and _safe_enabled()

        # No identity: "not logged in" -> deny on a fail-closed channel.
        if not sender_id:
            return "deny" if fail_closed else None

        roles = meta.get("acl_roles") if isinstance(meta, dict) else None
        if not isinstance(roles, list):
            roles = []

        try:
            mappings = get_config().role_channel_map
            result = evaluate_role_channel(roles, channel_key, mappings)
        except Exception as exc:
            logger.warning("NocoBase ACL evaluation failed: %s", exc)
            return None

        if result is not None:
            return "allow" if result else "deny"

        # No explicit opinion. On a fail-closed channel, an authenticated
        # (identity present) NocoBase user is allowed.
        if not fail_closed:
            return None
        return "allow"

    return checker
