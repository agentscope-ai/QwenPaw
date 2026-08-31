# -*- coding: utf-8 -*-
"""Tests for the auth module token lifecycle and revocation list.

Covers create_token/verify_token round-trip (including expiry and
tamper rejection), _get_jwt_secret persistence, the revocation list
(add/lookup/clean-expired), revoke_token, revoke_all_tokens (secret
rotation), and _load_auth_data malformed-file fail-closed semantics.

The secret-field encryption helpers are stubbed with identity
functions and AUTH_FILE is redirected to a temp dir so no real secret
store is touched.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from qwenpaw.app import auth as auth_module


@pytest.fixture
def auth_env(tmp_path, monkeypatch):
    """Redirect AUTH_FILE and neutralize secret-field encryption."""
    monkeypatch.setattr(auth_module, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(
        auth_module,
        "encrypt_dict_fields",
        lambda data, fields: data,
    )
    monkeypatch.setattr(
        auth_module,
        "decrypt_dict_fields",
        lambda data, fields: data,
    )
    monkeypatch.setattr(auth_module, "is_encrypted", lambda value: False)
    monkeypatch.setattr(
        auth_module,
        "_prepare_secret_parent",
        lambda path: None,
    )
    monkeypatch.setattr(
        auth_module,
        "_chmod_best_effort",
        lambda path, mode: None,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# token round-trip
# ---------------------------------------------------------------------------


class TestTokenRoundTrip:
    def test_create_and_verify(self, auth_env):
        token = auth_module.create_token("alice")
        assert auth_module.verify_token(token) == "alice"

    def test_permanent_token_never_expires_soon(self, auth_env):
        token = auth_module.create_token("alice", expiry_seconds=-1)
        payload = json.loads(
            base64.urlsafe_b64decode(token.split(".")[0]),
        )
        # permanent = ~100 years out
        assert payload["exp"] - payload["iat"] > 60 * 60 * 24 * 365

    def test_custom_expiry_capped(self, auth_env):
        token = auth_module.create_token("alice", expiry_seconds=10**12)
        payload = json.loads(
            base64.urlsafe_b64decode(token.split(".")[0]),
        )
        assert payload["exp"] - payload["iat"] <= (
            auth_module.TOKEN_EXPIRY_MAX
        )

    def test_tampered_payload_rejected(self, auth_env):
        token = auth_module.create_token("alice")
        payload_b64, sig = token.split(".", 1)
        forged = json.loads(base64.urlsafe_b64decode(payload_b64))
        forged["sub"] = "mallory"
        forged_b64 = base64.urlsafe_b64encode(
            json.dumps(forged).encode(),
        ).decode()
        assert auth_module.verify_token(f"{forged_b64}.{sig}") is None

    def test_tampered_signature_rejected(self, auth_env):
        token = auth_module.create_token("alice")
        payload_b64, _ = token.split(".", 1)
        assert auth_module.verify_token(f"{payload_b64}.badsig") is None

    def test_malformed_token_rejected(self, auth_env):
        assert auth_module.verify_token("no-dot-at-all") is None
        assert auth_module.verify_token("") is None
        assert auth_module.verify_token("abc.def") is None

    def test_expired_token_rejected(self, auth_env, monkeypatch):
        token = auth_module.create_token("alice", expiry_seconds=60)
        # Move time far past expiry
        import time as time_mod

        real_time = time_mod.time
        monkeypatch.setattr(
            auth_module.time,
            "time",
            lambda: real_time() + 200,
        )
        assert auth_module.verify_token(token) is None


class TestJwtSecret:
    def test_secret_created_and_persisted(self, auth_env):
        secret1 = auth_module._get_jwt_secret()
        assert secret1
        data = json.loads((auth_env / "auth.json").read_text())
        assert data["jwt_secret"] == secret1

    def test_secret_stable_across_calls(self, auth_env):
        assert auth_module._get_jwt_secret() == auth_module._get_jwt_secret()


# ---------------------------------------------------------------------------
# revocation
# ---------------------------------------------------------------------------


class TestRevocation:
    def test_revoke_token_blocks_verification(self, auth_env):
        token = auth_module.create_token("alice")
        assert auth_module.verify_token(token) == "alice"
        assert auth_module.revoke_token(token) is True
        assert auth_module.verify_token(token) is None

    def test_revoke_other_tokens_unaffected(self, auth_env):
        token_a = auth_module.create_token("alice")
        token_b = auth_module.create_token("bob")
        auth_module.revoke_token(token_a)
        assert auth_module.verify_token(token_b) == "bob"

    def test_revoke_malformed_token_returns_false(self, auth_env):
        assert auth_module.revoke_token("garbage") is False

    def test_revoke_token_without_jti_returns_false(self, auth_env):
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "x", "exp": 9999999999}).encode(),
        ).decode()
        assert auth_module.revoke_token(f"{payload}.sig") is False

    def test_revoke_all_rotates_secret(self, auth_env):
        old_secret = auth_module._get_jwt_secret()
        token = auth_module.create_token("alice")
        assert auth_module.revoke_all_tokens() is True
        new_secret = auth_module._get_jwt_secret()
        assert old_secret != new_secret
        # Old tokens are now invalid
        assert auth_module.verify_token(token) is None
        # Revocation list cleared
        data = json.loads((auth_env / "auth.json").read_text())
        assert data["revoked_tokens"] == []
        assert data["revoked_tokens_meta"] == {}

    def test_is_token_revoked_lookup(self, auth_env):
        auth_module._add_to_revocation_list("jti-1", 9999999999)
        assert auth_module._is_token_revoked("jti-1") is True
        assert auth_module._is_token_revoked("jti-2") is False


class TestCleanExpiredRevocations:
    def test_expired_entries_removed(self, auth_env):
        import time as time_mod

        now = int(time_mod.time())
        auth_module._add_to_revocation_list("expired", now - 100)
        auth_module._add_to_revocation_list("valid", now + 10000)
        auth_module._clean_expired_revocations()
        data = json.loads((auth_env / "auth.json").read_text())
        assert "expired" not in data["revoked_tokens"]
        assert "valid" in data["revoked_tokens"]
        assert "expired" not in data["revoked_tokens_meta"]

    def test_all_valid_no_rewrite(self, auth_env):
        import time as time_mod

        now = int(time_mod.time())
        auth_module._add_to_revocation_list("valid", now + 10000)
        before = (auth_env / "auth.json").read_text()
        auth_module._clean_expired_revocations()
        assert (auth_env / "auth.json").read_text() == before


# ---------------------------------------------------------------------------
# _load_auth_data fail-closed
# ---------------------------------------------------------------------------


class TestLoadAuthData:
    def test_missing_file_returns_empty(self, auth_env):
        assert auth_module._load_auth_data() == {}

    def test_malformed_json_fails_closed(self, auth_env):
        (auth_env / "auth.json").write_text("{broken", encoding="utf-8")
        data = auth_module._load_auth_data()
        assert data.get("_auth_load_error") is True

    def test_valid_json_loaded(self, auth_env):
        (auth_env / "auth.json").write_text(
            json.dumps({"jwt_secret": "s"}),
            encoding="utf-8",
        )
        assert auth_module._load_auth_data()["jwt_secret"] == "s"

    def test_revocation_noop_on_load_error(self, auth_env):
        (auth_env / "auth.json").write_text("{broken", encoding="utf-8")
        # must not raise, and not rewrite
        auth_module._add_to_revocation_list("jti", 999)
        assert (auth_env / "auth.json").read_text() == "{broken"
