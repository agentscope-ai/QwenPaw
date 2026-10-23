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
from ...providers.provider import Provider
from ...providers.adapters.wire_protocol import WireProtocol
from ...providers.adapters.request_context import model_session
from ...providers.adapters.cache_policy import mark_stable_prefix
from .request import GatewayRequest, GatewayStreamingResponse
from .limiter import SharedLimiter
from .provider_setup import provider_headers, model_provider
from .protocol import (
    safe_payload,
    upstream_payload,
    usage_tokens,
)


class _UpstreamError(HTTPException):
    """Carry a sanitized provider error through gateway cleanup."""


def _upstream_error(payload, attempt, status=502):
    """Keep provider diagnostics without exposing connection credentials."""
    if isinstance(payload, dict):
        payload = payload.get(f"response", payload)
        payload = (
            payload.get(f"error")
            or payload.get(f"incomplete_details")
            or payload
        )
    if not isinstance(payload, dict):
        payload = {f"message": payload}
    error = {}
    for field in (f"message", f"type", f"code"):
        value = payload.get(field)
        if field == f"message":
            value = value or payload.get(f"reason")
        if isinstance(value, (str, int)):
            text = f"{value}"
            if attempt.upstream_key:
                text = text.replace(attempt.upstream_key, f"[redacted]")
            error[field] = Provider.sanitize_connection_message(text)[:2048]
    error[f"message"] = error.get(f"message") or (
        f"Upstream model request failed (HTTP {status})."
    )
    error.setdefault(f"code", f"hub_upstream_error")
    error[f"request_id"] = attempt.request_id
    return _UpstreamError(status, error)


def _check_upstream_error(payload, attempt):
    """Inspect native error events before wire translation drops details."""
    if (
        payload.get(f"error")
        or payload.get(f"type")
        in {
            f"error",
            f"response.failed",
            f"response.incomplete",
        }
        or payload.get(f"status") == f"failed"
    ):
        raise _upstream_error(payload, attempt)


def _gateway_error(exc, attempt):
    """Distinguish provider errors, timeouts, and transport failures."""
    if isinstance(exc, _UpstreamError):
        return exc
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return _upstream_error(
            {
                f"message": f"Upstream model request timed out.",
                f"code": f"hub_upstream_timeout",
            },
            attempt,
            504,
        )
    message = (
        f"Could not reach the upstream model service."
        if isinstance(exc, httpx.RequestError)
        else f"Invalid or incomplete response from the upstream model."
    )
    return _upstream_error({f"message": message}, attempt)


def _error_response(exc, attempt):
    """Serve SDK error fields and the console's existing detail contract."""
    error = _gateway_error(exc, attempt)
    return JSONResponse(
        status_code=error.status_code,
        content={f"error": error.detail, f"detail": error.detail},
        headers={
            f"X-Request-ID": attempt.request_id,
            f"Cache-Control": f"no-store",
        },
    )


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
            recovery = db.execute(
                f"SELECT value_json FROM hub_settings "
                f"WHERE key = 'model_gateway_recovery_until'",
            ).fetchone()
        self.budgets.recover()
        if recovery:
            remaining = max(0, float(recovery[0]) - time.time())
            self.limiter.cooldown_until = time.monotonic() + remaining

    @staticmethod
    def _prepare(model, connection, body, cap):
        """Load metadata and prepare wire data outside the event loop."""
        provider = model_provider(model, connection)
        bridge = WireProtocol(
            provider.model_protocol(model[f"upstream_model"]),
        )
        payload = upstream_payload(
            body,
            model,
            cap,
            connection,
            provider=provider,
        )
        card = provider.resolve_model_info(model[f"upstream_model"])
        if card.max_output_length:
            for field in (f"max_tokens", f"max_completion_tokens"):
                if field in payload:
                    payload[field] = min(
                        payload[field],
                        card.max_output_length,
                    )
        settings = dict(model.get(f"cache_settings") or {})
        controls = provider.prepare_request(
            model[f"upstream_model"],
            bridge.protocol,
            settings,
        )
        if (
            settings.get(f"enable_prompt_cache_breakpoint")
            and bridge.protocol != f"responses"
        ):
            payload[f"messages"] = mark_stable_prefix(
                payload[f"messages"],
                responses=False,
            )
        headers = {
            **provider_headers(connection),
            **controls.pop(f"extra_headers", {}),
        }
        payload = bridge.request(payload)
        if (
            settings.get(f"enable_prompt_cache_breakpoint")
            and bridge.protocol == f"responses"
        ):
            payload[f"input"] = mark_stable_prefix(
                payload[f"input"],
                responses=True,
            )
        payload.update(controls.pop(f"extra_body", {}))
        payload.update(controls)
        return (
            bridge,
            provider.request_url(model[f"upstream_model"]),
            headers,
            payload,
        )

    async def _open(self, attempt, model, connection, prepared, timeout):
        bridge, url, headers, payload = prepared
        stack = attempt.stack
        await stack.enter_async_context(
            self.limiter.acquire(model, connection),
        )
        client = await stack.enter_async_context(
            httpx.AsyncClient(
                transport=self.transport,
                follow_redirects=False,
                timeout=httpx.Timeout(timeout, connect=10),
                trust_env=False,
            ),
        )
        key = await run_sync_io(self.catalog.key, connection)
        attempt.upstream_key = key
        request = client.build_request(
            "POST",
            url,
            headers={
                **headers,
                **(
                    {f"x-api-key": key, f"anthropic-version": f"2023-06-01"}
                    if bridge.protocol == f"anthropic"
                    else {f"Authorization": f"Bearer {key}"}
                ),
            },
            json=payload,
        )
        await attempt.dispatch(timeout)
        response = await asyncio.wait_for(
            client.send(request, stream=True),
            timeout=timeout,
        )
        stack.push_async_callback(response.aclose)
        if response.status_code != 200:
            raw = bytearray()
            async with asyncio.timeout(timeout):
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk[: 65536 - len(raw)])
                    if len(raw) >= 65536:
                        break
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw.decode(f"utf-8", errors=f"replace")
            status = response.status_code
            raise _upstream_error(
                payload,
                attempt,
                status if 400 <= status <= 599 else 502,
            )
        return response

    async def call(
        self,
        identity,
        body,
        *,
        admin_test=False,
        session_id=None,
    ):
        """Reserve once and transfer resource ownership to the response."""
        attempt = GatewayRequest(self.budgets, self.catalog)
        try:
            _, model, connection, cap = await attempt.reserve(
                identity,
                body,
                admin_test=admin_test,
            )
            settings = await run_sync_io(self.catalog.store.settings)
            timeout = settings[f"gateway_timeout_seconds"]
            context = {**identity, f"session_id": session_id}
            with model_session(context, attempt.request_id):
                prepared = await run_sync_io(
                    self._prepare,
                    model,
                    connection,
                    body,
                    cap,
                )
                bridge = prepared[0]
                response = await self._open(
                    attempt,
                    model,
                    connection,
                    prepared,
                    timeout,
                )
        except BaseException as exc:
            await attempt.close(error="upstream_failed")
            if isinstance(exc, _UpstreamError):
                return _error_response(exc, attempt)
            if isinstance(exc, (HTTPException, asyncio.CancelledError)):
                raise
            if isinstance(exc, ValueError):
                raise HTTPException(
                    422,
                    f"hub_invalid_model_controls",
                ) from None
            return _error_response(exc, attempt)
        if body.get("stream", False):
            return GatewayStreamingResponse(
                self._stream(
                    response,
                    attempt,
                    body["model"],
                    timeout,
                    bridge,
                ),
                attempt,
                media_type="text/event-stream",
                headers={
                    "X-Request-ID": attempt.request_id,
                    "Cache-Control": "no-store",
                },
            )
        return await self._complete(
            response,
            attempt,
            body["model"],
            timeout,
            bridge,
        )

    async def _complete(self, response, attempt, model_id, timeout, bridge):
        actual = None
        error = "response_incomplete"
        try:
            raw = bytearray()
            async with asyncio.timeout(timeout):
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 16 * 1024 * 1024:
                        raise ValueError("Upstream response too large")
            data = json.loads(raw)
            _check_upstream_error(data, attempt)
            if bridge is not None:
                data = bridge.response(data)
            result = safe_payload(data, model_id)
            actual = usage_tokens(data)
            error = None
            return JSONResponse(
                result,
                headers={"X-Request-ID": attempt.request_id},
            )
        except Exception as exc:
            return _error_response(exc, attempt)
        finally:
            await attempt.close(actual, error)

    async def _stream(self, response, attempt, model_id, timeout, bridge):
        actual = None
        complete = False
        try:
            async with asyncio.timeout(timeout):
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
                    _check_upstream_error(data, attempt)
                    if bridge is not None:
                        data = bridge.event(data)
                        if bridge.done:
                            complete = True
                        if data is None:
                            if complete:
                                yield b"data: [DONE]\n\n"
                                break
                            continue
                    found = usage_tokens(data)
                    if found is not None:
                        actual = found
                    event = json.dumps(safe_payload(data, model_id))
                    yield f"data: {event}\n\n".encode()
                    if complete:
                        yield b"data: [DONE]\n\n"
                        break
        except Exception as exc:
            error = _gateway_error(exc, attempt)
            event = json.dumps({f"error": error.detail})
            yield f"data: {event}\n\n".encode()
        finally:
            await attempt.close(
                actual if complete else None,
                None if complete else "stream_incomplete",
            )
