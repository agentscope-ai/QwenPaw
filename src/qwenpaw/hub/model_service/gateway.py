# -*- coding: utf-8 -*-
"""Bounded model forwarding with cancellation-safe resource ownership."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ...utils.io_utils import run_sync_io
from .request import GatewayRequest, GatewayStreamingResponse
from .limiter import SharedLimiter
from .provider_setup import provider_headers
from .protocol import (
    safe_payload,
    upstream_payload,
    usage_tokens,
)

_TIMEOUT = 120


class ModelGateway:
    """Keep upstream keys, request attribution, and settlement in Hub."""

    def __init__(self, catalog, budgets, transport=None):
        self.catalog = catalog
        self.budgets = budgets
        self.transport = transport
        self.limiter = SharedLimiter(catalog.store)

    def recover(self):
        """Wait out attempts that might still be running after a restart."""
        with self.catalog.store.connect() as db:
            orphan = db.execute(
                "SELECT 1 FROM hub_model_requests "
                "WHERE status = 'dispatched' LIMIT 1",
            ).fetchone()
        self.budgets.recover()
        if orphan:
            self.limiter.cooldown_until = time.monotonic() + 2 * _TIMEOUT

    async def _open(self, attempt, model, connection, payload):
        stack = attempt.stack
        await stack.enter_async_context(
            self.limiter.acquire(model, connection),
        )
        client = await stack.enter_async_context(
            httpx.AsyncClient(
                transport=self.transport,
                follow_redirects=False,
                timeout=httpx.Timeout(_TIMEOUT, connect=10),
                trust_env=False,
            ),
        )
        key = await run_sync_io(self.catalog.key, connection)
        request = client.build_request(
            "POST",
            f"{connection['base_url']}/chat/completions",
            headers={
                **provider_headers(connection),
                "Authorization": f"Bearer {key}",
            },
            json=payload,
        )
        await attempt.dispatch()
        response = await asyncio.wait_for(
            client.send(request, stream=True),
            timeout=_TIMEOUT,
        )
        stack.push_async_callback(response.aclose)
        if response.status_code != 200:
            raise HTTPException(
                502,
                f"hub_upstream_error:{attempt.request_id}",
            )
        return response

    async def call(self, identity, body):
        """Reserve once and transfer resource ownership to the response."""
        attempt = GatewayRequest(self.budgets, self.catalog)
        try:
            _, model, connection, cap = await attempt.reserve(identity, body)
            response = await self._open(
                attempt,
                model,
                connection,
                upstream_payload(body, model, cap, connection),
            )
        except BaseException as exc:
            await attempt.close(error="upstream_failed")
            if isinstance(exc, (HTTPException, asyncio.CancelledError)):
                raise
            raise HTTPException(
                502,
                f"hub_upstream_error:{attempt.request_id}",
            ) from None
        if body.get("stream", False):
            return GatewayStreamingResponse(
                self._stream(response, attempt, body["model"]),
                attempt,
                media_type="text/event-stream",
                headers={
                    "X-Request-ID": attempt.request_id,
                    "Cache-Control": "no-store",
                },
            )
        return await self._complete(response, attempt, body["model"])

    async def _complete(self, response, attempt, model_id):
        actual = None
        error = "response_incomplete"
        try:
            raw = bytearray()
            async with asyncio.timeout(_TIMEOUT):
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 16 * 1024 * 1024:
                        raise ValueError("Upstream response too large")
            data = json.loads(raw)
            result = safe_payload(data, model_id)
            actual = usage_tokens(data)
            error = None
            return JSONResponse(
                result,
                headers={"X-Request-ID": attempt.request_id},
            )
        except Exception:
            raise HTTPException(
                502,
                f"hub_upstream_error:{attempt.request_id}",
            ) from None
        finally:
            await attempt.close(actual, error)

    async def _stream(self, response, attempt, model_id):
        actual = None
        complete = False
        try:
            async with asyncio.timeout(_TIMEOUT):
                async for line in response.aiter_lines():
                    if len(line) > 4 * 1024 * 1024:
                        raise ValueError("Stream event too large")
                    if not line.startswith("data:"):
                        continue
                    text = line[5:].strip()
                    if text == "[DONE]":
                        complete = True
                        yield b"data: [DONE]\n\n"
                        break
                    data = json.loads(text)
                    found = usage_tokens(data)
                    if found is not None:
                        actual = found
                    event = json.dumps(safe_payload(data, model_id))
                    yield f"data: {event}\n\n".encode()
        except Exception:
            event = json.dumps(
                {
                    "error": {
                        "code": "hub_upstream_error",
                        "request_id": attempt.request_id,
                    },
                },
            )
            yield f"data: {event}\n\n".encode()
        finally:
            await attempt.close(
                actual if complete else None,
                None if complete else "stream_incomplete",
            )
