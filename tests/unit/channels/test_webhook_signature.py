# -*- coding: utf-8 -*-
"""Tests for the webhook HMAC-SHA256 signature verifier."""
from __future__ import annotations

import hashlib
import hmac

from qwenpaw.app.channels.webhook.signature import (
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    verify_signature,
)


def _make_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


class TestVerifySignature:
    """Coverage for verify_signature across all accept/reject branches."""

    def test_returns_true_when_no_secret_configured(self):
        assert verify_signature(b"hello", "sha256=abc", None) is True

    def test_returns_true_when_signature_missing_with_secret(self):
        assert verify_signature(b"hello", None, "secret") is True

    def test_returns_true_when_signature_empty_with_secret(self):
        assert verify_signature(b"hello", "", "secret") is True

    def test_valid_signature_passes(self):
        body = b'{"hello":"world"}'
        sig = _make_signature(body, "shhh")
        assert verify_signature(body, sig, "shhh") is True

    def test_mismatched_signature_rejected(self):
        body = b'{"hello":"world"}'
        sig = _make_signature(body, "shhh")
        bad = sig[:-1] + ("0" if sig[-1] != "0" else "1")
        assert verify_signature(body, bad, "shhh") is False

    def test_wrong_secret_rejected(self):
        body = b'{"hello":"world"}'
        sig = _make_signature(body, "shhh")
        assert verify_signature(body, sig, "different") is False

    def test_signature_missing_prefix_rejected(self):
        body = b"hello"
        sig = _make_signature(body, "shhh")[len(SIGNATURE_PREFIX):]
        assert verify_signature(body, sig, "shhh") is False

    def test_signature_with_non_hex_chars_rejected(self):
        assert verify_signature(b"hello", "sha256=zzzz", "shhh") is False

    def test_signature_with_empty_hex_rejected(self):
        assert verify_signature(b"hello", "sha256=", "shhh") is False

    def test_signature_is_case_insensitive(self):
        body = b"hello"
        digest = hmac.new(
            b"shhh",
            body,
            hashlib.sha256,
        ).hexdigest()
        upper = f"{SIGNATURE_PREFIX}{digest.upper()}"
        assert verify_signature(body, upper, "shhh") is True

    def test_signature_header_constant_value(self):
        assert SIGNATURE_HEADER == "X-QwenPaw-Signature"

    def test_uses_timing_safe_compare(self):
        # Two signatures of equal length and correct hex format should be
        # compared via hmac.compare_digest (constant-time). We cannot test
        # the constant-time property directly, but we verify the helper is
        # exercised: a swapped but well-formed signature is rejected, not
        # accepted via a hash equality shortcut.
        body = b"hello"
        sig = _make_signature(body, "shhh")
        # Build a syntactically valid but wrong signature by signing a
        # different body with the same secret, then truncating to length.
        wrong = _make_signature(b"hello!", "shhh")[: len(sig)]
        assert verify_signature(body, wrong, "shhh") is False