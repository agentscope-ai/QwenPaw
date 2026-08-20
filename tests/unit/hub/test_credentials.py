# -*- coding: utf-8 -*-
"""Tests for tenant-qualified QwenPaw Hub credential storage."""

import os
import sys
from pathlib import Path

import pytest

from qwenpaw.hub.credentials import TenantCredentialVault
from qwenpaw.hub.local_provisioner import LocalProcessRuntimeProvisioner
from tests.unit.hub.factories import runtime_record as _record


@pytest.fixture(name="vault")
def _vault(tmp_path: Path) -> TenantCredentialVault:
    return TenantCredentialVault(
        tmp_path / "control.db",
        tmp_path / ".vault_key",
    )


def test_same_credential_name_never_crosses_tenant_boundary(
    vault: TenantCredentialVault,
) -> None:
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


def test_runtime_scope_overrides_only_its_tenant_value(
    vault: TenantCredentialVault,
) -> None:
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


def test_windows_runtime_redirects_user_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SYSTEMDRIVE", "C:")
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\control-plane")
    monkeypatch.setenv("APPDATA", "C:\\Users\\control-plane\\AppData")
    record = _record(tmp_path)

    environment = LocalProcessRuntimeProvisioner.runtime_environment(
        record,
        {},
    )

    assert environment["SYSTEMDRIVE"] == "C:"
    assert environment["USERPROFILE"] == str(record.working_dir)
    assert environment["APPDATA"] == str(
        record.working_dir / "appdata" / "roaming",
    )
    assert environment["LOCALAPPDATA"] == str(
        record.working_dir / "appdata" / "local",
    )


@pytest.mark.parametrize(
    "name",
    [
        "PATH",
        "PYTHONPATH",
        "HOME",
        "TMPDIR",
        "QWENPAW_WORKING_DIR",
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
    ],
)
def test_tenant_cannot_store_runtime_control_credentials(
    vault: TenantCredentialVault,
    name: str,
) -> None:
    with pytest.raises(ValueError, match="reserved by the runtime"):
        vault.put(
            tenant_id="tenant-a",
            scope="tenant",
            name=name,
            value="attacker-controlled",
        )


def test_preexisting_control_credentials_are_not_resolved(
    vault: TenantCredentialVault,
) -> None:
    vault.put(
        tenant_id="tenant-a",
        scope="tenant",
        name="PYTHONPATH",
        value="/",
        trusted=True,
    )

    assert (
        vault.resolve_environment(
            tenant_id="tenant-a",
            runtime_id="runtime-a",
        )
        == {}
    )


def test_runtime_boundary_secret_ignores_tenant_planted_value(
    vault: TenantCredentialVault,
) -> None:
    vault.put(
        tenant_id="tenant-a",
        scope="runtime:runtime-a",
        name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        value="tenant-known-token",
        trusted=True,
    )

    secret = vault.get_or_create_runtime_secret(
        tenant_id="tenant-a",
        runtime_id="runtime-a",
        name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
    )

    assert secret != "tenant-known-token"
    assert (
        vault.get(
            tenant_id="tenant-a",
            scope="runtime:runtime-a",
            name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        )
        is None
    )
    assert (
        vault.get_runtime_secret(
            tenant_id="tenant-a",
            runtime_id="runtime-a",
            name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        )
        == secret
    )


def test_local_runtime_filters_untrusted_control_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "control-plane-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "control-plane-secret")
    record = _record(tmp_path)

    environment = LocalProcessRuntimeProvisioner.runtime_environment(
        record,
        {
            "PYTHONPATH": "/",
            "QWENPAW_WORKING_DIR": "/other-tenant",
            "QWENPAW_RUNTIME_INTERNAL_TOKEN": "boundary-token",
            "OPENAI_API_KEY": "tenant-key",
        },
    )

    assert environment.get("PYTHONPATH") != "/"
    assert environment["QWENPAW_WORKING_DIR"] == str(record.working_dir)
    assert environment["QWENPAW_RUNTIME_INTERNAL_TOKEN"] == "boundary-token"
    assert environment["OPENAI_API_KEY"] == "tenant-key"
    assert "LANGFUSE_SECRET_KEY" not in environment
    assert environment.get("PATH") == os.environ.get("PATH")


def test_credential_metadata_pages_are_tenant_scoped_and_filterable(
    vault: TenantCredentialVault,
) -> None:
    for index in range(5):
        vault.put(
            tenant_id="tenant-a",
            scope="tenant" if index < 3 else "runtime:runtime-a",
            name=f"API_KEY_{index}",
            value=f"secret-{index}",
        )
    vault.put(
        tenant_id="tenant-b",
        scope="tenant",
        name="API_KEY_OTHER",
        value="other-secret",
    )

    items, total = vault.list_metadata_page(
        tenant_id="tenant-a",
        page=1,
        page_size=2,
        scope="runtime:runtime-a",
    )

    assert total == 2
    assert len(items) == 2
    assert {item["name"] for item in items} == {"API_KEY_3", "API_KEY_4"}
    assert "secret" not in str(items)
