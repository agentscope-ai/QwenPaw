# -*- coding: utf-8 -*-
"""Regression tests for Matrix state migration and runtime device locks."""

import hashlib
import json

import pytest

from tests.channel_support.driver import module

matrix_module = module("matrix", "state")
MatrixStateError = matrix_module.MatrixStateError
MatrixStateStore = matrix_module.MatrixStateStore

USER = "@bot:example.com"
OTHER_USER = "@other:example.com"
DEVICE = "qwenpaw-worker"
DATABASE_NAME = f"{USER}_{DEVICE}.db"


def make_store(workspace, legacy):
    store = MatrixStateStore(
        {
            "workspace_dir": str(workspace),
            "legacy_state_dir": str(legacy),
            "homeserver": "https://matrix.test",
        },
    )
    store.begin()
    return store


def write_legacy(legacy, user=USER, device=DEVICE):
    legacy.mkdir(parents=True, exist_ok=True)
    auth = {
        "access_token": "legacy-token",
        "user_id": user,
        "device_id": device,
    }
    (legacy / "matrix_auth_state.json").write_text(json.dumps(auth))
    (legacy / "matrix_sync_token").write_text("legacy-batch")
    crypto = legacy / "matrix_crypto_store"
    crypto.mkdir(exist_ok=True)
    database = f"{user}_{device}.db"
    (crypto / database).write_bytes(b"legacy-crypto")
    return auth


def write_existing_owner(workspace, user=USER, device=DEVICE):
    workspace = workspace.resolve()
    owner = {
        "homeserver": "https://matrix.test",
        "user_id": user,
        "device_id": device,
        "workspace_dir": str(workspace),
    }
    scope = hashlib.sha256(
        json.dumps(["https://matrix.test", user, device]).encode(),
    ).hexdigest()
    root = workspace / "channel_state" / "matrix"
    directory = root / scope
    directory.mkdir(parents=True)
    (directory / "owner.json").write_text(json.dumps(owner))
    (directory / "sync_token").write_text("workspace-batch")
    (root / "current.json").write_text(
        json.dumps({"homeserver": "https://matrix.test", "scope": scope}),
    )
    return directory


def test_identity_mismatch_starts_fresh_without_touching_legacy(tmp_path):
    legacy = tmp_path / "legacy"
    auth = write_legacy(legacy, user=OTHER_USER, device="OTHER")
    original_auth = json.dumps(auth)
    store = make_store(tmp_path / "workspace-a", legacy)
    try:
        store.bind(USER, DEVICE)
        assert store.load_sync() is None
        assert store.owner["user_id"] == USER
        assert not store.crypto_dir.exists()
        assert (legacy / "matrix_auth_state.json").read_text() == (
            original_auth
        )
        assert (legacy / "matrix_sync_token").read_text() == "legacy-batch"
    finally:
        store.close()


def test_matching_identity_copies_sync_and_crypto_once(tmp_path):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)
    workspace = tmp_path / "workspace"
    first = make_store(workspace, legacy)
    try:
        first.bind(USER, DEVICE, encryption_enabled=True)
        assert first.load_sync() == "legacy-batch"
        database = first.crypto_dir / DATABASE_NAME
        assert database.read_bytes() == b"legacy-crypto"
        first.save_auth("fresh-token", USER, DEVICE)
    finally:
        first.close()
    legacy_auth = json.loads(
        (legacy / "matrix_auth_state.json").read_text(),
    )
    assert legacy_auth["access_token"] == "legacy-token"
    assert (legacy / "matrix_sync_token").read_text() == "legacy-batch"
    (legacy / "matrix_sync_token").write_text("changed-legacy")
    second = make_store(workspace, legacy)
    try:
        second.bind(USER, DEVICE, encryption_enabled=True)
        assert second.load_sync() == "legacy-batch"
        assert (second.crypto_dir / DATABASE_NAME).read_bytes() == (
            b"legacy-crypto"
        )
    finally:
        second.close()


def test_account_switch_reuses_each_workspace_scope(tmp_path):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)
    workspace = tmp_path / "workspace"
    first = make_store(workspace, legacy)
    try:
        first.bind(USER, DEVICE)
        assert first.load_sync() == "legacy-batch"
    finally:
        first.close()
    second = make_store(workspace, legacy)
    try:
        second.bind(OTHER_USER, "OTHER")
        assert second.load_sync() is None
    finally:
        second.close()
    third = make_store(workspace, legacy)
    try:
        third.bind(USER, DEVICE)
        assert third.load_sync() == "legacy-batch"
    finally:
        third.close()


def test_device_lock_is_released_and_stale_owner_is_ignored(tmp_path):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)
    first = make_store(tmp_path / "workspace-a", legacy)
    second = make_store(tmp_path / "workspace-b", legacy)
    first.bind(USER, DEVICE)
    with pytest.raises(MatrixStateError, match="DEVICE_ACTIVE_CONFLICT"):
        second.bind(USER, DEVICE)
    first.close()
    scope = hashlib.sha256(
        json.dumps(["https://matrix.test", USER, DEVICE]).encode(),
    ).hexdigest()
    claim = legacy / "matrix_plugin_claims" / scope
    claim.parent.mkdir(parents=True, exist_ok=True)
    claim.with_suffix(".json").write_text(
        json.dumps({"workspace_dir": "/old/workspace"}),
    )
    try:
        second.bind(USER, DEVICE)
        assert second.owner["user_id"] == USER
    finally:
        second.close()


def test_same_account_with_different_devices_can_run(tmp_path):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)
    first = make_store(tmp_path / "workspace-a", legacy)
    second = make_store(tmp_path / "workspace-b", legacy)
    try:
        first.bind(USER, DEVICE)
        second.bind(USER, "ANOTHER-DEVICE")
        assert second.owner["device_id"] == "ANOTHER-DEVICE"
    finally:
        second.close()
        first.close()


def test_non_e2ee_sync_copy_failure_uses_initial_sync(
    tmp_path,
    monkeypatch,
):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)

    def fail_copy(*_args):
        raise OSError("copy unavailable")

    monkeypatch.setattr(matrix_module.shutil, "copy2", fail_copy)
    store = make_store(tmp_path / "workspace", legacy)
    try:
        store.bind(USER, DEVICE)
        assert store.load_sync() is None
    finally:
        store.close()


def test_e2ee_copy_failure_does_not_create_new_identity(
    tmp_path,
    monkeypatch,
):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)

    def fail_copy(*_args):
        raise OSError("copy unavailable")

    monkeypatch.setattr(matrix_module.shutil, "copytree", fail_copy)
    store = make_store(tmp_path / "workspace", legacy)
    try:
        with pytest.raises(MatrixStateError, match="LEGACY_COPY_FAILED"):
            store.bind(USER, DEVICE, encryption_enabled=True)
        assert store.directory is None
        assert not list(store.root.glob(".matrix-migration-*"))
        database = legacy / "matrix_crypto_store" / DATABASE_NAME
        assert database.read_bytes() == b"legacy-crypto"
    finally:
        store.close()


def test_non_e2ee_crypto_copy_failure_discards_partial_copy(
    tmp_path,
    monkeypatch,
):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)

    def partial_copy(_source, destination):
        destination.mkdir(parents=True)
        (destination / DATABASE_NAME).write_bytes(b"partial")
        raise OSError("copy interrupted")

    monkeypatch.setattr(matrix_module.shutil, "copytree", partial_copy)
    store = make_store(tmp_path / "workspace", legacy)
    try:
        store.bind(USER, DEVICE)
        assert not store.crypto_dir.exists()
        assert store.load_sync() == "legacy-batch"
    finally:
        store.close()


def test_existing_owner_with_global_crypto_is_copied_to_workspace(tmp_path):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)
    workspace = tmp_path / "workspace"
    write_existing_owner(workspace)
    store = make_store(workspace, legacy)
    try:
        store.bind(USER, DEVICE, encryption_enabled=True)
        assert store.load_sync() == "workspace-batch"
        assert (store.crypto_dir / DATABASE_NAME).read_bytes() == (
            b"legacy-crypto"
        )
        legacy_database = legacy / "matrix_crypto_store" / DATABASE_NAME
        assert legacy_database.read_bytes() == b"legacy-crypto"
    finally:
        store.close()


def test_workspace_handoff_copies_latest_state_not_legacy_snapshot(tmp_path):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)
    workspace_a = tmp_path / "workspace-a"
    first = make_store(workspace_a, legacy)
    try:
        first.bind(USER, DEVICE, encryption_enabled=True)
        first.save_sync("workspace-a-latest")
        (first.crypto_dir / DATABASE_NAME).write_bytes(b"latest-crypto")
    finally:
        first.close()
    second = make_store(tmp_path / "workspace-b", legacy)
    try:
        second.bind(USER, DEVICE, encryption_enabled=True)
        assert second.load_sync() == "workspace-a-latest"
        assert (second.crypto_dir / DATABASE_NAME).read_bytes() == (
            b"latest-crypto"
        )
    finally:
        second.close()


def test_current_state_corruption_is_not_bypassed(tmp_path):
    legacy = tmp_path / "legacy"
    write_legacy(legacy)
    workspace = tmp_path / "workspace"
    first = make_store(workspace, legacy)
    try:
        first.bind(USER, DEVICE)
        owner_path = first.directory / "owner.json"
    finally:
        first.close()
    owner = json.loads(owner_path.read_text())
    owner["user_id"] = OTHER_USER
    owner_path.write_text(json.dumps(owner))
    second = make_store(workspace, legacy)
    try:
        with pytest.raises(MatrixStateError, match="STATE_IDENTITY_CONFLICT"):
            second.bind(USER, DEVICE)
    finally:
        second.close()
