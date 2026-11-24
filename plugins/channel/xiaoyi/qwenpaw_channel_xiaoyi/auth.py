# -*- coding: utf-8 -*-
"""
XiaoYi authentication using AK/SK mechanism.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Dict


def generate_signature(sk: str, timestamp: str) -> str:
    """Generate HMAC-SHA256 signature.

    Format: Base64(HMAC-SHA256(secretKey, timestamp))

    Args:
        sk: Secret Key
        timestamp: Timestamp as string (milliseconds)

    Returns:
        Base64 encoded signature
    """
    hmac_obj = hmac.new(sk.encode(), timestamp.encode(), hashlib.sha256)
    return base64.b64encode(hmac_obj.digest()).decode()


def generate_auth_headers(ak: str, sk: str, agent_id: str) -> Dict[str, str]:
    """Generate WebSocket authentication headers.

    Args:
        ak: Access Key
        sk: Secret Key
        agent_id: Agent ID

    Returns:
        Dict of headers for WebSocket connection
    """
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(sk, timestamp)

    return {
        "x-access-key": ak,
        "x-sign": signature,
        "x-ts": timestamp,
        "x-agent-id": agent_id,
    }
