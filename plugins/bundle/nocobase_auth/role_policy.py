# -*- coding: utf-8 -*-
"""Pure evaluation of the NocoBase role→channel access policy."""
from __future__ import annotations

from typing import List, Optional

from .config import RoleChannelMapping


def evaluate_role_channel(
    roles: List[str],
    channel_key: str,
    mappings: List[RoleChannelMapping],
) -> Optional[bool]:
    """Return an access opinion for ``channel_key`` given the caller's roles.

    - Any matching role denies the channel -> ``False`` (deny wins).
    - Else any matching role allows the channel -> ``True``.
    - No mapping mentions the channel for these roles -> ``None`` (no opinion).
    """
    role_set = set(roles or [])
    allowed = False
    denied = False
    for mapping in mappings:
        if mapping.role_name not in role_set:
            continue
        if channel_key in mapping.denied_channels:
            denied = True
        if channel_key in mapping.allowed_channels:
            allowed = True
    if denied:
        return False
    if allowed:
        return True
    return None
