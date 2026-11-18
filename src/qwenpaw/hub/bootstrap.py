# -*- coding: utf-8 -*-
"""Lightweight local bootstrap helpers for QwenPaw Hub."""

from __future__ import annotations

import os
from pathlib import Path

from ..constant import WORKING_DIR
from .auth import HubAuthService, HubUser
from .credentials import TenantCredentialVault


def get_hub_root() -> Path:
    """Resolve the Hub data root without loading runtime provisioners."""
    configured = os.environ.get("QWENPAW_HUB_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (WORKING_DIR / "hub").resolve()


def _auth_service() -> HubAuthService:
    """Build the lightweight authentication service for the Hub data root."""
    root_dir = get_hub_root()
    database_path = root_dir / "control.db"
    credential_vault = TenantCredentialVault(
        database_path,
        root_dir / "secrets" / ".vault_key",
    )
    return HubAuthService(
        database_path,
        credential_vault,
    )


def ensure_admin_initialization_available() -> None:
    """Reject local initialization before requesting a password."""
    if _auth_service().user_count() > 0:
        raise PermissionError("Hub is already initialized.")


def initialize_hub_admin(username: str, password: str) -> HubUser:
    """Initialize the first administrator without runtime provisioners."""
    return _auth_service().initialize_admin(username, password)
