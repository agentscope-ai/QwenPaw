# -*- coding: utf-8 -*-
"""Host wiring for skill package signature verification."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_PRIVATE_KEY_PATH,
    DEFAULT_PUBLIC_KEY_PATH,
    SIGNATURE_SCHEME,
    SIGN_TOOL_DIR,
)
from .verifier import (
    SkillSignatureVerificationResult,
    decode_detached_signature,
    load_public_key,
    sha256_hex,
    verify_skill_package_signature,
)


def get_sign_tool_dir() -> Path:
    return SIGN_TOOL_DIR


def get_default_public_key_path() -> Path:
    return DEFAULT_PUBLIC_KEY_PATH


def get_default_private_key_path() -> Path:
    return DEFAULT_PRIVATE_KEY_PATH


def verify_skill_package(
    package_data: bytes,
    signature_raw: bytes | str,
    *,
    public_key_path: Path | None = None,
) -> dict[str, Any]:
    return verify_skill_package_signature(
        package_data,
        signature_raw,
        public_key_path=public_key_path,
    ).to_dict()


def get_router():
    """Return the FastAPI router for skill pool secure import."""

    from .routes import router

    return router


__all__ = [
    "DEFAULT_PRIVATE_KEY_PATH",
    "DEFAULT_PUBLIC_KEY_PATH",
    "SIGNATURE_SCHEME",
    "SIGN_TOOL_DIR",
    "SkillSignatureVerificationResult",
    "decode_detached_signature",
    "get_default_private_key_path",
    "get_default_public_key_path",
    "get_router",
    "get_sign_tool_dir",
    "load_public_key",
    "sha256_hex",
    "verify_skill_package",
    "verify_skill_package_signature",
]
