# -*- coding: utf-8 -*-
"""Ed25519 detached signature verification for skill ZIP packages."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .constants import DEFAULT_PUBLIC_KEY_PATH, SIGNATURE_SCHEME

_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=]+$")


@dataclass(frozen=True)
class SkillSignatureVerificationResult:
    valid: bool
    signer: str | None
    package_sha256: str
    algorithm: str = "Ed25519"
    scheme: str = SIGNATURE_SCHEME
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "valid": self.valid,
            "signer": self.signer,
            "package_sha256": self.package_sha256,
            "algorithm": self.algorithm,
            "scheme": self.scheme,
        }
        if self.error:
            payload["error"] = self.error
        return payload


def sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def decode_detached_signature(signature_raw: bytes | str) -> bytes:
    """Decode a detached signature from raw bytes or base64 text."""
    if isinstance(signature_raw, bytes):
        text = signature_raw.decode("utf-8", errors="replace").strip()
    else:
        text = signature_raw.strip()

    if not text:
        raise ValueError("Signature file is empty")

    if text.startswith("{"):
        import json

        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("signature"), str):
            text = parsed["signature"].strip()
        else:
            raise ValueError("Unsupported JSON signature envelope")

    normalized = "".join(text.split())
    if not _BASE64_RE.fullmatch(normalized):
        raise ValueError("Signature must be base64-encoded")

    try:
        signature = base64.b64decode(normalized, validate=True)
    except Exception as exc:  # pragma: no cover - base64 validation branch
        raise ValueError("Invalid base64 signature") from exc

    if len(signature) != 64:
        raise ValueError(
            f"Ed25519 signature must be 64 bytes, got {len(signature)}",
        )
    return signature


def load_public_key(
    public_key_path: Path | None = None,
    *,
    pem_bytes: bytes | None = None,
) -> Ed25519PublicKey:
    if pem_bytes is not None:
        raw = pem_bytes
    else:
        path = public_key_path or DEFAULT_PUBLIC_KEY_PATH
        if not path.is_file():
            raise FileNotFoundError(f"Public key not found: {path}")
        raw = path.read_bytes()

    key = serialization.load_pem_public_key(raw.strip())
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("Public key must be Ed25519")
    return key


def verify_skill_package_signature(
    package_data: bytes,
    signature_raw: bytes | str,
    *,
    public_key_path: Path | None = None,
    signer_label: str = "qwenpaw-skill-sign",
) -> SkillSignatureVerificationResult:
    """Verify a detached Ed25519 signature over *package_data* (fail-closed)."""
    package_hash = sha256_hex(package_data)
    try:
        signature = decode_detached_signature(signature_raw)
        public_key = load_public_key(public_key_path)
        public_key.verify(signature, package_data)
        return SkillSignatureVerificationResult(
            valid=True,
            signer=signer_label,
            package_sha256=package_hash,
        )
    except InvalidSignature:
        return SkillSignatureVerificationResult(
            valid=False,
            signer=None,
            package_sha256=package_hash,
            error="Signature verification failed",
        )
    except Exception as exc:
        return SkillSignatureVerificationResult(
            valid=False,
            signer=None,
            package_sha256=package_hash,
            error=str(exc),
        )
