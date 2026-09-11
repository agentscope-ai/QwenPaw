# -*- coding: utf-8 -*-
"""Tests for QwenPaw Hub users, roles, and token invalidation."""

import sqlite3
from pathlib import Path

import pytest

from qwenpaw.hub.auth import HubAuthService
from qwenpaw.hub.credentials import TenantCredentialVault


def _auth_service(tmp_path: Path) -> HubAuthService:
    database = tmp_path / "control.db"
    vault = TenantCredentialVault(database, tmp_path / ".vault_key")
    return HubAuthService(database, vault)


def test_first_registration_bootstraps_admin_and_closes_registration(
    tmp_path: Path,
) -> None:
    auth = _auth_service(tmp_path)

    admin, token = auth.register("owner", "safe-password")

    assert admin.role == "admin"
    assert auth.has_enabled_admin() is True
    assert auth.verify_token(token) == admin
    assert auth.status()["registration_enabled"] is False
    with sqlite3.connect(tmp_path / "control.db") as connection:
        tenant = connection.execute(
            "SELECT tenant_type FROM hub_tenants WHERE tenant_id = ?",
            (f"personal-{admin.user_id}",),
        ).fetchone()
    assert tenant == ("personal",)
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


def test_administrator_cannot_change_own_authorization(
    tmp_path: Path,
) -> None:
    auth = _auth_service(tmp_path)
    owner, _ = auth.register("owner", "safe-password")
    second = auth.create_user(
        username="second-admin",
        password="safe-password",
        role="admin",
    )

    with pytest.raises(ValueError, match="cannot change their own"):
        auth.update_user(
            owner.user_id,
            role="user",
            actor_user_id=owner.user_id,
        )
    with pytest.raises(ValueError, match="cannot change their own"):
        auth.update_user(
            owner.user_id,
            disabled=True,
            actor_user_id=owner.user_id,
        )

    updated = auth.update_user(
        second.user_id,
        role="user",
        actor_user_id=owner.user_id,
    )
    assert updated.role == "user"
    assert auth.get_user(owner.user_id) == owner


def test_user_pages_filter_without_loading_all_accounts(
    tmp_path: Path,
) -> None:
    auth = _auth_service(tmp_path)
    auth.register("owner", "safe-password")
    for index in range(5):
        auth.create_user(
            username=f"member-{index}",
            password="safe-password",
            role="admin" if index == 4 else "user",
        )

    users, total = auth.list_users_page(page=2, page_size=2)
    admins, admin_total = auth.list_users_page(
        page=1,
        page_size=10,
        query="member",
        role="admin",
    )

    assert total == 6
    assert len(users) == 2
    assert admin_total == 1
    assert admins[0].username == "member-4"


def test_usernames_are_loaded_in_one_batch(tmp_path: Path) -> None:
    auth = _auth_service(tmp_path)
    owner, _ = auth.register("owner", "safe-password")
    member = auth.create_user(
        username="member",
        password="safe-password",
    )

    usernames = auth.get_usernames(
        {owner.user_id, member.user_id, "missing-user"},
    )

    assert usernames == {
        owner.user_id: "owner",
        member.user_id: "member",
    }


def test_change_password_rotates_token_and_preserves_username(
    tmp_path: Path,
) -> None:
    auth = _auth_service(tmp_path)
    user, old_token = auth.register("owner", "safe-password")

    updated = auth.change_password(user.user_id, "new-safe-password")
    new_token = auth.create_token(updated)

    assert updated.username == "owner"
    assert auth.verify_token(old_token) is None
    assert auth.verify_token(new_token).user_id == user.user_id
    with pytest.raises(PermissionError, match="Invalid username or password"):
        auth.authenticate("owner", "safe-password")
    assert auth.authenticate("owner", "new-safe-password")[0].user_id == (
        user.user_id
    )
