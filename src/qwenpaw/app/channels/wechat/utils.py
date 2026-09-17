# -*- coding: utf-8 -*-
"""WeChat iLink channel utilities."""

from __future__ import annotations

import base64
import secrets
from typing import Dict


def make_headers(bot_token: str = "") -> Dict[str, str]:
    """Build iLink API request headers.

    X-WECHAT-UIN: base64(str(random_uint32)) — anti-replay, per request.
    Authorization: Bearer <bot_token> — only set when token is available.
    """
    uin_val = secrets.randbelow(0xFFFFFFFF)
    uin_b64 = base64.b64encode(str(uin_val).encode()).decode()
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": uin_b64,
    }
    if bot_token:
        headers["Authorization"] = f"Bearer {bot_token}"
    return headers


def aes_ecb_decrypt(data: bytes, key_b64: str) -> bytes:
    """Decrypt AES-128-ECB encrypted bytes.

    Args:
        data: Encrypted bytes (from CDN).
        key_b64: AES key — accepts three formats:
            - Base64-encoded bytes (standard, e.g. from media.aes_key decoded)
            - Hex string (32 chars = 16 bytes, e.g. image_item.aeskey field)
            - Raw 16/24/32-byte string (passed through directly)

    Returns:
        Decrypted bytes with PKCS7 padding removed.

    Raises:
        ImportError: If pycryptodome is not installed.
        ValueError: If key length is invalid.
    """
    try:
        from Crypto.Cipher import AES  # pycryptodome
    except ImportError as exc:
        raise ImportError(
            "pycryptodome is required for WeChat media decryption. "
            "Install with: pip install pycryptodome",
        ) from exc

    # Auto-detect key format (mirrors official TypeScript parseAesKey logic)
    key: bytes
    raw = key_b64.strip()
    if len(raw) in (32, 48, 64) and all(
        c in "0123456789abcdefABCDEF" for c in raw
    ):
        # Format: raw hex string (e.g. image_item.aeskey — 32 hex chars)
        key = bytes.fromhex(raw)
    else:
        # Format: base64-encoded — base64(16 raw bytes) or base64(32-char hex)
        try:
            decoded = base64.b64decode(raw + "==")
        except Exception:
            decoded = raw.encode()
        if len(decoded) == 16:
            # Format A: base64(raw 16 bytes) — used by images
            key = decoded
        elif len(decoded) == 32 and all(
            c in b"0123456789abcdefABCDEF" for c in decoded
        ):
            # Format B: base64(hex string) — used by file/voice/video
            key = bytes.fromhex(decoded.decode("ascii"))
        else:
            key = decoded

    if len(key) not in (16, 24, 32):
        raise ValueError(
            f"Invalid AES key length: {len(key)} (from key_b64={raw[:20]!r})",
        )
    cipher = AES.new(key, AES.MODE_ECB)
    decrypted = cipher.decrypt(data)
    # Remove PKCS7 padding using pycryptodome's validated unpad
    from Crypto.Util.Padding import unpad

    return unpad(decrypted, AES.block_size)


def aes_ecb_encrypt(data: bytes, key_b64: str) -> bytes:
    """Encrypt bytes with AES-128-ECB + PKCS7 padding.

    Args:
        data: Plain bytes to encrypt.
        key_b64: Base64-encoded 16-byte AES key.

    Returns:
        Encrypted bytes.
    """
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
    except ImportError as exc:
        raise ImportError(
            "pycryptodome is required for WeChat media encryption. "
            "Install with: pip install pycryptodome",
        ) from exc

    key = base64.b64decode(key_b64)
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(pad(data, AES.block_size))


def generate_aes_key_b64() -> str:
    """Generate a cryptographically secure random 16-byte AES key.

    Returns:
        Base64-encoded 16-byte AES key.
    """
    key = secrets.token_bytes(16)
    return base64.b64encode(key).decode()
