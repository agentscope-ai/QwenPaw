# -*- coding: utf-8 -*-
"""Feishu/Lark Device Flow; no message-runtime construction or binding."""

import asyncio
import base64
import json
from urllib.parse import urlencode

import httpx

from qwenpaw.channel_protocol.errors import ProtocolValidationError
from qwenpaw.channel_protocol.management import (
    ManagementRequest,
    management_result,
)

_ORIGINS = {
    "feishu": "https://accounts.feishu.cn",
    "lark": "https://accounts.larksuite.com",
}


def _continuation(device_code, domain):
    if not isinstance(device_code, str) or not device_code:
        raise ValueError("device code missing")
    return base64.urlsafe_b64encode(
        json.dumps({"device_code": device_code, "domain": domain}).encode(),
    ).decode("ascii")


def _decode(value):
    data = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
    if (
        not isinstance(data, dict)
        or set(data) != {"device_code", "domain"}
        or not isinstance(data["domain"], str)
        or data["domain"] not in _ORIGINS
        or not isinstance(data["device_code"], str)
        or not data["device_code"]
    ):
        raise ValueError("invalid continuation")
    return data["device_code"], data["domain"]


async def manage(request):
    request = ManagementRequest.from_mapping(request.to_mapping())
    if request.plugin_id != "feishu" or request.channel_key != "feishu":
        return management_result(request, reason="IDENTITY_MISMATCH")
    if request.operation not in {"qrcode.fetch", "qrcode.poll"}:
        return management_result(
            request,
            reason="MANAGEMENT_UNSUPPORTED",
            unsupported=True,
        )
    fetch = request.operation == "qrcode.fetch"
    domain = request.parameters.get("options", {}).get("domain")
    if domain not in _ORIGINS:
        domain = request.parameters["config"].get("domain", "feishu")
    domain = domain if domain in _ORIGINS else "feishu"
    device_code = None
    if not fetch:
        try:
            device_code, domain = _decode(request.parameters["continuation"])
        except (ValueError, TypeError, UnicodeError):
            return management_result(
                request,
                reason="MANAGEMENT_INVALID_REQUEST",
            )
    endpoint = _ORIGINS[domain] + "/oauth/v1/app/registration"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        async with asyncio.timeout(request.timeout_ms / 1000):
            async with httpx.AsyncClient(
                timeout=min(15 if fetch else 10, request.timeout_ms / 1000),
            ) as client:
                if fetch:
                    response = await client.post(
                        endpoint,
                        content=urlencode({"action": "init"}),
                        headers=headers,
                    )
                    response.raise_for_status()
                    if "client_secret" not in response.json().get(
                        "supported_auth_methods",
                        [],
                    ):
                        return management_result(
                            request,
                            reason="PLATFORM_REJECTED",
                        )
                    response = await client.post(
                        endpoint,
                        content=urlencode(
                            {
                                "action": "begin",
                                "archetype": "PersonalAgent",
                                "auth_method": "client_secret",
                                "request_user_info": "open_id",
                            },
                        ),
                        headers=headers,
                    )
                    response.raise_for_status()
                    value = response.json()
                    uri = value.get("verification_uri_complete")
                    if not isinstance(uri, str) or not uri:
                        raise ValueError("QR URL missing")
                    result = {
                        "scan_url": uri
                        + ("&" if "?" in uri else "?")
                        + "source=QwenPaw",
                        "continuation": _continuation(
                            value.get("device_code"),
                            domain,
                        ),
                    }
                    if "expires_in" in value:
                        result["expires_in_seconds"] = value["expires_in"]
                    return management_result(request, result)
                response = await client.post(
                    endpoint,
                    content=urlencode(
                        {"action": "poll", "device_code": device_code},
                    ),
                    headers=headers,
                )
                # OAuth errors can be useful JSON on HTTP400; preserve that path.
                value = response.json()
                if value.get("client_id") and value.get("client_secret"):
                    info = value.get("user_info", {})
                    result = {
                        "status": "success",
                        "credentials": {
                            "app_id": value["client_id"],
                            "app_secret": value["client_secret"],
                        },
                        "metadata": {
                            "open_id": info.get("open_id", ""),
                            "tenant_brand": info.get("tenant_brand", "feishu"),
                        },
                    }
                else:
                    error = value.get("error", "")
                    status, reason = "waiting", None
                    if error in {"expired_token", "invalid_grant"}:
                        status, reason = "expired", "QR code expired"
                    elif error == "access_denied":
                        status, reason = "fail", "User denied authorization"
                    elif error and error not in {
                        "authorization_pending",
                        "slow_down",
                    }:
                        status, reason = "fail", error
                    result = {
                        "status": status,
                        "credentials": (
                            {"fail_reason": reason}
                            if reason is not None
                            else {}
                        ),
                    }
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
