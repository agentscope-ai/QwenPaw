# -*- coding: utf-8 -*-
"""Tests for tenant-qualified QwenPaw Pro credential storage."""

import os
from pathlib import Path

from qwenpaw.pro.credentials import TenantCredentialVault
from qwenpaw.pro.local_driver import LocalProcessRuntimeDriver
from qwenpaw.pro.models import RuntimeRecord, RuntimeState


def test_same_credential_name_never_crosses_tenant_boundary(
    tmp_path: Path,
) -> None:
    vault = TenantCredentialVault(
        tmp_path / "control.db",
        tmp_path / ".vault_key",
    )
    vault.put(
        tenant_id="tenant-a",
        scope="tenant",
        name="OPENAI_API_KEY",
        value="key-a",
    )
    vault.put(
        tenant_id="tenant-b",
        scope="tenant",
        name="OPENAI_API_KEY",
        value="key-b",
    )

    assert vault.resolve_environment(
        tenant_id="tenant-a",
        runtime_id="runtime-a",
    ) == {"OPENAI_API_KEY": "key-a"}
    assert vault.resolve_environment(
        tenant_id="tenant-b",
        runtime_id="runtime-b",
    ) == {"OPENAI_API_KEY": "key-b"}


def test_runtime_scope_overrides_only_its_tenant_value(tmp_path: Path) -> None:
    vault = TenantCredentialVault(
        tmp_path / "control.db",
        tmp_path / ".vault_key",
    )
    vault.put(
        tenant_id="tenant-a",
        scope="tenant",
        name="OPENAI_API_KEY",
        value="tenant-key",
    )
    vault.put(
        tenant_id="tenant-a",
        scope="runtime:runtime-a",
        name="OPENAI_API_KEY",
        value="runtime-key",
    )

    assert (
        vault.resolve_environment(
            tenant_id="tenant-a",
            runtime_id="runtime-a",
        )["OPENAI_API_KEY"]
        == "runtime-key"
    )
    assert (
        vault.resolve_environment(
            tenant_id="tenant-a",
            runtime_id="runtime-b",
        )["OPENAI_API_KEY"]
        == "tenant-key"
    )


def test_local_runtime_does_not_inherit_control_plane_secrets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "control-plane-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "control-plane-secret")
    record = RuntimeRecord(
        runtime_id="runtime-a",
        tenant_id="tenant-a",
        owner_user_id="user-a",
        driver="local",
        host="127.0.0.1",
        port=9001,
        state=RuntimeState.CREATED,
        working_dir=tmp_path / "working",
        secret_dir=tmp_path / "secrets",
        backup_dir=tmp_path / "backups",
        log_file=tmp_path / "logs" / "app.log",
    )

    environment = LocalProcessRuntimeDriver.runtime_environment(
        record,
        {"ANTHROPIC_API_KEY": "tenant-key"},
    )

    assert "OPENAI_API_KEY" not in environment
    assert "LANGFUSE_SECRET_KEY" not in environment
    assert environment["ANTHROPIC_API_KEY"] == "tenant-key"
    assert environment["QWENPAW_PRO_TENANT_ID"] == "tenant-a"
    assert environment.get("PATH") == os.environ.get("PATH")
