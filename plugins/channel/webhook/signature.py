# -*- coding: utf-8 -*-
"""HMAC-SHA256 signature verification for incoming webhook requests."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-QwenPaw-Signature"
SIGNATURE_PREFIX = "sha256="
_HEX_RE = __import__("re").compile(r"^[0-9a-fA-F]+$")


def verify_signature(
    body: bytes,
    signature: Optional[str],
    secret: Optional[str],
) -> bool:
    """Verify an HMAC-SHA256 webhook signature.

    Args:
        body: Raw request body bytes.
        signature: Value of the ``X-QwenPaw-Signature`` header, in the
            form ``sha256=<hex>``. May be ``None`` when the sender does
            not include the header.
        secret: Shared secret configured on the channel. May be ``None``
            when the channel accepts unsigned requests (not recommended
            on a public endpoint).

    Returns:
        ``True`` if the channel is configured without a secret
        (accepts everything), or when the supplied signature matches
        the body. ``False`` when a secret is configured but the
        request arrives unsigned, or when the supplied signature does
        not match.

        Security note: when ``secret`` is set, an unsigned request is
        always rejected. The previous permissive default (accept
        unsigned requests even with a secret) was removed because it
        effectively disabled signature enforcement on any caller that
        omitted the header.
    """
    if secret is None:
        # No secret configured — accept everything. This preserves
        # backwards compatibility for deployments that rely on
        # network-level isolation (e.g. binding to 127.0.0.1). New
        # deployments exposing the listener publicly should always
        # configure a secret.
        return True
    if signature is None or signature == "":
        logger.warning(
            "webhook received without signature header while a "
            "secret is configured; rejecting",
        )
        return False
    if not signature.startswith(SIGNATURE_PREFIX):
        logger.warning("webhook signature missing sha256= prefix")
        return False
    hex_part = signature[len(SIGNATURE_PREFIX) :]
    if not hex_part or not _HEX_RE.match(hex_part):
        logger.warning("webhook signature contains non-hex characters")
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, hex_part.lower())
