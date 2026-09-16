# -*- coding: utf-8 -*-
"""多用户启动只迁移旧管理员凭据，不迁移旧令牌。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.identity.bootstrap import migrate_legacy_admin_if_needed


class FakeUsers:
    def __init__(self) -> None:
        self.migrated = None

    async def migrate_legacy_admin(self, legacy):
        self.migrated = legacy
        return SimpleNamespace(username=legacy.username)


@pytest.mark.asyncio
async def test_bootstrap_extracts_only_legacy_password_credential() -> None:
    users = FakeUsers()
    auth_data = {
        "user": {
            "username": "legacy-admin",
            "password_hash": "a" * 64,
            "password_salt": "b" * 32,
        },
        "jwt_secret": "must-not-migrate",
        "revoked_tokens": ["must-not-migrate"],
    }

    migrated = await migrate_legacy_admin_if_needed(
        lambda: auth_data,
        SimpleNamespace(users=users),
    )

    assert migrated is not None
    assert users.migrated.username == "legacy-admin"
    assert not hasattr(users.migrated, "jwt_secret")


@pytest.mark.asyncio
async def test_bootstrap_ignores_missing_or_invalid_legacy_data() -> None:
    users = FakeUsers()
    runtime = SimpleNamespace(users=users)
    assert await migrate_legacy_admin_if_needed(lambda: {}, runtime) is None
    assert (
        await migrate_legacy_admin_if_needed(
            lambda: {"_auth_load_error": True}, runtime
        )
        is None
    )
    assert users.migrated is None
