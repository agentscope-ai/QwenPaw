# -*- coding: utf-8 -*-
"""Encrypted local storage for OAuth provider credentials."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ...constant import SECRET_DIR
from ...security.secret_store import decrypt_dict_fields, encrypt_dict_fields
from .models import OAuthCredential

logger = logging.getLogger(__name__)

ProviderCredentialType = Literal["builtin", "plugin", "custom"]

OAUTH_SECRET_FIELDS = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
    },
)


class OAuthCredentialStore:
    """Persist OAuth credentials next to provider config directories."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            Path(root) if root is not None else (SECRET_DIR / "providers")
        )

    def save(
        self,
        credential: OAuthCredential,
        provider_type: ProviderCredentialType,
    ) -> None:
        """Save a credential with sensitive fields encrypted."""
        if not credential.access_token:
            raise ValueError(
                "Cannot save OAuth credential without access token",
            )

        provider_dir = self.root / provider_type
        provider_dir.mkdir(parents=True, exist_ok=True)
        self._chmod_best_effort(provider_dir, 0o700)

        data = credential.model_dump()
        data["version"] = 1
        encrypted = encrypt_dict_fields(data, OAUTH_SECRET_FIELDS)
        path = self._path_for(credential.provider_id, provider_type)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(encrypted, f, ensure_ascii=False, indent=2)
        self._chmod_best_effort(path, 0o600)

    def load(
        self,
        provider_id: str,
        provider_type: ProviderCredentialType,
    ) -> OAuthCredential | None:
        """Load and decrypt a credential, returning ``None`` on corruption."""
        path = self._path_for(provider_id, provider_type)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Credential file is not a JSON object")
            data.pop("version", None)
            decrypted = decrypt_dict_fields(data, OAUTH_SECRET_FIELDS)
            for field in OAUTH_SECRET_FIELDS:
                value = decrypted.get(field)
                if isinstance(value, str) and value.startswith("ENC:"):
                    raise ValueError(f"Failed to decrypt field '{field}'")
            return OAuthCredential.model_validate(decrypted)
        except (
            json.JSONDecodeError,
            OSError,
            ValueError,
            ValidationError,
        ) as exc:
            logger.warning(
                "Failed to load OAuth credential for provider '%s'; "
                "ignoring unreadable or invalid credential file: %s",
                provider_id,
                exc,
                exc_info=True,
            )
            return None

    def delete(
        self,
        provider_id: str,
        provider_type: ProviderCredentialType,
    ) -> None:
        """Delete a credential if it exists."""
        try:
            self._path_for(provider_id, provider_type).unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning(
                "Failed to delete OAuth credential for provider '%s'; "
                "ignoring cleanup error: %s",
                provider_id,
                exc,
                exc_info=True,
            )

    def exists(
        self,
        provider_id: str,
        provider_type: ProviderCredentialType,
    ) -> bool:
        """Return whether a credential file exists."""
        return self._path_for(provider_id, provider_type).exists()

    def _path_for(
        self,
        provider_id: str,
        provider_type: ProviderCredentialType,
    ) -> Path:
        return self.root / provider_type / f"{provider_id}_oauth.json"

    @staticmethod
    def _chmod_best_effort(path: Path, mode: int) -> None:
        try:
            os.chmod(path, mode)
        except OSError:
            pass
