# -*- coding: utf-8 -*-
"""Utility functions for Nextcloud Talk channel."""


import hashlib
import hmac
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Dict, Any

from .constants import (
    SIGNATURE_LENGTH,
    RANDOM_LENGTH,
    BOT_HEADER_RANDOM,
    BOT_HEADER_SIGNATURE,
    OCS_API_REQUEST_HEADER,
)

logger = logging.getLogger(__name__)


def verify_request_signature(
    body: bytes,
    signature_header: str,
    random_header: str,
    secret: str,
) -> bool:
    """
    Verify HMAC-SHA256 signature for incoming webhook request.

    Args:
        body: Raw request body (bytes)
        signature_header: Value from X-Nextcloud-Talk-Signature header
        random_header: Value from X-Nextcloud-Talk-Random header
        secret: Shared secret configured for the bot

    Returns:
        True if signature is valid, False otherwise
    """
    if not signature_header or not random_header:
        logger.warning("Missing signature or random header")
        return False

    # Validate lengths
    if len(signature_header) != SIGNATURE_LENGTH:
        logger.warning(f"Invalid signature length: {len(signature_header)}")
        return False

    if len(random_header) != RANDOM_LENGTH:
        logger.warning(f"Invalid random length: {len(random_header)}")
        return False

    try:
        # Calculate expected signature
        # Signature is HMAC-SHA256 of RANDOM + BODY (Nextcloud Talk spec)
        # Verified by actual testing: RANDOM+BODY matches, BODY+RANDOM doesn't
        message_to_sign = random_header.encode("utf-8") + body

        expected_digest = hmac.new(
            secret.encode("utf-8"),
            message_to_sign,
            hashlib.sha256,
        ).hexdigest()

        # Compare using constant-time comparison
        is_valid = hmac.compare_digest(
            signature_header.lower(),
            expected_digest.lower(),
        )

        if not is_valid:
            logger.warning("Signature verification failed")

        return is_valid

    except Exception as e:
        logger.exception(f"Signature verification error: {e}")
        return False


def generate_bot_signature(
    message_text: str,
    secret: str,
) -> tuple[str, str]:
    """
    Generate HMAC-SHA256 signature for outgoing bot request.

    Args:
        message_text: The message text value (not the full JSON body)
        secret: Shared secret configured for the bot

    Returns:
        Tuple of (random_value, signature)
    """
    # Generate random value
    random_value = secrets.token_hex(32)

    # Calculate signature using random + message text (not full JSON body)
    # This matches Nextcloud Talk Bot API verification logic
    message_to_sign = random_value + message_text

    signature = hmac.new(
        secret.encode("utf-8"),
        message_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return (random_value, signature)


def normalize_nextcloud_url(url: str) -> str:
    """
    Normalize Nextcloud base URL, ensuring it has a trailing slash.
    """
    if not url:
        return ""
    url = url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        # Assume https if not specified
        url = "https://" + url
    return url + "/"


def get_config_path() -> Path:
    """Get the CoPaw config directory path."""
    config_home = os.environ.get("CO_AW_CONFIG_HOME")
    if config_home:
        return Path(config_home)
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home) / ".copaw"
    return Path.home() / ".copaw"


def get_token_store_path() -> Path:
    """Get the path to the bot token store file."""
    config_path = get_config_path()
    return config_path / "nextcloud_talk_tokens.json"


def load_token_store() -> Dict[str, Any]:
    """Load bot token store from disk."""
    path = get_token_store_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning(f"Failed to load token store from {path}")
        return {}


def save_token_store(store: Dict[str, Any]) -> None:
    """Save bot token store to disk."""
    path = get_token_store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to save token store to {path}: {e}")


def extract_backend_url(backend_header: str) -> str:
    """
    Extract and normalize backend URL from header.
    """
    return normalize_nextcloud_url(backend_header)


def build_bot_headers(
    secret: str,
    message_text: str,
) -> Dict[str, str]:
    """
    Build headers for outgoing bot API request.

    Args:
        secret: Shared secret configured for the bot
        message_text: The message text value (not the full JSON body)

    Returns:
        Dictionary with X-Nextcloud-Talk-Bot-Random,
        X-Nextcloud-Talk-Bot-Signature, and OCS-APIRequest headers
    """
    random_val, signature = generate_bot_signature(message_text, secret)

    return {
        BOT_HEADER_RANDOM: random_val,
        BOT_HEADER_SIGNATURE: signature,
        OCS_API_REQUEST_HEADER: "true",
    }
