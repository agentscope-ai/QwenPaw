# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the encrypted secret store layer."""
from __future__ import annotations

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
            "local_cli_token": "cli-token-value",
            "user": {"username": "admin"},
        }
        enc = encrypt_dict_fields(data, AUTH_SECRET_FIELDS)
        assert is_encrypted(enc["jwt_secret"])
        assert is_encrypted(enc["local_cli_token"])
        assert enc["user"] == {"username": "admin"}
        dec = decrypt_dict_fields(enc, AUTH_SECRET_FIELDS)
        assert dec["jwt_secret"] == "hex-secret-value"
        assert dec["local_cli_token"] == "cli-token-value"


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
