# -*- coding: utf-8 -*-
"""Gateway Token Provider: AK-SK → Bearer Token.

Calls aliyun CLI to exchange Alibaba Cloud AK-SK credentials
for a Bearer Token used by the intelligent gateway A2A endpoint.
Supports token caching and automatic refresh.
"""

import asyncio
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_TOKEN_REFRESH_MARGIN_SECONDS = 300  # refresh 5 min before expiry


class GatewayTokenProvider:
    """Exchange AK-SK for a Bearer Token via aliyun CLI.

    The token is cached and refreshed automatically when expired.
    """

    def __init__(
        self,
        ak: str = "",
        sk: str = "",
        client_id: str = "4081417976505782102",
        scope: str = "/internal/agenthub",
        endpoint: str = "ramoauth.aliyuncs.com",
    ):
        self._ak = ak or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
        self._sk = sk or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
        self._client_id = client_id
        self._scope = scope
        self._endpoint = endpoint
        self._cached_token: str = ""
        self._token_expire_at: float = 0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Get a valid Bearer Token, refreshing if expired."""
        async with self._lock:
            if self._cached_token and time.time() < self._token_expire_at:
                return self._cached_token
            return await self._refresh_token()

    def invalidate(self) -> None:
        """Force clear the cached token."""
        self._cached_token = ""
        self._token_expire_at = 0

    async def _refresh_token(self) -> str:
        if not self._ak or not self._sk:
            raise RuntimeError(
                "ALIBABA_CLOUD_ACCESS_KEY_ID / SECRET not configured",
            )

        cmd = [
            "aliyun",
            "ramoauth",
            "GenerateAccessToken",
            "--ClientId",
            self._client_id,
            "--endpoint",
            self._endpoint,
            "--version",
            "2026-04-21",
            "--access-key-id",
            self._ak,
            "--access-key-secret",
            self._sk,
            "--method",
            "POST",
            "--force",
            "--Scope",
            self._scope,
        ]

        logger.info("Refreshing gateway token via aliyun CLI...")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = (stderr or stdout).decode().strip()
            raise RuntimeError(
                f"Token refresh failed (exit={proc.returncode}): {err_msg}",
            )

        data = json.loads(stdout.decode())
        d = data.get("Data") or data
        token = d.get("AccessToken", d.get("access_token", ""))
        if not token:
            raise RuntimeError(
                f"No AccessToken in response: {stdout.decode()[:500]}",
            )

        expires_in = int(d.get("ExpiresIn", 3600))
        self._cached_token = token
        self._token_expire_at = (
            time.time() + expires_in - _TOKEN_REFRESH_MARGIN_SECONDS
        )

        logger.info(
            "Gateway token refreshed (length=%d, expires_in=%ds)",
            len(token),
            expires_in,
        )
        return token
