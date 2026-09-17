# -*- coding: utf-8 -*-
"""多用户身份启动迁移。"""

from __future__ import annotations

from collections.abc import Callable

from .models import LegacyAdminCredential, UserRecord
from .runtime import IdentityRuntime


async def migrate_legacy_admin_if_needed(
    auth_data_loader: Callable[[], object],
    runtime: IdentityRuntime,
) -> UserRecord | None:
    """只提取旧密码凭据，并由 Repository 原子判断空库。"""
    auth_data = auth_data_loader()
    if isinstance(auth_data, dict) and auth_data.get("_auth_load_error"):
        return None
    legacy = LegacyAdminCredential.from_auth_data(auth_data)
    if legacy is None:
        return None
    return await runtime.users.migrate_legacy_admin(legacy)
