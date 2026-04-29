# -*- coding: utf-8 -*-
"""Encrypted on-disk persistence for OAuth access tokens.

Only the *long-lived* OAuth access token is persisted.  The short-lived
Copilot API token is always re-fetched from GitHub on startup.

The on-disk JSON layout is::

    {
        "oauth_access_token": "ENC:...",   # encrypted via secret_store
        "github_login":       "octocat",
        "saved_at":           1714123456
    }

File mode is restricted to ``0o600`` on POSIX systems.  On Windows the
chmod call is best-effort and silently ignored.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from qwenpaw.security.secret_store import (
    PROVIDER_SECRET_FIELDS,
    decrypt_dict_fields,
    encrypt_dict_fields,
)

logger = logging.getLogger(__name__)


def _resolve_default_path(provider_id: str) -> Path:
    """Lazy lookup so tests can monkeypatch ``SECRET_DIR`` after import."""
    from qwenpaw.constant import SECRET_DIR  # local import on purpose

    return SECRET_DIR / "providers" / "oauth" / f"{provider_id}.json"


class CopilotTokenStore:
    """Encrypted on-disk persistence for the GitHub OAuth access token."""

    def __init__(
        self,
        provider_id: str = "github-copilot",
        path: Optional[Path] = None,
    ) -> None:
        self.provider_id = provider_id
        self._explicit_path = path

    @property
    def path(self) -> Path:
        if self._explicit_path is not None:
            return self._explicit_path
        return _resolve_default_path(self.provider_id)

    def save(self, oauth_access_token: str, github_login: str = "") -> None:
        """Persist the OAuth access token (encrypted)."""
        if not oauth_access_token:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = encrypt_dict_fields(
                {
                    "oauth_access_token": oauth_access_token,
                    "github_login": github_login,
                    "saved_at": int(time.time()),
                },
                PROVIDER_SECRET_FIELDS,
            )
            with open(self.path, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                # Non-POSIX FS (Windows / NTFS): best-effort
                pass
            logger.info(
                "Persisted Copilot OAuth token to %s",
                self.path,
            )
        except OSError as exc:
            logger.warning(
                "Failed to persist Copilot OAuth token at %s: %s",
                self.path,
                exc,
            )

    def load(self) -> Optional[dict]:
        """Load the persisted OAuth payload, decrypted.

        Returns ``None`` when the file is missing or unreadable.  The
        returned dict has keys ``oauth_access_token``, ``github_login``,
        ``saved_at``.
        """
        if not self.path.exists():
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            data = decrypt_dict_fields(data, PROVIDER_SECRET_FIELDS)
            token = data.get("oauth_access_token") or ""
            if not token:
                logger.warning(
                    "Copilot OAuth token file %s is empty/malformed",
                    self.path,
                )
                return None
            return {
                "oauth_access_token": token,
                "github_login": data.get("github_login", ""),
                "saved_at": int(data.get("saved_at", 0) or 0),
            }
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Failed to load Copilot OAuth token from %s: %s",
                self.path,
                exc,
            )
            return None

    def delete(self) -> None:
        """Remove the persisted token file (idempotent)."""
        try:
            self.path.unlink(missing_ok=True)
            logger.info("Deleted Copilot OAuth token at %s", self.path)
        except OSError as exc:
            logger.warning(
                "Failed to delete Copilot OAuth token at %s: %s",
                self.path,
                exc,
            )
