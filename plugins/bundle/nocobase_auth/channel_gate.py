# -*- coding: utf-8 -*-
"""External ACL checker that evaluates NocoBase permissions."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from .permission_store import PermissionStore

logger = logging.getLogger(__name__)


AclResult = Optional[str]
AclChecker = Callable[[str, str, dict], AclResult]


def build_checker(store: PermissionStore) -> AclChecker:
    """Return a checker callable for BaseChannel._external_acl_checkers.

    The checker receives (channel_key, sender_id, meta) and returns:
      - "allow": user is permitted by NocoBase.
      - "deny":  user is explicitly denied by NocoBase.
      - None:    user not known or NocoBase not configured; fall through.
    """

    def checker(
        channel_key: str,
        sender_id: str,
        _meta: dict,
    ) -> AclResult:
        if not sender_id:
            return None

        try:
            result = store.is_channel_allowed(sender_id, channel_key)
        except Exception as exc:
            logger.warning("NocoBase ACL check failed: %s", exc)
            return None

        if result is True:
            return "allow"
        if result is False:
            return "deny"
        return None

    return checker
