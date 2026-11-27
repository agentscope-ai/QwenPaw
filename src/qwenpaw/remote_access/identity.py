# -*- coding: utf-8 -*-
"""Proof-of-possession primitives for QwenPaw Relay clients."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)


class RelayProofError(ValueError):
    """Raised when a Relay proof-of-possession check fails."""


@dataclass(frozen=True, slots=True)
class RelayKeyPair:
    """An Ed25519 key pair used to bind a Relay client credential."""

    private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> RelayKeyPair:
        """Generate a new Relay signing key pair."""
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_private_bytes(cls, value: bytes) -> RelayKeyPair:
        """Restore a key pair from its 32-byte private representation."""
        return cls(Ed25519PrivateKey.from_private_bytes(value))

    def private_bytes(self) -> bytes:
        """Return the raw private representation for protected persistence."""
        return self.private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )

    def public_jwk(self) -> dict[str, str]:
        """Return the public key as a minimal Ed25519 JWK."""
        value = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        return {
            "crv": "Ed25519",
            "kty": "OKP",
            "x": _base64url_encode(value),
        }

    def thumbprint(self) -> str:
        """Return the RFC 7638 SHA-256 public JWK thumbprint."""
        canonical = json.dumps(
            self.public_jwk(),
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return _base64url_encode(hashlib.sha256(canonical).digest())

    def create_proof(
        self,
        method: str,
        target: str,
        access_token: str,
        nonce: str,
        *,
        issued_at: int | None = None,
        proof_id: str | None = None,
    ) -> str:
        """Create a compact DPoP-style proof bound to an access token."""
        header = {
            "alg": "EdDSA",
            "jwk": self.public_jwk(),
            "typ": "dpop+jwt",
        }
        payload = {
            "ath": _token_hash(access_token),
            "htm": method.upper(),
            "htu": _canonical_target(target),
            "iat": int(time.time()) if issued_at is None else issued_at,
            "jti": proof_id or str(uuid.uuid4()),
            "nonce": nonce,
        }
        signing_input = (
            f"{_encode_json(header)}.{_encode_json(payload)}"
        ).encode("ascii")
        signature = self.private_key.sign(signing_input)
        return (
            f"{signing_input.decode('ascii')}.{_base64url_encode(signature)}"
        )


def _canonical_target(target: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme not in {"https", "wss", "http", "ws"}:
        raise RelayProofError("Relay proof target scheme is invalid")
    host = parsed.hostname
    if not host or parsed.username or parsed.password or parsed.fragment:
        raise RelayProofError("Relay proof target is invalid")
    port = parsed.port
    default_port = {"http": 80, "ws": 80, "https": 443, "wss": 443}
    netloc = host.lower()
    if ":" in netloc:
        netloc = f"[{netloc}]"
    if port is not None and port != default_port[parsed.scheme]:
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def _token_hash(token: str) -> str:
    return _base64url_encode(hashlib.sha256(token.encode("utf-8")).digest())


def _encode_json(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _base64url_encode(raw)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
