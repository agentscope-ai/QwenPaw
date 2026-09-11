# -*- coding: utf-8 -*-
"""Tests for QR-code auth helper pure functions.

Covers the poll-token encode/decode round-trip, the AES-256-GCM secret
decryption helper (valid ciphertext, too-short rejection, tamper
rejection), and QR code image generation, which were previously
untested.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import base64
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

from qwenpaw.app.channels.qrcode_auth_handler import (
    _decode_poll_token,
    _decrypt_secret,
    _encode_poll_token,
    generate_qrcode_image,
)


# ---------------------------------------------------------------------------
# poll token codec
# ---------------------------------------------------------------------------


class TestPollTokenCodec:
    def test_round_trip(self):
        token = _encode_poll_token("task-1", "aes-key-xyz")
        task_id, aes_key = _decode_poll_token(token)
        assert task_id == "task-1"
        assert aes_key == "aes-key-xyz"

    def test_round_trip_with_special_characters(self):
        token = _encode_poll_token("task/with spaces+chars", "k==/++")
        task_id, aes_key = _decode_poll_token(token)
        assert task_id == "task/with spaces+chars"
        assert aes_key == "k==/++"

    def test_invalid_base64_raises(self):
        with pytest.raises(ValueError, match="Invalid poll token"):
            _decode_poll_token("!!!not-base64!!!")

    def test_non_json_payload_raises(self):
        token = base64.urlsafe_b64encode(b"not json").decode()
        with pytest.raises(ValueError, match="Invalid poll token"):
            _decode_poll_token(token)

    def test_missing_key_raises(self):
        payload = base64.urlsafe_b64encode(b'{"task_id": "t"}').decode()
        with pytest.raises(ValueError, match="Invalid poll token"):
            _decode_poll_token(payload)


# ---------------------------------------------------------------------------
# _decrypt_secret (AES-256-GCM)
# ---------------------------------------------------------------------------


def _encrypt_to_base64(
    plaintext: bytes,
    key: bytes,
    associated_data: bytes | None = None,
) -> str:
    iv = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(iv, plaintext, associated_data)
    return base64.b64encode(iv + ciphertext).decode()


class TestDecryptSecret:
    def test_round_trip(self):
        key = os.urandom(32)
        encrypted = _encrypt_to_base64(b"super secret", key)
        result = _decrypt_secret(
            encrypted,
            base64.b64encode(key).decode(),
        )
        assert result == "super secret"

    def test_round_trip_with_associated_data(self):
        key = os.urandom(32)
        encrypted = _encrypt_to_base64(b"secret", key, b"aad")
        result = _decrypt_secret(
            encrypted,
            base64.b64encode(key).decode(),
            associated_data=b"aad",
        )
        assert result == "secret"

    def test_utf8_content(self):
        key = os.urandom(32)
        encrypted = _encrypt_to_base64("中文内容".encode("utf-8"), key)
        result = _decrypt_secret(
            encrypted,
            base64.b64encode(key).decode(),
        )
        assert result == "中文内容"

    def test_too_short_ciphertext_rejected(self):
        key = os.urandom(32)
        short = base64.b64encode(b"x" * 20).decode()
        with pytest.raises(ValueError, match="too short"):
            _decrypt_secret(short, base64.b64encode(key).decode())

    def test_tampered_ciphertext_rejected(self):
        key = os.urandom(32)
        encrypted = _encrypt_to_base64(b"secret", key)
        raw = bytearray(base64.b64decode(encrypted))
        raw[-1] ^= 0xFF  # flip a bit in the auth tag
        tampered = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(Exception):
            _decrypt_secret(tampered, base64.b64encode(key).decode())

    def test_wrong_associated_data_rejected(self):
        key = os.urandom(32)
        encrypted = _encrypt_to_base64(b"secret", key, b"aad")
        with pytest.raises(Exception):
            _decrypt_secret(
                encrypted,
                base64.b64encode(key).decode(),
                associated_data=b"wrong",
            )


# ---------------------------------------------------------------------------
# generate_qrcode_image
# ---------------------------------------------------------------------------


class TestGenerateQrcodeImage:
    def test_returns_valid_png_base64(self):
        result = generate_qrcode_image("https://example.com/scan")
        raw = base64.b64decode(result)
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"

    def test_deterministic_for_same_url(self):
        assert generate_qrcode_image("u1") == generate_qrcode_image("u1")

    def test_generation_failure_raises_500(self, monkeypatch):
        import segno

        def boom(*args, **kwargs):
            raise RuntimeError("segno broken")

        monkeypatch.setattr(segno, "make", boom)
        with pytest.raises(HTTPException) as exc_info:
            generate_qrcode_image("https://example.com")
        assert exc_info.value.status_code == 500
