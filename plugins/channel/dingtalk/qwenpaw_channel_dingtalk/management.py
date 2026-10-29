# -*- coding: utf-8 -*-
"""DingTalk Device Flow through the fixed one-shot management hook."""

import asyncio

import httpx

from qwenpaw.channel_protocol.errors import ProtocolValidationError
from qwenpaw.channel_protocol.management import (
    ManagementRequest,
    management_result,
)

_BASE = "https://oapi.dingtalk.com/app/registration"


def _text(value):
    return value.strip() if isinstance(value, str) else ""


async def manage(request):
    request = ManagementRequest.from_mapping(request.to_mapping())
    if request.plugin_id != "dingtalk" or request.channel_key != "dingtalk":
        return management_result(request, reason="IDENTITY_MISMATCH")
    if request.operation not in {"qrcode.fetch", "qrcode.poll"}:
        return management_result(
            request,
            reason="MANAGEMENT_UNSUPPORTED",
            unsupported=True,
        )
    fetch = request.operation == "qrcode.fetch"
    try:
        async with asyncio.timeout(request.timeout_ms / 1000):
            async with httpx.AsyncClient(
                timeout=min(15 if fetch else 10, request.timeout_ms / 1000),
            ) as client:
                if fetch:
                    response = await client.post(
                        _BASE + "/init",
                        json={"source": "QWENPAW"},
                    )
                    response.raise_for_status()
                    initial = response.json()
                    if initial.get("errcode", -1) != 0:
                        return management_result(
                            request,
                            reason="PLATFORM_REJECTED",
                        )
                    nonce = initial.get("nonce")
                    if not isinstance(nonce, str) or not nonce:
                        raise ValueError("nonce missing")
                    # The same client retains cookies from init through begin.
                    response = await client.post(
                        _BASE + "/begin",
                        json={"nonce": nonce},
                    )
                    response.raise_for_status()
                    value = response.json()
                    if value.get("errcode", -1) != 0:
                        return management_result(
                            request,
                            reason="PLATFORM_REJECTED",
                        )
                    # The original Device Flow documents a two-hour code TTL.
                    return management_result(
                        request,
                        {
                            "scan_url": value.get("verification_uri_complete"),
                            "continuation": value.get("device_code"),
                            "expires_in_seconds": value.get(
                                "expires_in",
                                7200,
                            ),
                        },
                    )
                # Each management execution creates a fresh poll client.
                response = await client.post(
                    _BASE + "/poll",
                    json={"device_code": request.parameters["continuation"]},
                )
                response.raise_for_status()
                value = response.json()
                status = _text(value.get("status")).upper()
                client_id = _text(value.get("client_id"))
                secret = _text(value.get("client_secret"))
                if client_id and secret:
                    result = {
                        "status": "success",
                        "credentials": {
                            "client_id": client_id,
                            "client_secret": secret,
                        },
                    }
                elif status in {"FAIL", "EXPIRED"}:
                    result = {
                        "status": "expired" if status == "EXPIRED" else "fail",
                        "credentials": {
                            "fail_reason": _text(value.get("fail_reason")),
                        },
                    }
                else:
                    result = {"status": "waiting", "credentials": {}}
                return management_result(request, result)
    except (asyncio.CancelledError, TimeoutError):
        raise
    except httpx.HTTPStatusError as error:
        if error.response.status_code < 500:
            return management_result(request, reason="PLATFORM_REJECTED")
        raise ProtocolValidationError(
            "uncertain authorization operation",
            reason_code="PLATFORM_RESULT_UNKNOWN",
        ) from None
    except (httpx.RequestError, ValueError, TypeError, AttributeError):
        raise ProtocolValidationError(
            "uncertain authorization operation",
            reason_code="PLATFORM_RESULT_UNKNOWN",
        ) from None
