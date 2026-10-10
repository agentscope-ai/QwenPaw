# -*- coding: utf-8 -*-
"""Workspace avatar identity for the single-user Console."""

from functools import lru_cache

from ...constant import WORKING_DIR
from ...user_assets.avatars import AvatarStore
from ...user_assets.avatar_routes import avatar_router


def avatar_owner() -> str:
    """Return a stable workspace identity after AuthMiddleware admission."""
    return "console"


@lru_cache(maxsize=1)
def avatar_store() -> AvatarStore:
    return AvatarStore(WORKING_DIR / "profile" / "avatars.sqlite3")


router = avatar_router(avatar_store, avatar_owner)
