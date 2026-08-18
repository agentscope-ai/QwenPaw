# -*- coding: utf-8 -*-
"""Tests for strict QwenPaw Pro startup configuration."""

import sqlite3
from pathlib import Path

import pytest

from qwenpaw.pro.auth import ProAuthService
from qwenpaw.pro.config import (
    ProConfig,
    ProConfigStore,
    TenantQuota,
    load_pro_config,
)
from qwenpaw.pro.credentials import TenantCredentialVault


def test_load_partial_config_and_resolve_tenant_override(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "pro.yaml"
    config_path.write_text(
        """
version: 1
control_plane:
  registration:
    enabled: false
runtime:
  default_driver: local
  allowed_drivers: [local]
tenant_defaults:
  max_runtimes: 3
  max_running_runtimes: 2
tenants:
  personal-user-a:
    max_running_runtimes: 1
""".strip(),
        encoding="utf-8",
    )

    config = load_pro_config(config_path)

    assert config.control_plane.registration.enabled is False
    assert config.default_driver == "local"
    assert config.allowed_drivers == frozenset({"local"})
    assert config.quota_for("personal-user-a") == TenantQuota(
        max_runtimes=3,
        max_running_runtimes=1,
    )


def test_no_config_uses_built_in_defaults() -> None:
    config = load_pro_config(None)

    assert config == ProConfig()
    assert config.control_plane.registration.enabled is None
    assert config.quota_for("tenant").max_runtimes is None


@pytest.mark.parametrize(
    "content, match",
    [
        ("version: 2", "Input should be 1"),
        ("runtime: {}", "missing version"),
        ("version: 1\nunknown: true", "Extra inputs are not permitted"),
        (
            "version: 1\ntenant_defaults:\n  max_runtimes: -1",
            "greater than or equal to 0",
        ),
        (
            "version: 1\nruntime:\n  allowed_drivers: []",
            "must not be empty",
        ),
    ],
)
def test_invalid_config_fails_closed(
    tmp_path: Path,
    content: str,
    match: str,
) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        load_pro_config(config_path)


def test_config_store_persists_explicit_fields_and_keeps_disk_values(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.db"
    config_path = tmp_path / "pro.yaml"
    config_path.write_text(
        """
version: 1
control_plane:
  registration:
    enabled: true
runtime:
  allowed_drivers: [local]
tenant_defaults:
  max_runtimes: 3
  max_running_runtimes: 2
""".strip(),
        encoding="utf-8",
    )
    store = ProConfigStore(database)

    imported = store.resolve(config_path)
    loaded_from_disk = store.resolve(None)

    assert imported == loaded_from_disk
    assert loaded_from_disk.allowed_drivers == frozenset({"local"})
    assert loaded_from_disk.tenant_defaults.max_runtimes == 3
    with sqlite3.connect(database) as connection:
        registration = connection.execute(
            "SELECT value FROM pro_settings WHERE key = ?",
            ("registration_enabled",),
        ).fetchone()
    assert registration == ("true",)
    auth = ProAuthService(
        database,
        TenantCredentialVault(database, tmp_path / ".vault_key"),
    )
    assert auth.registration_enabled() is True

    config_path.write_text(
        "version: 1\ntenant_defaults:\n  max_running_runtimes: 1",
        encoding="utf-8",
    )
    updated = store.resolve(config_path)

    assert updated.tenant_defaults.max_runtimes == 3
    assert updated.tenant_defaults.max_running_runtimes == 1


def test_config_store_does_not_persist_unavailable_driver(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "pro.yaml"
    config_path.write_text(
        "version: 1\nruntime:\n  default_driver: docker",
        encoding="utf-8",
    )
    store = ProConfigStore(tmp_path / "control.db")

    with pytest.raises(ValueError, match="Unknown default runtime driver"):
        store.resolve(config_path, available_drivers={"local"})

    assert store.resolve(None).default_driver == "local"
