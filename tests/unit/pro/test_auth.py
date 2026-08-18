# -*- coding: utf-8 -*-
"""Tests for QwenPaw Pro users, roles, and token invalidation."""

from pathlib import Path

import pytest

from qwenpaw.pro.auth import ProAuthService
from qwenpaw.pro.credentials import TenantCredentialVault


def _auth_service(tmp_path: Path) -> ProAuthService:
    database = tmp_path / "control.db"
    vault = TenantCredentialVault(database, tmp_path / ".vault_key")
    return ProAuthService(database, vault)


def test_first_registration_bootstraps_admin_and_closes_registration(
    tmp_path: Path,
) -> None:
    auth = _auth_service(tmp_path)

    admin, token = auth.register("owner", "safe-password")

    assert admin.role == "admin"
    assert auth.verify_token(token) == admin
    assert auth.status()["registration_enabled"] is False
    with pytest.raises(PermissionError, match="Registration is disabled"):
        auth.register("second", "safe-password")


def test_role_or_disabled_change_invalidates_existing_token(
    tmp_path: Path,
) -> None:
    auth = _auth_service(tmp_path)
    auth.register("owner", "safe-password")
    user = auth.create_user(
        username="member",
        password="safe-password",
    )
    _, token = auth.authenticate("member", "safe-password")

    updated = auth.update_user(user.user_id, role="admin")

    assert updated.role == "admin"
    assert auth.verify_token(token) is None


def test_last_active_admin_cannot_be_disabled_or_demoted(
    tmp_path: Path,
) -> None:
    auth = _auth_service(tmp_path)
    admin, _ = auth.register("owner", "safe-password")

    with pytest.raises(ValueError, match="last active administrator"):
        auth.update_user(admin.user_id, disabled=True)
    with pytest.raises(ValueError, match="last active administrator"):
        auth.update_user(admin.user_id, role="user")
