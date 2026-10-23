# -*- coding: utf-8 -*-
"""Password storage and authentication log security regressions."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import pytest

from qwenpaw.app import auth


@pytest.fixture
def auth_store(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(auth, "encrypt_dict_fields", lambda data, _: data)
    monkeypatch.setattr(auth, "decrypt_dict_fields", lambda data, _: data)
    monkeypatch.setattr(auth, "is_encrypted", lambda _: True)
    return auth.AUTH_FILE


def test_new_passwords_use_work_factored_hashes():
    password = "correct horse 电池"
    stored, salt = auth._hash_password(password)
    scheme, rounds, digest = stored.split("$")
    assert scheme == "pbkdf2_sha256"
    assert int(rounds) >= 600_000
    expected = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        int(rounds),
    ).hex()
    assert digest == expected
    assert auth.verify_password(password, stored, salt) is True
    assert auth.verify_password("wrong", stored, salt) is False
    other_hash, other_salt = auth._hash_password(password)
    assert other_salt != salt
    assert other_hash != stored


@pytest.mark.parametrize(
    "password, salt",
    [("password", "0123456789abcdef"), ("旧密码 🔑", "任意盐🧂")],
)
def test_legacy_password_migrates_only_after_valid_login(
    auth_store,
    password,
    salt,
):
    legacy_hash = hashlib.sha256((salt + password).encode()).hexdigest()
    auth_store.write_text(
        json.dumps(
            {
                "user": {
                    "username": "alice",
                    "password_hash": legacy_hash,
                    "password_salt": salt,
                },
                "jwt_secret": "signing-secret",
            },
        ),
        encoding="utf-8",
    )
    before = auth_store.read_bytes()
    assert auth.authenticate("alice", "wrong") is None
    assert auth_store.read_bytes() == before
    token = auth.authenticate("alice", password)
    assert token is not None
    assert auth.verify_token(token) == "alice"
    migrated = json.loads(auth_store.read_text())["user"]
    assert migrated["password_hash"].startswith("pbkdf2_sha256$")
    assert migrated["password_salt"] != salt
    assert auth.verify_password(
        password,
        migrated["password_hash"],
        migrated["password_salt"],
    )


def test_user_and_untrusted_token_logs_escape_line_breaks(auth_store, caplog):
    username = "alice\r\nFORGED"
    with caplog.at_level(logging.INFO, logger=auth.__name__):
        token = auth.register_user(username, "password")
        assert auth.verify_token(token) == username
        assert auth.update_credentials("password", new_username=username)
        payload = base64.urlsafe_b64encode(
            json.dumps({"jti": "x\r\ny", "exp": 9999999999}).encode(),
        ).decode()
        assert auth.revoke_token(f"{payload}.signature") is True
    messages = [
        r.getMessage() for r in caplog.records if r.name == auth.__name__
    ]
    assert len(messages) >= 3
    assert any("alice\\r\\nFORGED" in message for message in messages)
    assert all(
        "\r" not in message and "\n" not in message for message in messages
    )


@pytest.mark.parametrize(
    "stored",
    [
        "pbkdf2_sha256$",
        "pbkdf2_sha256$bad$abc",
        "pbkdf2_sha256$0$abc",
        "pbkdf2_sha256$1$abc",
        "pbkdf2_sha256$999999999999999999999$abc",
        "pbkdf2_sha256$600000$abc$extra",
        "pbkdf2_sha256$600000$非ASCII",
    ],
)
def test_malformed_or_unsafe_password_hash_fails_closed(stored):
    assert auth.verify_password("password", stored, "salt") is False


@pytest.mark.parametrize(
    "stored",
    [
        None,
        123,
        b"a" * 64,
        [],
        {},
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
        "é" * 64,
        "０" * 64,
        "a" * 63 + "\n",
        " a" * 32,
        "sha256$" + "a" * 64,
        "pbkdf2_sha512$600000$" + "a" * 64,
    ],
)
def test_invalid_legacy_hash_rejected_before_sha256(stored, monkeypatch):
    calls = []
    real_sha256 = hashlib.sha256

    def observed_sha256(*args, **kwargs):
        calls.append(args)
        return real_sha256(*args, **kwargs)

    monkeypatch.setattr(auth.hashlib, "sha256", observed_sha256)
    assert auth.verify_password("password", stored, "salt") is False
    assert calls == []


@pytest.mark.parametrize("salt", ["", "任意盐🧂", "x" * 257])
def test_valid_legacy_unicode_password_keeps_arbitrary_salts(salt):
    password = "旧密码 🔑"
    stored = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    assert auth.verify_password(password, stored, salt) is True
    assert auth.verify_password("wrong", stored, salt) is False


def test_concurrent_registration_preserves_single_account(
    auth_store,
    monkeypatch,
):
    first_hash_started = threading.Event()
    release_first_hash = threading.Event()
    second_started = threading.Event()

    def controlled_hash(password):
        if password == "first-password":
            first_hash_started.set()
            assert release_first_hash.wait(5)
        return "test-hash", "test-salt"

    def second_register():
        second_started.set()
        return auth.register_user("second", "second-password")

    monkeypatch.setattr(auth, "_hash_password", controlled_hash)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(auth.register_user, "first", "first-password")
        try:
            assert first_hash_started.wait(5)
            second = pool.submit(second_register)
            assert second_started.wait(5)
            # Registration must serialize through the first account's save.
            with pytest.raises(TimeoutError):
                second.result(timeout=0.2)
        finally:
            release_first_hash.set()
        first_token = first.result(timeout=5)
        assert second.result(timeout=5) is None
    assert auth.verify_token(first_token) == "first"
    assert json.loads(auth_store.read_text())["user"]["username"] == "first"
