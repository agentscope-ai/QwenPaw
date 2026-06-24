# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for the NocoBase auth plugin configuration."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from nocobase_auth.config import NocoBaseAuthConfig
from qwenpaw.security.secret_store import decrypt, encrypt, is_encrypted


@pytest.fixture
def config_path() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "config.json"


def test_api_token_encrypted_on_save(config_path: Path) -> None:
    config = NocoBaseAuthConfig(
        enabled=True,
        base_url="https://nocobase.test",
        api_token="super-secret-token",
        user_id_field="email",
    )
    config.save(config_path)

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert is_encrypted(raw["api_token"])
    assert decrypt(raw["api_token"]) == "super-secret-token"


def test_api_token_decrypted_on_load(config_path: Path) -> None:
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "base_url": "https://nocobase.test",
                "api_token": encrypt("super-secret-token"),
                "user_id_field": "email",
                "role_channel_map": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = NocoBaseAuthConfig.load(config_path)
    assert loaded.api_token == "super-secret-token"


def test_empty_token_roundtrip(config_path: Path) -> None:
    config = NocoBaseAuthConfig(enabled=False)
    config.save(config_path)

    loaded = NocoBaseAuthConfig.load(config_path)
    assert loaded.api_token == ""


def test_to_dict_excludes_plaintext_token() -> None:
    config = NocoBaseAuthConfig(api_token="plain-token")
    data = config.to_dict()
    assert is_encrypted(data["api_token"])
    assert decrypt(data["api_token"]) == "plain-token"


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX file mode bits do not apply on Windows",
)
def test_saved_config_is_owner_only(config_path: Path) -> None:
    config = NocoBaseAuthConfig(
        enabled=True,
        base_url="https://nocobase.test",
        api_token="super-secret-token",
    )
    config.save(config_path)

    mode = stat.S_IMODE(os.stat(config_path).st_mode)
    assert mode == 0o600


@pytest.mark.parametrize(
    "url",
    [
        "https://nocobase.example.com",
        "http://nocobase.example.com:8080",
        "https://8.8.8.8",  # public IP literal
        # Self-hosted targets are legitimate and must be allowed:
        "http://localhost:13000",  # loopback hostname
        "http://127.0.0.1:13000",  # loopback IP
        "http://10.0.0.5",  # private range
        "http://192.168.1.1",  # private range (LAN)
        "",  # empty is allowed: integration stays unconfigured
    ],
)
def test_base_url_accepts_valid_targets(url: str) -> None:
    assert NocoBaseAuthConfig(base_url=url).base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://nocobase.test",  # wrong scheme
        "file:///etc/passwd",  # wrong scheme
        "nocobase.test",  # no scheme
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://0.0.0.0",  # unspecified
        "http://224.0.0.1",  # multicast
    ],
)
def test_base_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        NocoBaseAuthConfig(base_url=url)
