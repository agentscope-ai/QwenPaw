# -*- coding: utf-8 -*-
"""One bounded explicit management operation; never runtime authentication files."""

import asyncio

import httpx

from qwenpaw.channel_protocol.management import ManagementResult
from .client import ILinkClient, _DEFAULT_BASE_URL


def _result(request, result=None, *, reason=None):
    identity = request.to_mapping()
    identity.pop("parameters")
    identity.pop("timeout_ms")
    return ManagementResult.from_mapping(
        {
            **identity,
            "outcome": "failed" if reason else "ok",
            "reason_code": reason,
            "result": result,
        },
    )


async def manage(request):
    config = request.parameters["config"]
    base_url = (
        request.parameters.get("options", {}).get(
            "base_url",
            config.get("base_url"),
        )
        or _DEFAULT_BASE_URL
    )
    operation = str(request.operation)
    if operation == "connection.verify":
        level = request.parameters["level"]
        if level == "credentials":
            return _result(
                request,
                {
                    "level": level,
                    "verdict": "unsupported",
                    "reason_code": "VERIFICATION_UNSUPPORTED",
                    "notes": [],
                },
            )
        url = (
            config.get("base_url") or "https://api.weixin.qq.com"
        ).strip().rstrip("/") + "/"
        try:
            async with asyncio.timeout(request.timeout_ms / 1000):
                async with httpx.AsyncClient(
                    timeout=request.timeout_ms / 1000,
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
        except (httpx.HTTPError, TimeoutError):
            return _result(
                request,
                {
                    "level": level,
                    "verdict": "failed",
                    "reason_code": "PLATFORM_REQUEST_FAILED",
                    "notes": [],
                },
            )
        return _result(
            request,
            {
                "level": level,
                "verdict": "passed",
                "reason_code": None,
                "notes": [
                    "HTTP reachability only; credentials were not verified.",
                ],
            },
        )

    client = ILinkClient(base_url=base_url)
    try:
        async with asyncio.timeout(request.timeout_ms / 1000):
            await client.start()
            if operation == "qrcode.fetch":
                data = await client.get_bot_qrcode()
                continuation = data.get("qrcode", "")
                image_content = data.get("qrcode_img_content", "")
                if (
                    not continuation
                    or not isinstance(continuation, str)
                    or not isinstance(image_content, str)
                ):
                    return _result(request, reason="MANAGEMENT_INVALID_RESULT")
                scan_url = (
                    image_content
                    if image_content.startswith("http")
                    else (
                        "https://liteapp.weixin.qq.com/q/7GiQu1"
                        f"?qrcode={continuation}&bot_type=3"
                    )
                )
                return _result(
                    request,
                    {"scan_url": scan_url, "continuation": continuation},
                )
            if operation == "qrcode.poll":
                data = await client.get_qrcode_status(
                    request.parameters["continuation"],
                )
                return _result(
                    request,
                    {
                        "status": data.get("status", "waiting"),
                        "credentials": {
                            key: "" if value is None else value
                            for key, value in (
                                ("bot_token", data.get("bot_token")),
                                ("base_url", data.get("baseurl")),
                            )
                        },
                    },
                )
            return _result(request, reason="MANAGEMENT_UNSUPPORTED")
    finally:
        await client.stop()
