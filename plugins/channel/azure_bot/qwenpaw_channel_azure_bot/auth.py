# -*- coding: utf-8 -*-
"""Connector JWT authentication; no untrusted tenant/issuer substring matching."""

import asyncio
import json
import time
from urllib.parse import urlsplit

import aiohttp
import jwt

from .constants import ISSUER, OPENID_URL


class AzureBotTokenValidator:
    _VALID_ISSUERS = (
        ISSUER,
        "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/",
        "https://login.microsoftonline.com/"
        "d6d49420-f39b-4df7-a1dc-d59a935871db/v2.0",
    )

    def __init__(self, app_id, session):
        self.app_id = app_id
        self.session = session
        self._keys = []
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _json(self, url):
        async with self.session.get(
            url,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def _key(self, kid):
        async with self._lock:
            now = time.monotonic()
            match = next((k for k in self._keys if k.get("kid") == kid), None)
            if now - self._fetched_at >= 3600 or (
                match is None and now - self._fetched_at >= 60
            ):
                metadata = await self._json(OPENID_URL)
                uri = metadata.get("jwks_uri", "")
                parsed = urlsplit(uri)
                if (
                    metadata.get("issuer") != ISSUER
                    or parsed.scheme != "https"
                    or parsed.hostname != "login.botframework.com"
                    or parsed.username
                    or parsed.password
                    or parsed.port not in (None, 443)
                ):
                    raise ValueError("AUTH_METADATA_INVALID")
                keys = (await self._json(uri))["keys"]
                if not isinstance(keys, list):
                    raise ValueError("AUTH_KEYS_INVALID")
                self._keys, self._fetched_at = keys, now
                match = next((k for k in keys if k.get("kid") == kid), None)
            if match is None:
                raise ValueError("AUTH_KEY_UNKNOWN")
            return match

    async def authenticate(self, header):
        """Verify signature and claims before the request body is read."""
        if not self.app_id or not header.startswith("Bearer "):
            return None
        try:
            token = header[7:]
            headers = jwt.get_unverified_header(token)
            kid = headers.get("kid")
            if (
                headers.get("alg") != "RS256"
                or not isinstance(kid, str)
                or not kid
            ):
                return None
            key = await self._key(kid)
            claims = jwt.decode(
                token,
                jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key)),
                algorithms=["RS256"],
                audience=self.app_id,
                leeway=300,
                options={
                    "require": ["iss", "aud", "exp", "nbf"],
                    "verify_iss": False,
                },
            )
            # PyJWT 2.0 accepts only one issuer; check the signed claims here.
            if (
                claims["iss"] not in self._VALID_ISSUERS
                or claims["aud"] != self.app_id
            ):
                return None
            return claims, tuple(key.get("endorsements") or ())
        except (
            jwt.InvalidTokenError,
            ValueError,
            KeyError,
            TypeError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            return None

    @staticmethod
    def validates_activity(authentication, activity):
        claims, endorsements = authentication
        service_url = activity.get("serviceUrl")
        # Microsoft's SDK uses lowercase serviceurl; REST documentation names
        # the claim serviceUrl. Both must agree if a token carries both.
        values = [
            claims[k] for k in ("serviceurl", "serviceUrl") if k in claims
        ]
        return bool(
            isinstance(service_url, str)
            and service_url
            and values
            and all(value == service_url for value in values)
            and (
                not endorsements or activity.get("channelId") in endorsements
            ),
        )
