# -*- coding: utf-8 -*-
"""Unit tests for CopilotTokenStore (encrypted on-disk persistence)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import qwenpaw.constant as constant_module
from qwenpaw.providers.oauth.copilot_token_store import CopilotTokenStore


@pytest.fixture
def secret_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SECRET_DIR to a temp folder for the duration of the test."""
    monkeypatch.setattr(constant_module, "SECRET_DIR", tmp_path)
    # Also reload the secret_store module's lazy lookup
    return tmp_path


def test_save_and_load_roundtrip(secret_dir: Path) -> None:
    store = CopilotTokenStore("github-copilot")
    store.save("gho_secret_token_123", github_login="octocat")

    assert store.path.exists()
    payload = store.load()
    assert payload is not None
    assert payload["oauth_access_token"] == "gho_secret_token_123"
    assert payload["github_login"] == "octocat"
    assert payload["saved_at"] > 0


def test_save_writes_encrypted_token_on_disk(secret_dir: Path) -> None:
    store = CopilotTokenStore("github-copilot")
    store.save("gho_plaintext_must_not_appear", github_login="alice")

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    # Secret field must be encrypted (ENC: prefix from secret_store).
    assert raw["oauth_access_token"].startswith("ENC:")
    assert "gho_plaintext_must_not_appear" not in store.path.read_text(
        encoding="utf-8",
    )
    # Non-secret field is stored in plain text.
    assert raw["github_login"] == "alice"


def test_save_skips_empty_token(secret_dir: Path) -> None:
    store = CopilotTokenStore("github-copilot")
    store.save("", github_login="alice")
    assert not store.path.exists()


def test_load_returns_none_when_missing(secret_dir: Path) -> None:
    store = CopilotTokenStore("github-copilot")
    assert store.load() is None


def test_load_handles_corrupted_file(secret_dir: Path) -> None:
    store = CopilotTokenStore("github-copilot")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json", encoding="utf-8")
    assert store.load() is None


def test_delete_is_idempotent(secret_dir: Path) -> None:
    store = CopilotTokenStore("github-copilot")
    store.delete()  # missing — must not raise
    store.save("gho_x", github_login="bob")
    assert store.path.exists()
    store.delete()
    assert not store.path.exists()
    store.delete()  # second delete must be a no-op


def test_save_sets_owner_only_permissions_on_posix(
    secret_dir: Path,
) -> None:
    store = CopilotTokenStore("github-copilot")
    store.save("gho_token", github_login="user")
    if os.name == "posix":
        mode = store.path.stat().st_mode & 0o777
        assert mode == 0o600
