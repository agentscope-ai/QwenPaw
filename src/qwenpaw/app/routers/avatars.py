# -*- coding: utf-8 -*-
"""Workspace avatar identity for the single-user Console."""

from functools import lru_cache

from fastapi import HTTPException, Request

from ...constant import WORKING_DIR
from ...user_assets.avatars import AvatarStore
from ...user_assets.avatar_routes import avatar_router
from ..auth import is_auth_enabled, verify_token


def avatar_owner(request: Request) -> str:
    """Protect workspace identity even after the username changes."""
    if is_auth_enabled():
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if not token or verify_token(token) is None:
            raise HTTPException(401, "Not authenticated")
    return "console"


@lru_cache(maxsize=1)
def avatar_store() -> AvatarStore:
    return AvatarStore(WORKING_DIR / "profile" / "avatars.sqlite3")


router = avatar_router(avatar_store, avatar_owner)
