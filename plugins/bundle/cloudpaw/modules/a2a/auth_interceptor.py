# -*- coding: utf-8 -*-
"""Auth token injection helpers for A2A requests.

Provides simple functions for building auth headers instead of SDK
interceptors. Used by A2AClientManager to inject Bearer Token into
httpx requests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gateway_token import GatewayTokenProvider


async def get_auth_headers(
    auth_type: str,
    auth_token: str = "",
    token_provider: "GatewayTokenProvider | None" = None,
) -> dict[str, str]:
    """Build Authorization headers based on auth type.

    Args:
        auth_type: "bearer", "api_key", "gateway", or "".
        auth_token: Static token for bearer/api_key.
        token_provider: Dynamic provider for gateway mode.

    Returns:
        Dict of HTTP headers to merge into requests.
    """
    if auth_type == "gateway" and token_provider:
        token = await token_provider.get_token()
        return {"Authorization": f"Bearer {token}"}
    if auth_type in ("bearer", "api_key") and auth_token:
        return {"Authorization": f"Bearer {auth_token}"}
    return {}
