# -*- coding: utf-8 -*-
"""Outbound webhook reply sender with HMAC-SHA256 signing and retry."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

import httpx

from .signature import SIGNATURE_HEADER, SIGNATURE_PREFIX

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_MAX_ATTEMPTS = 3
RETRY_BACKOFF_BASE_S = 1.0


def _sign_body(body: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


async def send_webhook_reply(
    url: str,
    payload: Dict[str, Any],
    secret: Optional[str] = None,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> bool:
    """POST ``payload`` to ``url`` with optional HMAC-SHA256 signing.

    Retries on 5xx and network errors with exponential backoff
    (``1s``, ``2s``, ``4s`` by default). Returns ``True`` on any 2xx
    response, ``False`` after exhausting retries or on a 4xx response
    (no retry).
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers[SIGNATURE_HEADER] = _sign_body(body, secret)

    last_exc: Optional[Exception] = None
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(url, content=body, headers=headers)
            if 200 <= resp.status_code < 300:
                return True
            if 400 <= resp.status_code < 500:
                logger.warning(
                    "webhook reply returned %d (no retry): %s",
                    resp.status_code,
                    url,
                )
                return False
            last_exc = httpx.HTTPStatusError(
                f"{resp.status_code} response",
                request=resp.request,
                response=resp,
            )
            logger.warning(
                "webhook reply attempt %d/%d failed with %d",
                attempt + 1,
                max_attempts,
                resp.status_code,
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning(
                "webhook reply attempt %d/%d raised %s",
                attempt + 1,
                max_attempts,
                exc.__class__.__name__,
            )

        if attempt < max_attempts - 1:
            await asyncio.sleep(RETRY_BACKOFF_BASE_S * (2**attempt))

    logger.error(
        "webhook reply exhausted %d attempts to %s: %s",
        max_attempts,
        url,
        last_exc,
    )
    return False


def send_webhook_reply_sync(
    url: str,
    payload: Dict[str, Any],
    secret: Optional[str] = None,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> bool:
    """Synchronous wrapper around :func:`send_webhook_reply`."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            send_webhook_reply(
                url,
                payload,
                secret,
                max_attempts=max_attempts,
                timeout_s=timeout_s,
            ),
        )
    return asyncio.run_coroutine_threadsafe(
        send_webhook_reply(
            url,
            payload,
            secret,
            max_attempts=max_attempts,
            timeout_s=timeout_s,
        ),
        loop,
    ).result()
