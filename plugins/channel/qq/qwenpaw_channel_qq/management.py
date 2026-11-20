# -*- coding: utf-8 -*-
"""One-shot Portal binding operations for the fixed G3 static hook."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from qwenpaw.channel_protocol.management import (
    ManagementRequest,
    ManagementResult,
)
from qwenpaw.channel_protocol.errors import ProtocolValidationError


def _generate_bind_key():
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _decrypt_secret(encrypted_base64, key_base64, associated_data=None):
    key = base64.b64decode(key_base64, validate=True)
    raw = base64.b64decode(encrypted_base64, validate=True)
    if len(key) != 32 or len(raw) < 28:
        raise ValueError("Invalid encrypted secret")
    return (
        AESGCM(key)
        .decrypt(raw[:12], raw[12:], associated_data)
        .decode("utf-8")
    )


def _encode_poll_token(task_id, aes_key):
    value = json.dumps(
        {"task_id": task_id, "key": aes_key},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(value.encode()).decode("ascii")


def _decode_poll_token(token):
    try:
        raw = base64.b64decode(token, altchars=b"-_", validate=True)
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"task_id", "key"}:
            raise ValueError
        if not all(isinstance(v, str) and v for v in data.values()):
            raise ValueError
        if len(data["task_id"].encode()) > 8192:
            raise ValueError
        if len(base64.b64decode(data["key"], validate=True)) != 32:
            raise ValueError
        return data["task_id"], data["key"]
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("Invalid poll token") from exc


def _result(request, payload=None, *, reason=None, unsupported=False):
    identity = request.to_mapping()
    identity.pop("timeout_ms")
    identity.pop("parameters")
    return ManagementResult.from_mapping(
        {
            **identity,
            "outcome": (
                "unsupported" if unsupported else "failed" if reason else "ok"
            ),
            "reason_code": reason,
            "result": payload,
        },
    )


async def manage(request):
    """Cancel the one native operation once, then settle its real HTTP cleanup."""
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
    if request.channel_key != "qq" or request.plugin_id != "qq":
        return _result(request, reason="IDENTITY_MISMATCH")
    if request.operation not in {"qrcode.fetch", "qrcode.poll"}:
        return _result(
            request,
            reason="VERIFICATION_UNSUPPORTED",
            unsupported=True,
        )
    host = os.getenv("QQ_PORTAL_HOST", "q.qq.com")
    # This is the historical trusted environment override, never browser config.
    if any(c in host for c in "/?#@\\") or not host:
        return _result(request, reason="MANAGEMENT_INVALID_REQUEST")
    continuation = None
    if request.operation == "qrcode.poll":
        try:
            continuation = _decode_poll_token(
                request.parameters["continuation"],
            )
        except ValueError:
            return _result(request, reason="MANAGEMENT_INVALID_REQUEST")
    try:
        async with asyncio.timeout(request.timeout_ms / 1000):
            async with httpx.AsyncClient(
                timeout=min(15, request.timeout_ms / 1000),
            ) as client:
                if request.operation == "qrcode.fetch":
                    key = _generate_bind_key()
                    response = await client.post(
                        f"https://{host}/lite/create_bind_task",
                        json={"key": key},
                    )
                    response.raise_for_status()
                    value = response.json()
                    task_id = value.get("data", {}).get("task_id")
                    if value.get("retcode") != 0:
                        return _result(request, reason="PLATFORM_REJECTED")
                    if not isinstance(task_id, str) or not task_id:
                        raise ProtocolValidationError(
                            "uncertain Portal operation",
                            reason_code="PLATFORM_RESULT_UNKNOWN",
                        )
                    query = urlencode(
                        {"task_id": task_id, "_wv": "2", "source": "QwenPaw"},
                    )
                    return _result(
                        request,
                        {
                            "scan_url": f"https://{host}/qqbot/openclaw/connect.html?{query}",
                            "continuation": _encode_poll_token(task_id, key),
                        },
                    )
                task_id, key = continuation
                response = await client.post(
                    f"https://{host}/lite/poll_bind_result",
                    json={"task_id": task_id},
                )
                response.raise_for_status()
                value = response.json()
                if value.get("retcode") != 0:
                    return _result(
                        request,
                        {
                            "status": "fail",
                            "credentials": {
                                "fail_reason": str(
                                    value.get("msg", "unknown"),
                                ),
                            },
                        },
                    )
                data = value.get("data", {})
                status, credentials = "waiting", {}
                if data.get("status", -1) == 3:
                    status = "expired"
                elif data.get("status", -1) == 2:
                    status = "fail"
                    if not data.get("bot_appid") or not data.get(
                        "bot_encrypt_secret",
                    ):
                        credentials = {
                            "fail_reason": "Missing app_id or secret",
                        }
                    else:
                        try:
                            secret = _decrypt_secret(
                                data["bot_encrypt_secret"],
                                key,
                            )
                        except Exception:
                            credentials = {
                                "fail_reason": "Secret decryption failed",
                            }
                        else:
                            status = "success"
                            credentials = {
                                "app_id": str(data["bot_appid"]),
                                "client_secret": secret,
                            }
                result = {"status": status, "credentials": credentials}
                if status == "success":
                    result["metadata"] = {
                        "user_openid": str(data.get("user_openid", "")),
                    }
                return _result(request, result)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        raise
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= 500:
            raise ProtocolValidationError(
                "uncertain Portal operation",
                reason_code="PLATFORM_RESULT_UNKNOWN",
            ) from None
        return _result(request, reason="PLATFORM_REJECTED")
    except httpx.RequestError:
        raise ProtocolValidationError(
            "uncertain Portal operation",
            reason_code="PLATFORM_RESULT_UNKNOWN",
        ) from None
    except (ValueError, TypeError, AttributeError):
        raise ProtocolValidationError(
            "uncertain Portal operation",
            reason_code="PLATFORM_RESULT_UNKNOWN",
        ) from None
