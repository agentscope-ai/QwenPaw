# -*- coding: utf-8 -*-
"""Tests for strict QwenPaw Hub startup configuration."""

import sqlite3
from pathlib import Path

import pytest

from qwenpaw.hub.auth import HubAuthService
from qwenpaw.hub.config import (
    ControlPlaneConfig,
    DockerRuntimeConfig,
    HubConfig,
    HubConfigStore,
    RuntimeConfig,
    TenantQuota,
    load_hub_config,
)
from qwenpaw.hub.credentials import TenantCredentialVault


def test_load_partial_config_and_resolve_tenant_override(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "hub.yaml"
    config_path.write_text(
        """
version: 1
control_plane:
  public_base_url: https://qwenpaw.example.com/root/
  registration:
    enabled: false
runtime:
  provisioner: local
tenant_defaults:
  max_runtimes: 3
  max_running_runtimes: 2
tenants:
  personal-user-a:
    max_running_runtimes: 1
""".strip(),
        encoding="utf-8",
    )

    config = load_hub_config(config_path)

    assert config.control_plane.registration.enabled is False
    assert (
        config.control_plane.public_base_url
        == "https://qwenpaw.example.com/root"
    )
    assert config.default_provisioner == "local"
    assert config.quota_for("personal-user-a") == TenantQuota(
        max_runtimes=3,
        max_running_runtimes=1,
    )


def test_no_config_uses_built_in_defaults() -> None:
    config = load_hub_config(None)

    assert config == HubConfig()
    assert config.control_plane.registration.enabled is None
    assert config.quota_for("tenant").max_runtimes is None


def test_docker_yaml_fields_round_trip_without_panel_only_values(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "hub.yaml"
    config_path.write_text(
        """
version: 1
runtime:
  provisioner: docker
  docker:
    source: custom
    image: registry.example.com/qwenpaw:v2
    pull_policy: never
    allowed_registries: [registry.example.com]
    cpu_limit: 3.5
    memory_limit_mb: 6144
    pids_limit: 768
    shm_size_mb: 1024
""".strip(),
        encoding="utf-8",
    )

    config = load_hub_config(config_path)

    assert config.runtime.provisioner == "docker"
    assert config.runtime.docker == DockerRuntimeConfig(
        source="custom",
        image="registry.example.com/qwenpaw:v2",
        pull_policy="never",
        allowed_registries=["registry.example.com"],
        cpu_limit=3.5,
        memory_limit_mb=6144,
        pids_limit=768,
        shm_size_mb=1024,
    )
    assert set(config.runtime.docker.model_dump()) == {
        "source",
        "image",
        "pull_policy",
        "allowed_registries",
        "cpu_limit",
        "memory_limit_mb",
        "pids_limit",
        "shm_size_mb",
    }


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
            "version: 1\nruntime:\n  provisioner: unsupported",
            "Input should be 'local' or 'docker'",
        ),
        (
            "version: 1\ncontrol_plane:\n  public_base_url: localhost",
            "absolute HTTP\\(S\\) URL",
        ),
        (
            "version: 1\ncontrol_plane:\n"
            "  public_base_url: https://user@example.com",
            "must not contain credentials",
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
        load_hub_config(config_path)


def test_config_store_persists_explicit_fields_and_keeps_disk_values(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.db"
    config_path = tmp_path / "hub.yaml"
    config_path.write_text(
        """
version: 1
control_plane:
  registration:
    enabled: true
runtime:
  provisioner: local
tenant_defaults:
  max_runtimes: 3
  max_running_runtimes: 2
""".strip(),
        encoding="utf-8",
    )
    store = HubConfigStore(database)

    imported = store.resolve(config_path)
    loaded_from_disk = store.resolve(None)

    assert imported == loaded_from_disk
    assert loaded_from_disk.runtime.provisioner == "local"
    assert loaded_from_disk.tenant_defaults.max_runtimes == 3
    with sqlite3.connect(database) as connection:
        registration = connection.execute(
            "SELECT value_json FROM hub_settings WHERE key = ?",
            ("registration_enabled",),
        ).fetchone()
    assert registration == ("true",)
    auth = HubAuthService(
        database,
        TenantCredentialVault(database, tmp_path / ".vault_key"),
    )
    assert auth.registration_enabled() is True

    config_path.write_text(
        "version: 1\ntenant_defaults:\n  max_running_runtimes: 1",
        encoding="utf-8",
    )
    unchanged = store.resolve(config_path)

    assert unchanged.tenant_defaults.max_runtimes == 3
    assert unchanged.tenant_defaults.max_running_runtimes == 2


def test_config_store_updates_with_revision_and_rejects_stale_writes(
    tmp_path: Path,
) -> None:
    store = HubConfigStore(tmp_path / "control.db")
    store.resolve(None, available_provisioners={"local"})
    _, revision, _ = store.snapshot()
    updated = HubConfig(
        runtime=RuntimeConfig(
            provisioner="local",
        ),
        tenant_defaults=TenantQuota(
            max_runtimes=4,
            max_running_runtimes=2,
        ),
    )

    saved, next_revision, _ = store.update(
        updated,
        expected_revision=revision,
        available_provisioners={"local"},
        updated_by_user_id="admin-a",
    )

    assert saved.tenant_defaults == updated.tenant_defaults
    assert saved.control_plane.registration.enabled is False
    assert saved.control_plane.registration.default_role == "user"
    assert next_revision == revision + 1
    assert store.snapshot()[0] == saved
    with pytest.raises(RuntimeError, match="changed concurrently"):
        store.update(
            HubConfig(),
            expected_revision=revision,
            available_provisioners={"local"},
            updated_by_user_id="admin-b",
        )


def test_config_store_does_not_persist_unavailable_provisioner(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "hub.yaml"
    config_path.write_text(
        "version: 1\nruntime:\n  provisioner: docker",
        encoding="utf-8",
    )
    store = HubConfigStore(tmp_path / "control.db")

    with pytest.raises(
        ValueError,
        match="Unknown runtime provisioner",
    ):
        store.resolve(config_path, available_provisioners={"local"})

    assert store.resolve(None).default_provisioner == "local"


def test_public_base_url_rejects_query_and_fragment() -> None:
    with pytest.raises(ValueError, match="query or fragment"):
        HubConfig(
            control_plane=ControlPlaneConfig(
                public_base_url="https://example.com?tenant=one",
            ),
        )
