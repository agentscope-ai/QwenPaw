# -*- coding: utf-8 -*-
"""FastAPI server factory for the inbound webhook receiver."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .signature import SIGNATURE_HEADER, verify_signature

if TYPE_CHECKING:
    from .channel import GenericWebhookEvent, WebhookChannel

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB


def create_webhook_app(channel: "WebhookChannel") -> FastAPI:
    """Build the FastAPI app exposing POST /webhooks/{channel_id}."""
    app = FastAPI(title="QwenPaw Webhook Channel")

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
