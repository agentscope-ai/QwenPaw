# -*- coding: utf-8 -*-
"""Pydantic configuration model for the NocoBase auth plugin."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from qwenpaw.constant import WORKING_DIR
from qwenpaw.security.secret_store import decrypt, encrypt, is_encrypted

logger = logging.getLogger(__name__)

CONFIG_FILE = "nocobase_auth_config.json"

# Hostnames that must never be the NocoBase target — currently just the
# cloud metadata endpoint by name (its IP, 169.254.169.254, is also caught
# as link-local below).  QwenPaw is self-hosted, so loopback / LAN targets
# (localhost, 192.168.x, 10.x, …) are legitimate and intentionally allowed.
_BLOCKED_HOSTNAMES = {"metadata.google.internal"}


def validate_base_url(value: str) -> str:
    """Validate and normalise a NocoBase base URL.

    Empty values are allowed (integration simply stays unconfigured).  When
    set, the URL must use http/https.  Because QwenPaw is self-hosted and the
    admin configures their own NocoBase, loopback and private/LAN addresses
    are permitted; we only reject link-local (incl. the cloud metadata
    endpoint), multicast, reserved, and unspecified addresses as a light
    SSRF guard, since the server fetches this URL with redirects followed.
    """
    if not value:
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must use http or https")
    host = parsed.hostname
    if not host:
        raise ValueError("base_url must include a host")
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise ValueError(f"base_url host '{host}' is not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError(
            f"base_url host '{host}' resolves to a disallowed address range",
        )
    return value


class RoleChannelMapping(BaseModel):
    """Maps a NocoBase role to allowed/denied QwenPaw channels."""

    role_name: str = Field(..., description="NocoBase role name")
    allowed_channels: List[str] = Field(
        default_factory=list,
        description="Channel keys this role may use",
    )
    denied_channels: List[str] = Field(
        default_factory=list,
        description="Channel keys this role is explicitly blocked from",
    )


class NocoBaseAuthConfig(BaseModel):
    """Runtime configuration persisted per workspace/agent.

    The ``api_token`` is encrypted at rest using the keyring-backed secret
    store's Fernet helper.  Plain text tokens are accepted on input (e.g. from
    the console) and are converted to ``ENC:...`` ciphertext on serialization.
    """

    enabled: bool = Field(default=False, description="Enable NocoBase ACL")
    base_url: str = Field(default="", description="NocoBase base URL")
    api_token: str = Field(default="", description="NocoBase API token")
    user_id_field: str = Field(
        default="email",
        description="NocoBase user field to use as channel sender_id",
    )
    role_channel_map: List[RoleChannelMapping] = Field(
        default_factory=list,
        description="Mapping of NocoBase roles to channel access",
    )

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        return validate_base_url(value)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict for JSON storage.

        The API token is encrypted before being written to disk.
        """
        data = self.model_dump()
        token = data.get("api_token", "")
        if token:
            data["api_token"] = encrypt(token)
        return data

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "NocoBaseAuthConfig":
        """Deserialize from plain dict, tolerating missing keys.

        Decrypts the API token if it was persisted as ciphertext.
        """
        if not data:
            return cls()
        token = data.get("api_token", "")
        if token and is_encrypted(token):
            token = decrypt(token)
        data = {**data, "api_token": token}
        return cls(**data)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "NocoBaseAuthConfig":
        """Load configuration from disk."""
        target = path or WORKING_DIR / CONFIG_FILE
        if not target.exists():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            return cls.from_dict(raw)
        except Exception:
            logger.exception("Failed to load config from %s", target)
            return cls()

    def save(self, path: Optional[Path] = None) -> None:
        """Save configuration to disk."""
        target = path or WORKING_DIR / CONFIG_FILE
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
        except Exception:
            logger.exception("Failed to save config to %s", target)
