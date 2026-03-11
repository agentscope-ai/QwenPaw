# -*- coding: utf-8 -*-
"""Feishu (Lark) Webhook Router.

Handles Feishu event subscriptions via HTTP webhook.
Supports challenge verification, signature verification, and event dispatching.
Reference: https://open.feishu.cn/document/ukTMukTMukTM/
uYDNxYjL2QTM24iN0EjN/event-subscription-guide
"""

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Tuple

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_signature(
    encrypt_key: str,
    timestamp: str,
    nonce: str,
    body: str,
    expected_signature: str,
) -> bool:
    """Verify Feishu webhook request signature.

    Args:
        encrypt_key: The encryption key configured in Feishu app
        timestamp: Request timestamp from header
        nonce: Request nonce from header
        body: Raw request body
        expected_signature: Expected signature from header

    Returns:
        True if signature is valid, False otherwise

    Reference: https://open.larksuite.com/document/server-docs/
        event-subscription/event-subscription-configure-/
        encrypt-key-encryption-configuration-case
    Algorithm: SHA256(timestamp + nonce + encrypt_key + body), output as hex
    """
    if not encrypt_key:
        logger.warning(
            "No encrypt_key configured, skipping signature verification",
        )
        return True

    # Lark signature algorithm:
    # SHA256(timestamp + nonce + encrypt_key + body)
    # Note: This is NOT HMAC, just a simple SHA256 hash
    content = f"{timestamp}{nonce}{encrypt_key}{body}"
    computed = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Debug logging - use info level for troubleshooting
    is_valid = hmac.compare_digest(computed, expected_signature)
    if is_valid:
        logger.info(f"Signature verification PASSED for timestamp={timestamp}")
    else:
        logger.warning(
            "Signature verification FAILED: "
            f"timestamp={timestamp}, nonce={nonce}, "
            f"key_prefix={encrypt_key[:8]}..., "
            f"body_len={len(body)}, "
            f"computed={computed[:20]}..., "
            f"expected={expected_signature[:20]}...",
        )

    return is_valid


def decrypt_body(encrypt_key: str, encrypted_body: str) -> str:
    """Decrypt Feishu/Lark webhook payload using AES-256-CBC.

    Args:
        encrypt_key: The encryption key from Lark developer console
        encrypted_body: Base64-encoded encrypted payload

    Returns:
        Decrypted JSON string

    Reference: https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/
               event-subscription-guide/event-subscriptions/encrypt-keys
    """
    if not encrypted_body:
        return ""

    try:
        # Try to import cryptography for AES decryption
        from cryptography.hazmat.primitives.ciphers import (
            Cipher,
            algorithms,
            modes,
        )
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        logger.error(
            "cryptography package is required for webhook decryption. "
            "Install with: pip install cryptography",
        )
        raise RuntimeError(
            "cryptography package required for Lark webhook decryption",
        ) from None

    # Decode the base64 encrypted body
    encrypted_bytes = base64.b64decode(encrypted_body)

    # Derive AES key from encrypt_key using SHA-256
    # Lark uses the first 32 bytes of SHA256(encrypt_key) as the AES key
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()

    # Extract IV (first 16 bytes) and ciphertext
    # Lark format: IV (16 bytes) + ciphertext + padding
    iv = encrypted_bytes[:16]
    ciphertext = encrypted_bytes[16:]

    # Create AES-256-CBC cipher
    cipher = Cipher(
        algorithms.AES(key),
        modes.CBC(iv),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()

    # Decrypt
    padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    # Remove PKCS7 padding
    padding_len = padded_plaintext[-1]
    plaintext = padded_plaintext[:-padding_len]

    return plaintext.decode("utf-8")


def _get_feishu_config():
    """Load and return Feishu configuration."""
    from ...config.utils import load_config

    config = load_config()
    return config.channels.feishu


def _get_signature_key(feishu_config) -> str:
    """Get signature key from config."""
    return (
        feishu_config.webhook_encrypt_key
        or feishu_config.encrypt_key
        or feishu_config.webhook_verification_token
        or feishu_config.verification_token
    )


def _decrypt_payload_if_needed(
    payload: Dict[str, Any],
    feishu_config,
) -> Tuple[Dict[str, Any], bool]:
    """Decrypt payload if encrypted.

    Returns:
        Tuple of (decrypted_payload, is_url_verification).
    """
    is_url_verification = payload.get("type") == "url_verification"

    if "encrypt" not in payload:
        return payload, is_url_verification

    encrypt_key = (
        getattr(feishu_config, "webhook_encrypt_key", None)
        or getattr(feishu_config, "encrypt_key", None)
        or getattr(feishu_config, "verification_token", None)
    )

    if not encrypt_key:
        return payload, is_url_verification

    try:
        decrypted = decrypt_body(encrypt_key, payload["encrypt"])
        payload = json.loads(decrypted)
        logger.info("Successfully decrypted webhook payload")
        is_url_verification = payload.get("type") == "url_verification"
        return payload, is_url_verification
    except Exception as e:
        logger.error(f"Failed to decrypt webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decryption failed",
        ) from e


def _verify_webhook_signature(
    feishu_config,
    timestamp: str,
    nonce: str,
    body_str: str,
    signature: str,
) -> None:
    """Verify webhook signature, raise HTTPException if invalid."""
    skip_sig = getattr(feishu_config, "webhook_skip_signature_verify", False)
    if skip_sig:
        logger.warning(
            "Skipping signature verification "
            "(webhook_skip_signature_verify is enabled)",
        )
        return

    signature_key = _get_signature_key(feishu_config)
    if not signature_key or not signature:
        return

    is_valid = verify_signature(
        signature_key,
        timestamp,
        nonce,
        body_str,
        signature,
    )

    if is_valid:
        return

    # Try using verification_token as fallback
    verification_key = (
        feishu_config.webhook_verification_token
        or feishu_config.verification_token
    )
    if verification_key and verification_key != signature_key:
        is_valid = verify_signature(
            verification_key,
            timestamp,
            nonce,
            body_str,
            signature,
        )
        if is_valid:
            logger.info("Signature verified using verification_token")
            return

    logger.error(
        f"Webhook signature verification failed. "
        f"Timestamp: {timestamp}, Nonce: {nonce}, "
        f"Signature key prefix: {signature_key[:8]}..., "
        f"Body length: {len(body_str)}",
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid signature",
    )


def _find_feishu_channel(request: Request):
    """Find FeishuChannel instance from channel manager."""
    cm = getattr(request.app.state, "channel_manager", None)
    if cm is None:
        logger.error("Channel manager not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Channel manager not ready",
        )

    if hasattr(cm, "channels"):
        channels = cm.channels
        if isinstance(channels, dict):
            channel_iter = channels.values()
        else:
            channel_iter = channels
        for ch in channel_iter:
            if getattr(ch, "channel", None) == "feishu":
                return ch

    logger.error("Feishu channel not found")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Feishu channel not available",
    )


@router.post("/webhook/feishu")
async def handle_feishu_webhook(request: Request) -> JSONResponse:
    """Handle Feishu webhook events.

    Handles:
    1. URL verification (challenge response)
    2. Event callbacks with signature verification
    3. Message dispatching to FeishuChannel
    """
    # Get request headers for verification
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")

    # Read raw body
    body = await request.body()
    body_str = body.decode("utf-8")

    # Debug logging for troubleshooting
    logger.info(
        f"Feishu webhook request: timestamp={timestamp}, nonce={nonce}, "
        f"signature={signature[:30] if signature else 'None'}..., "
        f"body_len={len(body_str)}",
    )
    logger.info("Feishu webhook full body for debug: %s", body_str)

    # Parse JSON payload
    try:
        payload: Dict[str, Any] = json.loads(body_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from e

    # Get config for decryption and verification
    feishu_config = _get_feishu_config()

    # Handle decryption if needed
    payload, is_url_verification = _decrypt_payload_if_needed(
        payload,
        feishu_config,
    )

    # Handle URL verification
    if is_url_verification:
        challenge = payload.get("challenge")
        logger.info(f"Feishu webhook URL verification, challenge: {challenge}")
        return JSONResponse(
            content={"challenge": challenge},
            status_code=status.HTTP_200_OK,
        )

    # Check if webhook is enabled
    if not feishu_config.webhook_enabled:
        logger.warning("Feishu webhook is disabled in config")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook not enabled",
        )

    # Verify signature
    _verify_webhook_signature(
        feishu_config,
        timestamp,
        nonce,
        body_str,
        signature,
    )

    # Log event info
    header = payload.get("header", {})
    event_id = header.get("event_id", "")
    logger.debug(f"Received Feishu webhook event: {event_id}")

    # Find FeishuChannel and dispatch event
    feishu_channel = _find_feishu_channel(request)

    try:
        await feishu_channel.handle_webhook_event(payload)
    except Exception as e:
        logger.exception(f"Error handling webhook event: {e}")
        # Return 200 to prevent Feishu from retrying

    return JSONResponse(
        content={"code": 0, "msg": "success"},
        status_code=status.HTTP_200_OK,
    )


@router.get("/webhook/feishu/health")
async def feishu_webhook_health(request: Request) -> JSONResponse:
    """Health check endpoint for Feishu webhook."""
    cm = getattr(request.app.state, "channel_manager", None)
    return JSONResponse(
        content={
            "status": "ok",
            "webhook_enabled": cm is not None,
        },
        status_code=status.HTTP_200_OK,
    )
