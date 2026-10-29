# -*- coding: utf-8 -*-
"""Explicit one-shot QR authorization over the frozen G3 data contract."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from urllib.parse import quote

import httpx

from qwenpaw.channel_protocol.errors import ProtocolValidationError
from qwenpaw.channel_protocol.management import (
    ManagementRequest,
    ManagementResult,
)

_AUTH_ORIGIN = "https://work.weixin.qq.com"
_SOURCE = "qwenpaw"


def _result(request, payload=None, reason=None, unsupported=False):
    identity = request.to_mapping()
    identity.pop("timeout_ms")
    identity.pop("parameters")
    return ManagementResult.from_mapping(
        {
            **identity,
            "outcome": "unsupported"
            if unsupported
            else "failed"
            if reason
            else "ok",
            "reason_code": reason,
            "result": payload,
        },
    )


async def manage(request):
    task = asyncio.create_task(_execute(request))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if not task.done() and not task.cancelling():
            task.cancel()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if task.done() and not task.cancelled():
            task.exception()
        raise


async def _execute(request):
    request = ManagementRequest.from_mapping(request.to_mapping())
    if request.plugin_id != "wecom" or request.channel_key != "wecom":
        return _result(request, reason="IDENTITY_MISMATCH")
    if request.operation not in {"qrcode.fetch", "qrcode.poll"}:
        return _result(
            request,
            reason="VERIFICATION_UNSUPPORTED",
            unsupported=True,
        )
    fetch = request.operation == "qrcode.fetch"
    if fetch:
        state = secrets.token_urlsafe(16)
        url = f"{_AUTH_ORIGIN}/ai/qc/gen?source={_SOURCE}&state={state}&timestamp={int(time.time() * 1000)}"
    else:
        url = f"{_AUTH_ORIGIN}/ai/qc/query_result?scode={quote(request.parameters['continuation'])}"
    try:
        async with asyncio.timeout(request.timeout_ms / 1000):
            async with httpx.AsyncClient(
                timeout=min(15 if fetch else 10, request.timeout_ms / 1000),
                follow_redirects=fetch,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                if fetch:
                    match = re.search(
                        r"window\.settings\s*=\s*(\{[^<]+\})",
                        response.text,
                    )
                    if match is None:
                        raise ValueError("settings missing")
                    settings = json.loads(match.group(1))
                    scode, auth_url = settings.get("scode"), settings.get(
                        "auth_url",
                    )
                    if (
                        not isinstance(scode, str)
                        or not scode
                        or not isinstance(auth_url, str)
                        or not auth_url
                    ):
                        raise ValueError("settings incomplete")
                    return _result(
                        request,
                        {"scan_url": auth_url, "continuation": scode},
                    )
                value = response.json()
                data = value.get("data", {})
                info = data.get("bot_info", {})
                return _result(
                    request,
                    {
                        "status": data.get("status", "waiting"),
                        "credentials": {
                            "bot_id": info.get("botid", ""),
                            "secret": info.get("secret", ""),
                        },
                    },
                )
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        raise
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code < 500:
            return _result(request, reason="PLATFORM_REJECTED")
        raise ProtocolValidationError(
            "uncertain WeCom authorization operation",
            reason_code="PLATFORM_RESULT_UNKNOWN",
        ) from None
    except (httpx.RequestError, ValueError, TypeError, AttributeError):
        raise ProtocolValidationError(
            "uncertain WeCom authorization operation",
            reason_code="PLATFORM_RESULT_UNKNOWN",
        ) from None
