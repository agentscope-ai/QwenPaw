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

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
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
        return public_jwk_thumbprint(self.public_jwk())

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


def public_jwk_thumbprint(jwk: Mapping[str, Any]) -> str:
    """Calculate a thumbprint for a validated public Ed25519 JWK."""
    normalized = _validate_public_jwk(jwk)
    canonical = json.dumps(
        normalized,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _base64url_encode(hashlib.sha256(canonical).digest())


def verify_proof(
    proof: str,
    method: str,
    target: str,
    access_token: str,
    nonce: str,
    *,
    expected_thumbprint: str | None = None,
    now: int | None = None,
    max_age_seconds: int = 30,
) -> str:
    """Verify a Relay proof and return its public key thumbprint."""
    parts = proof.split(".")
    if len(parts) != 3 or not all(parts):
        raise RelayProofError("Relay proof is malformed")
    header = _decode_json(parts[0], "header")
    payload = _decode_json(parts[1], "payload")
    if header.get("alg") != "EdDSA" or header.get("typ") != "dpop+jwt":
        raise RelayProofError("Relay proof algorithm or type is invalid")
    jwk = _validate_public_jwk(header.get("jwk"))
    thumbprint = public_jwk_thumbprint(jwk)
    if expected_thumbprint is not None and thumbprint != expected_thumbprint:
        raise RelayProofError("Relay proof key does not match credential")
    expected = {
        "ath": _token_hash(access_token),
        "htm": method.upper(),
        "htu": _canonical_target(target),
        "nonce": nonce,
    }
    for name, expected_value in expected.items():
        if payload.get(name) != expected_value:
            raise RelayProofError(f"Relay proof {name} is invalid")
    issued_at = payload.get("iat")
    if isinstance(issued_at, bool) or not isinstance(issued_at, int):
        raise RelayProofError("Relay proof iat is invalid")
    current_time = int(time.time()) if now is None else now
    if abs(current_time - issued_at) > max_age_seconds:
        raise RelayProofError("Relay proof is outside its time window")
    proof_id = payload.get("jti")
    if not isinstance(proof_id, str) or not proof_id:
        raise RelayProofError("Relay proof jti is invalid")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            _base64url_decode(jwk["x"]),
        )
        public_key.verify(
            _base64url_decode(parts[2]),
            f"{parts[0]}.{parts[1]}".encode("ascii"),
        )
    except (InvalidSignature, ValueError) as exc:
        raise RelayProofError("Relay proof signature is invalid") from exc
    return thumbprint


def _validate_public_jwk(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise RelayProofError("Relay proof public key is missing")
    if value.get("kty") != "OKP" or value.get("crv") != "Ed25519":
        raise RelayProofError("Relay proof public key type is invalid")
    encoded_key = value.get("x")
    if not isinstance(encoded_key, str):
        raise RelayProofError("Relay proof public key is invalid")
    try:
        raw_key = _base64url_decode(encoded_key)
    except ValueError as exc:
        raise RelayProofError("Relay proof public key is invalid") from exc
    if len(raw_key) != 32:
        raise RelayProofError("Relay proof public key is invalid")
    return {"crv": "Ed25519", "kty": "OKP", "x": encoded_key}


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


def _decode_json(value: str, name: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_base64url_decode(value))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RelayProofError(f"Relay proof {name} is invalid") from exc
    if not isinstance(decoded, dict):
        raise RelayProofError(f"Relay proof {name} is invalid")
    return decoded


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")
