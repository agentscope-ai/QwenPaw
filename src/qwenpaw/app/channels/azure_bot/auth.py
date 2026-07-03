# -*- coding: utf-8 -*-
"""JWT token validation for inbound Azure Bot Service requests."""

from __future__ import annotations

import logging
import time
from typing import Optional

import aiohttp
import jwt
from jwt import PyJWKClient

from .constants import (
    AZURE_BOT_JWKS_CACHE_TTL_S,
    AZURE_BOT_OPENID_METADATA_URL,
)

logger = logging.getLogger(__name__)


class AzureBotTokenValidator:
    """Validate Bearer tokens on inbound Bot Framework requests.

    Bot Framework sends a JWT signed by Microsoft's identity
    platform. We verify:
      - Signature (via JWKS from OpenID metadata)
      - Issuer matches Bot Framework issuers
      - Audience matches our app_id
    """

    # Known Bot Framework token issuers
    _VALID_ISSUERS = (
        "https://api.botframework.com",
        "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/",
        "https://login.microsoftonline.com/d6d49420-f39b-4df7-a1dc-d59a935871db/v2.0",  # noqa: E501
    )

    def __init__(
        self,
        app_id: str,
        tenant_id: str = "",
    ) -> None:
        self._app_id = app_id
        self._tenant_id = tenant_id
        self._jwks_client: Optional[PyJWKClient] = None
        self._jwks_uri: Optional[str] = None
        self._jwks_fetched_at: float = 0.0
        self._openid_config: Optional[dict] = None

    async def _ensure_jwks_client(self) -> None:
        """Lazily fetch OpenID metadata and create JWKS client."""
        now = time.time()
        if (
            self._jwks_client is not None
            and (now - self._jwks_fetched_at) < AZURE_BOT_JWKS_CACHE_TTL_S
        ):
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    AZURE_BOT_OPENID_METADATA_URL,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "azure_bot auth: failed to fetch "
                            "OpenID metadata status=%d",
                            resp.status,
                        )
                        return
                    self._openid_config = await resp.json()

            jwks_uri = self._openid_config.get(
                "jwks_uri",
                "",
            )
            if not jwks_uri:
                logger.warning(
                    "azure_bot auth: no jwks_uri in OpenID metadata",
                )
                return

            self._jwks_uri = jwks_uri
            self._jwks_client = PyJWKClient(jwks_uri)
            self._jwks_fetched_at = now
            logger.debug(
                "azure_bot auth: JWKS client initialized from %s",
                jwks_uri,
            )
        except Exception:
            logger.exception(
                "azure_bot auth: error fetching OpenID metadata",
            )

    async def validate_auth_header(
        self,
        auth_header: str,
    ) -> bool:
        """Validate the Authorization header.

        Args:
            auth_header: Full "Bearer <token>" header value.

        Returns:
            True if the token is valid, False otherwise.
        """
        if not auth_header or not auth_header.startswith(
            "Bearer ",
        ):
            logger.debug(
                "azure_bot auth: missing or malformed auth header",
            )
            return False

        token = auth_header[7:]  # Strip "Bearer "
        await self._ensure_jwks_client()

        if self._jwks_client is None:
            logger.warning(
                "azure_bot auth: JWKS client not available, "
                "rejecting request",
            )
            return False

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(
                token,
            )
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._app_id,
                options={
                    "verify_iss": False,
                    "verify_exp": True,
                },
            )

            # Verify issuer is from Bot Framework
            issuer = claims.get("iss", "")
            if issuer not in self._VALID_ISSUERS:
                # Accept tenant-specific issuers
                if self._tenant_id and self._tenant_id in issuer:
                    pass
                else:
                    logger.warning(
                        "azure_bot auth: unexpected issuer: %s",
                        issuer,
                    )
                    return False

            return True

        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
            logger.debug(
                "azure_bot auth: token error: %s",
                e,
            )
            return False
        except Exception:
            logger.exception(
                "azure_bot auth: unexpected error",
            )
            return False
