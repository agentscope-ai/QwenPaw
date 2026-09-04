# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the encrypted secret store layer."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.security.secret_store import (
    AUTH_SECRET_FIELDS,
    PROVIDER_SECRET_FIELDS,
    decrypt,
    decrypt_dict_fields,
    encrypt,
    encrypt_dict_fields,
    is_encrypted,
)


@pytest.fixture(autouse=True)
def _isolate_master_key(tmp_path: Path, monkeypatch):
    """Provide a deterministic master key and isolated secret dir."""
    import qwenpaw.security.secret_store as mod

    # 32-byte hex key → 32-byte raw
    test_key = bytes.fromhex(
        "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
    )
    monkeypatch.setattr(mod, "_cached_master_key", test_key)
    monkeypatch.setattr(mod, "_cached_fernet", None)
    monkeypatch.setattr(mod, "_get_secret_dir", lambda: tmp_path)


class TestEncryptDecrypt:
    def test_roundtrip(self):
        plaintext = "sk-test-key-1234"
        ct = encrypt(plaintext)
        assert is_encrypted(ct)
        assert decrypt(ct) == plaintext

    def test_empty_passthrough(self):
        assert encrypt("") == ""
        assert decrypt("") == ""

    def test_plaintext_passthrough_on_decrypt(self):
        assert decrypt("sk-plain") == "sk-plain"

    def test_is_encrypted(self):
        ct = encrypt("hello")
        assert is_encrypted(ct)
        assert not is_encrypted("hello")
        assert not is_encrypted("")

    def test_unicode_roundtrip(self):
        text = "你好世界🌍"
        assert decrypt(encrypt(text)) == text


class TestDictHelpers:
    def test_encrypt_dict_fields(self):
        data = {"api_key": "sk-secret", "base_url": "https://api.example.com"}
        result = encrypt_dict_fields(data, PROVIDER_SECRET_FIELDS)
        assert is_encrypted(result["api_key"])
        assert result["base_url"] == "https://api.example.com"

    def test_decrypt_dict_fields(self):
        original = {"api_key": "sk-secret", "name": "test"}
        encrypted = encrypt_dict_fields(original, PROVIDER_SECRET_FIELDS)
        decrypted = decrypt_dict_fields(encrypted, PROVIDER_SECRET_FIELDS)
        assert decrypted["api_key"] == "sk-secret"
        assert decrypted["name"] == "test"

    def test_empty_field_not_encrypted(self):
        data = {"api_key": "", "name": "test"}
        result = encrypt_dict_fields(data, PROVIDER_SECRET_FIELDS)
        assert result["api_key"] == ""

    def test_already_encrypted_not_double_encrypted(self):
        data = {"api_key": "sk-secret"}
        once = encrypt_dict_fields(data, PROVIDER_SECRET_FIELDS)
        twice = encrypt_dict_fields(once, PROVIDER_SECRET_FIELDS)
        assert once["api_key"] == twice["api_key"]

    def test_auth_secret_fields(self):
        data = {
            "jwt_secret": "hex-secret-value",
            "user": {"username": "admin"},
        }
        enc = encrypt_dict_fields(data, AUTH_SECRET_FIELDS)
        assert is_encrypted(enc["jwt_secret"])
        assert enc["user"] == {"username": "admin"}
        dec = decrypt_dict_fields(enc, AUTH_SECRET_FIELDS)
        assert dec["jwt_secret"] == "hex-secret-value"


class TestBackwardCompatibility:
    """Verify that plaintext values survive a decrypt pass (migration path)."""

    def test_plaintext_api_key_survives_decrypt(self):
        data = {"api_key": "sk-old-plaintext-key", "name": "openai"}
        result = decrypt_dict_fields(data, PROVIDER_SECRET_FIELDS)
        assert result["api_key"] == "sk-old-plaintext-key"

    def test_mixed_fields_decrypt(self):
        ct = encrypt("sk-new-encrypted")
        data = {"api_key": ct, "base_url": "https://api.openai.com/v1"}
        result = decrypt_dict_fields(data, PROVIDER_SECRET_FIELDS)
        assert result["api_key"] == "sk-new-encrypted"
        assert result["base_url"] == "https://api.openai.com/v1"


class TestDecryptFailureGraceful:
    """Verify that corrupted or wrong-key ciphertext does not crash."""

    def test_corrupted_ciphertext_returns_raw(self):
        bad = "ENC:not_valid_fernet_token"
        result = decrypt(bad)
        assert result == bad

    def test_wrong_key_ciphertext_returns_raw(self, monkeypatch):
        import qwenpaw.security.secret_store as mod

        ct = encrypt("secret-value")

        new_key = bytes.fromhex("bb" * 32)
        monkeypatch.setattr(mod, "_cached_master_key", new_key)
        monkeypatch.setattr(mod, "_cached_fernet", None)

        result = decrypt(ct)
        assert result == ct

    def test_decrypt_dict_fields_survives_corruption(self):
        data = {"api_key": "ENC:corrupted_data", "name": "test"}
        result = decrypt_dict_fields(data, PROVIDER_SECRET_FIELDS)
        assert result["api_key"] == "ENC:corrupted_data"
        assert result["name"] == "test"


class TestMasterKeyGeneration:
    def test_generates_key_when_missing(self, tmp_path: Path, monkeypatch):
        import qwenpaw.security.secret_store as mod

        monkeypatch.setattr(mod, "_cached_master_key", None)
        monkeypatch.setattr(mod, "_get_secret_dir", lambda: tmp_path)

        with patch.object(
            mod,
            "_try_keyring_get",
            return_value=None,
        ), patch.object(mod, "_try_keyring_set", return_value=False):
            key = mod._get_master_key()

        assert isinstance(key, bytes)
        assert len(key) == 32
        assert (tmp_path / ".master_key").exists()

    def test_reads_from_file(self, tmp_path: Path, monkeypatch):
        import qwenpaw.security.secret_store as mod

        key_hex = "aa" * 32
        (tmp_path / ".master_key").write_text(key_hex)

        monkeypatch.setattr(mod, "_cached_master_key", None)
        monkeypatch.setattr(mod, "_get_secret_dir", lambda: tmp_path)

        with patch.object(
            mod,
            "_try_keyring_get",
            return_value=None,
        ), patch.object(mod, "_try_keyring_set", return_value=False):
            key = mod._get_master_key()

        assert key == bytes.fromhex(key_hex)


class TestKeyringAccountIsolation:
    """The keychain account must isolate relocated (dev) installs from the
    default install so they cannot overwrite each other's master key."""

    @pytest.fixture(autouse=True)
    def _clear_relocation_env(self, monkeypatch):
        for var in (
            "QWENPAW_KEYRING_ACCOUNT",
            "COPAW_KEYRING_ACCOUNT",
            "QWENPAW_WORKING_DIR",
            "COPAW_WORKING_DIR",
            "QWENPAW_SECRET_DIR",
            "COPAW_SECRET_DIR",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_default_install_uses_legacy_account(self, monkeypatch):
        import qwenpaw.security.secret_store as mod

        # No relocation env vars → historical account preserved verbatim so
        # existing installs are untouched.
        monkeypatch.setattr(
            mod,
            "_get_secret_dir",
            lambda: Path("~/.qwenpaw.secret").expanduser(),
        )
        assert mod._keyring_account() == "master_key"

    def test_explicit_override_wins(self, monkeypatch):
        import qwenpaw.security.secret_store as mod

        monkeypatch.setenv("QWENPAW_KEYRING_ACCOUNT", "dev-profile")
        monkeypatch.setenv("QWENPAW_WORKING_DIR", "/tmp/whatever")
        assert mod._keyring_account() == "dev-profile"

    def test_relocated_install_is_namespaced(self, monkeypatch, tmp_path):
        import qwenpaw.security.secret_store as mod

        monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path / ".devdata"))
        monkeypatch.setattr(
            mod,
            "_get_secret_dir",
            lambda: tmp_path / ".devdata.secret",
        )
        account = mod._keyring_account()
        assert account != "master_key"
        assert account.startswith("master_key:")

    def test_distinct_secret_dirs_get_distinct_accounts(
        self,
        monkeypatch,
        tmp_path,
    ):
        import qwenpaw.security.secret_store as mod

        monkeypatch.setenv("QWENPAW_SECRET_DIR", "set-to-mark-relocated")

        monkeypatch.setattr(mod, "_get_secret_dir", lambda: tmp_path / "a")
        account_a = mod._keyring_account()
        monkeypatch.setattr(mod, "_get_secret_dir", lambda: tmp_path / "b")
        account_b = mod._keyring_account()

        assert account_a != account_b

    def test_account_is_stable_for_same_secret_dir(
        self,
        monkeypatch,
        tmp_path,
    ):
        import qwenpaw.security.secret_store as mod

        monkeypatch.setenv("QWENPAW_SECRET_DIR", "set-to-mark-relocated")
        monkeypatch.setattr(mod, "_get_secret_dir", lambda: tmp_path / "x")
        assert mod._keyring_account() == mod._keyring_account()


@pytest.fixture
def _umask_022():
    """Pin a permissive umask so mode assertions are deterministic."""
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture
def _no_chmod(monkeypatch):
    """Disable ``os.chmod`` so only creation-time modes can pass a test.

    ``secret_store`` calls ``os.chmod`` best effort (``except OSError:
    pass``), so a mode that only holds because the chmod succeeded is not a
    guarantee. Everything asserted under this fixture holds without it.
    """
    monkeypatch.setattr(os, "chmod", lambda *args, **kwargs: None)


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX mode bits are not meaningful on Windows",
)
@pytest.mark.usefixtures("_umask_022")
class TestMasterKeyFilePermissions:
    """The fallback key file must be owner-only from the moment it exists.

    The module docstring promises ``SECRET_DIR/.master_key`` is persisted
    "with mode ``0o600``", so the mode has to come from creating the file
    rather than from a follow-up call that is allowed to fail.
    """

    @staticmethod
    def _secret_dir(mod, monkeypatch, tmp_path: Path) -> Path:
        secret_dir = tmp_path / "secrets"
        monkeypatch.setattr(mod, "_get_secret_dir", lambda: secret_dir)
        return secret_dir

    @staticmethod
    def _legacy_key_file(secret_dir: Path, content: str) -> Path:
        """Lay down a key file as a pre-0o600 version would have left it."""
        secret_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
        os.chmod(secret_dir, 0o755)
        path = secret_dir / ".master_key"
        path.write_text(content, encoding="utf-8")
        os.chmod(path, 0o644)
        # Under ``_no_chmod`` the call above is a no-op, so state the
        # precondition rather than assuming it.
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
        return path

    @pytest.mark.usefixtures("_no_chmod")
    def test_new_key_file_is_owner_only(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        import qwenpaw.security.secret_store as mod

        secret_dir = self._secret_dir(mod, monkeypatch, tmp_path)

        mod._write_key_file("cd" * 32)

        key_path = secret_dir / ".master_key"
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o700

    @pytest.mark.usefixtures("_no_chmod")
    def test_world_readable_key_file_is_replaced_not_truncated(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """A pre-existing 0o644 file must not host the new key.

        Opening the destination with ``O_TRUNC`` would keep its mode, so
        the freshly written key would sit in a world-readable inode.
        """
        import qwenpaw.security.secret_store as mod

        secret_dir = self._secret_dir(mod, monkeypatch, tmp_path)
        key_path = self._legacy_key_file(secret_dir, "ab" * 32)

        mod._write_key_file("cd" * 32)

        assert key_path.read_text(encoding="utf-8") == "cd" * 32
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600

    @pytest.mark.usefixtures("_no_chmod")
    def test_corrupt_world_readable_key_file_is_replaced(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """The regeneration path starts from the same 0o644 file."""
        import qwenpaw.security.secret_store as mod

        secret_dir = self._secret_dir(mod, monkeypatch, tmp_path)
        key_path = self._legacy_key_file(secret_dir, "not-a-hex-key")

        assert mod._read_key_file() is None

        mod._write_key_file("ef" * 32)

        assert key_path.read_text(encoding="utf-8") == "ef" * 32
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600

    @pytest.mark.usefixtures("_no_chmod")
    def test_reading_a_valid_legacy_key_migrates_it(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """A valid 0o644 key is never rewritten, so reading must fix it.

        Running without ``chmod`` is the point: tightening the mode of
        the legacy inode is the best-effort step that cannot be relied
        on, so the key has to end up in an inode created ``0o600``.
        """
        import qwenpaw.security.secret_store as mod

        secret_dir = self._secret_dir(mod, monkeypatch, tmp_path)
        key_path = self._legacy_key_file(secret_dir, "ab" * 32)
        legacy_inode = key_path.stat().st_ino

        assert mod._read_key_file() == "ab" * 32

        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
        assert key_path.stat().st_ino != legacy_inode
        assert key_path.read_text(encoding="utf-8") == "ab" * 32
        assert [p.name for p in secret_dir.iterdir()] == [".master_key"]

    @pytest.mark.usefixtures("_no_chmod")
    def test_owner_only_key_is_read_without_being_rewritten(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """A key that is already 0o600 must not be replaced on read."""
        import qwenpaw.security.secret_store as mod

        secret_dir = self._secret_dir(mod, monkeypatch, tmp_path)
        mod._write_key_file("ab" * 32)
        key_path = secret_dir / ".master_key"
        inode = key_path.stat().st_ino

        assert mod._read_key_file() == "ab" * 32

        assert key_path.stat().st_ino == inode

    def test_no_temporary_key_file_is_left_behind(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        import qwenpaw.security.secret_store as mod

        secret_dir = self._secret_dir(mod, monkeypatch, tmp_path)

        mod._write_key_file("11" * 32)
        mod._write_key_file("22" * 32)

        assert [p.name for p in secret_dir.iterdir()] == [".master_key"]


class TestMasterKeyFileContent:
    """Tightening the permissions must not change what is written."""

    def test_key_file_is_written_and_replaced(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        import qwenpaw.security.secret_store as mod

        secret_dir = tmp_path / "secrets"
        monkeypatch.setattr(mod, "_get_secret_dir", lambda: secret_dir)

        mod._write_key_file("11" * 32)
        assert mod._read_key_file() == "11" * 32

        mod._write_key_file("22" * 32)
        assert mod._read_key_file() == "22" * 32
