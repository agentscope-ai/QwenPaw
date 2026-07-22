# -*- coding: utf-8 -*-
"""External ACL checker that evaluates NocoBase permissions."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from .permission_store import PermissionStore

logger = logging.getLogger(__name__)


AclResult = Optional[str]
AclChecker = Callable[[str, str, dict], AclResult]

# Channels that fail closed: when the integration is enabled, a sender that is
# not a known NocoBase user is denied instead of falling through. The console
# is the QwenPaw web UI whose caller identity is the authenticated login user;
# requiring a matching NocoBase account enforces "no NocoBase login, no
# access".
FAIL_CLOSED_CHANNELS = frozenset({"console"})


def build_checker(
    store: PermissionStore,
    is_enabled: Callable[[], bool],
) -> AclChecker:
    """Return a checker callable for BaseChannel._external_acl_checkers.

    The checker receives (channel_key, sender_id, meta) and returns:
      - "allow": user is permitted by NocoBase.
      - "deny":  user is explicitly denied by NocoBase, or — on a fail-closed
                 channel while the integration is enabled — the sender is not a
                 known NocoBase user.
      - None:    no NocoBase opinion; fall through to native ACL.

    Args:
        store: The permission cache synced from NocoBase.
        is_enabled: Callable returning whether the integration is currently
            enabled. Used to scope fail-closed enforcement so a disabled
            plugin never blocks anyone.
    """

    def _safe_enabled() -> bool:
        try:
            return bool(is_enabled())
        except Exception as exc:
            logger.warning("NocoBase enabled-state check failed: %s", exc)
            return False

    def _known_user(sender_id: str) -> bool:
        try:
            return store.is_known_user(sender_id)
        except Exception as exc:
            logger.warning("NocoBase known-user check failed: %s", exc)
            return False

    def checker(
        channel_key: str,
        sender_id: str,
        _meta: dict,
    ) -> AclResult:
        # Fail-closed only on designated channels while enabled.
        fail_closed = channel_key in FAIL_CLOSED_CHANNELS and _safe_enabled()

        # No identity: "not logged in" -> deny on a fail-closed channel.
        if not sender_id:
            return "deny" if fail_closed else None

        try:
            result = store.is_channel_allowed(sender_id, channel_key)
        except Exception as exc:
            logger.warning("NocoBase ACL check failed: %s", exc)
            return None

        # Explicit allow / deny from a role mapping.
        if result is not None:
            return "allow" if result else "deny"

        # No explicit opinion. On a fail-closed channel, a known (logged-in)
        # NocoBase user is allowed and an unknown sender is denied.
        if not fail_closed:
            return None
        return "allow" if _known_user(sender_id) else "deny"

    return checker
