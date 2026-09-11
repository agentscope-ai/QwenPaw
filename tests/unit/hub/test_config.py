# -*- coding: utf-8 -*-
"""Tests for strict QwenPaw Hub startup configuration."""

import sqlite3
from pathlib import Path

import pytest

from qwenpaw.hub.auth import HubAuthService
from qwenpaw.hub.config import (
    DockerRuntimeConfig,
    HubConfig,
    HubConfigStore,
    RuntimeCapacityConfig,
    RuntimeConfig,
    RuntimeProxyConfig,
    load_hub_config,
)
from qwenpaw.hub.credentials import TenantCredentialVault


def test_load_partial_config_and_security_policy(
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
  security:
    ip_blacklist: [192.0.2.4, 2001:db8::/64]
  proxy:
    max_request_size_mb: 2048
    request_idle_timeout_seconds: 90
    response_header_timeout_seconds: 600
    connect_timeout_seconds: 15
    websocket_max_message_size_mb: 32
runtime:
  provisioner: local
capacity:
  max_running_runtimes: 2
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
    assert config.capacity.max_running_runtimes == 2
    assert config.control_plane.security.ip_blacklist == [
        "192.0.2.4/32",
        "2001:db8::/64",
    ]
    assert config.control_plane.proxy == RuntimeProxyConfig(
        max_request_size_mb=2048,
        request_idle_timeout_seconds=90,
        response_header_timeout_seconds=600,
        connect_timeout_seconds=15,
        websocket_max_message_size_mb=32,
    )


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
        cpu_limit=3.5,
        memory_limit_mb=6144,
        pids_limit=768,
        shm_size_mb=1024,
    )
    assert set(config.runtime.docker.model_dump()) == {
        "source",
        "image",
        "pull_policy",
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
            "version: 1\ncapacity:\n  max_running_runtimes: -1",
            "greater than or equal to 0",
        ),
        (
            "version: 1\nruntime:\n  provisioner: unsupported",
            "Input should be 'local' or 'docker'",
        ),
        (
            "version: 1\nruntime:\n  docker:\n"
            "    allowed_registries: [docker.io]",
            "Extra inputs are not permitted",
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
        (
            "version: 1\ncontrol_plane:\n"
            "  public_base_url: https://example.com?tenant=one",
            "query or fragment",
        ),
        (
            "version: 1\ncontrol_plane:\n"
            "  public_base_url: https://example.com#fragment",
            "query or fragment",
        ),
        (
            "version: 1\ncontrol_plane:\n"
            "  proxy:\n    max_request_size_mb: 0",
            "greater than or equal to 1",
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


def test_config_store_applies_explicit_yaml_on_every_resolve(
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
capacity:
  max_running_runtimes: 2
""".strip(),
        encoding="utf-8",
    )
    store = HubConfigStore(database)

    imported = store.resolve(config_path)
    loaded_from_disk = store.resolve(None)

    assert imported == loaded_from_disk
    assert loaded_from_disk.runtime.provisioner == "local"
    assert loaded_from_disk.capacity.max_running_runtimes == 2
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
    _, revision, _ = store.snapshot()
    store.update(
        HubConfig(
            capacity=RuntimeCapacityConfig(max_running_runtimes=4),
        ),
        expected_revision=revision,
        available_provisioners={"local", "docker"},
        updated_by_user_id="admin-a",
    )
    assert store.resolve(None).capacity.max_running_runtimes == 4

    config_path.write_text(
        """
version: 1
control_plane:
  registration:
    enabled: false
capacity:
  max_running_runtimes: 1
""".strip(),
        encoding="utf-8",
    )
    replaced = store.resolve(config_path)

    assert replaced.capacity.max_running_runtimes == 1
    assert replaced.control_plane.registration.enabled is False
    assert store.resolve(None) == replaced
    assert auth.registration_enabled() is False


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
        capacity=RuntimeCapacityConfig(
            max_running_runtimes=2,
        ),
    )

    saved, next_revision, _ = store.update(
        updated,
        expected_revision=revision,
        available_provisioners={"local"},
        updated_by_user_id="admin-a",
    )

    assert saved.capacity == updated.capacity
    assert saved.control_plane.registration.enabled is False
    assert saved.control_plane.registration.default_role == "user"
    assert next_revision == revision + 1
    assert store.snapshot()[0] == saved
    assert store.resolve(None) == saved
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
