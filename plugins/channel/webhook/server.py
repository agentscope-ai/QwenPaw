# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""FastAPI server factory for the inbound webhook receiver."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .signature import SIGNATURE_HEADER, verify_signature

if TYPE_CHECKING:
    from .channel import GenericWebhookEvent, WebhookChannel

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# Per-client-IP token bucket rate limiter (simple in-memory implementation)
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Single-bucket token bucket.

    A bucket starts at capacity ``burst`` and refills at ``rps`` tokens
    per second. Each request consumes one token. When the bucket is
    empty, the request is rejected.
    """

    __slots__ = ("capacity", "rps", "tokens", "last_refill")

    def __init__(self, *, burst: int, rps: float) -> None:
        self.capacity = max(1, int(burst))
        self.rps = max(0.1, float(rps))
        self.tokens: float = float(self.capacity)
        self.last_refill: float = time.monotonic()

    def allow(self) -> bool:
        """Return True if a token is available, refilling lazily."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rps,
            )
            self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class _RateLimiter:
    """Rate limiter keyed by client IP.

    Buckets are kept in memory for the lifetime of the FastAPI app
    (cleared on restart). This is intentional for v1: a single-process
    uvicorn worker exposes a single, well-known listening surface, and
    the bucket count is bounded by the number of unique source IPs the
    listener sees. Operators running many workers behind a proxy should
    also enforce rate limiting at the proxy layer.
    """

    def __init__(self, *, rps: float, burst: int) -> None:
        self._rps = rps
        self._burst = burst
        self._buckets: Dict[str, _TokenBucket] = {}
        self._lock = threading.Lock()

    def _bucket_for(self, key: str) -> _TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            with self._lock:
                bucket = self._buckets.get(key)
                if bucket is None:
                    bucket = _TokenBucket(
                        burst=self._burst,
                        rps=self._rps,
                    )
                    self._buckets[key] = bucket
        return bucket

    def allow(self, key: str) -> bool:
        return self._bucket_for(key).allow()


def create_webhook_app(channel: "WebhookChannel") -> FastAPI:
    """Build the FastAPI app exposing POST /webhooks/{channel_id}."""
    app = FastAPI(title="QwenPaw Webhook Channel")

    rate_limiter = _RateLimiter(
        rps=channel.config.rate_limit_rps,
        burst=channel.config.rate_limit_burst,
    )

    @app.post("/webhooks/{channel_id}")
    async def receive_webhook(
        channel_id: str,
        request: Request,
    ) -> JSONResponse:
        if channel_id != channel.config.channel_id:
            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": "unknown_channel"},
            )

        # Per-client-IP rate limiting. ``request.client`` is None for
        # raw ASGI scope tests; fall back to a sentinel key so tests
        # that omit the client still see a single shared bucket.
        client_key = getattr(request.client, "host", None) or "unknown-client"
        if not rate_limiter.allow(client_key):
            logger.warning(
                "webhook rejected due to rate limit for client %s",
                client_key,
            )
            return JSONResponse(
                status_code=429,
                content={"ok": False, "error": "rate_limited"},
                headers={"Retry-After": "1"},
            )

        # Reject early if Content-Length exceeds the limit, so we
        # never read more than MAX_BODY_BYTES off the wire.
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"ok": False, "error": "payload_too_large"},
                    )
            except ValueError:
                pass

        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"ok": False, "error": "payload_too_large"},
            )

        signature = request.headers.get(SIGNATURE_HEADER)
        if not verify_signature(body, signature, channel.config.secret):
            return JSONResponse(
                status_code=401,
                content={
                    "ok": False,
                    "error": "signature_mismatch",
                },
            )

        try:
            payload: Dict[str, Any] = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "malformed_json"},
            )

        event = _build_event(
            body=body,
            payload=payload,
            headers=dict(request.headers),
            channel_id=channel_id,
        )
        asyncio.create_task(channel.dispatch_event(event))

        return JSONResponse(
            status_code=200,
            content={"ok": True, "dispatched": True},
        )

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content={"ok": True, "channel_id": channel.config.channel_id},
        )

    return app


def _build_event(
    *,
    body: bytes,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    channel_id: str,
) -> "GenericWebhookEvent":
    """Construct a ``GenericWebhookEvent`` from a parsed request."""
    from .channel import GenericWebhookEvent

    return GenericWebhookEvent(
        raw_body=body,
        parsed=payload,
        headers=headers,
        channel_id=channel_id,
        timestamp=datetime.now(timezone.utc),
    )


class WebhookServerHandle:
    """Handle returned by :func:`start_webhook_server`."""

    def __init__(
        self,
        *,
        url: str,
        channel_id: str,
        server: Any,
        task: Optional[asyncio.Task],
    ) -> None:
        self.url = url
        self.channel_id = channel_id
        self._server = server
        self._task = task

    async def close(self) -> None:
        """Signal the uvicorn server to shut down."""
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass


def start_webhook_server(channel: "WebhookChannel") -> WebhookServerHandle:
    """Build the FastAPI app and start the uvicorn server in the background."""
    import uvicorn

    app = create_webhook_app(channel)
    config = uvicorn.Config(
        app,
        host=channel.config.bind_address,
        port=channel.config.port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    url = f"http://{channel.config.bind_address}:{channel.config.port}"
    return WebhookServerHandle(
        url=url,
        channel_id=channel.config.channel_id,
        server=server,
        task=task,
    )
