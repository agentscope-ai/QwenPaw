# -*- coding: utf-8 -*-
"""QQ media sending helpers with local-file and URL upload support."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import namedtuple
from typing import Any

import aiohttp

from .file_utils import file_exists, get_file_hash, get_file_size, is_local_path
from .media_tags import SendQueueItem

logger = logging.getLogger(__name__)

API_BASE = "https://api.sgroup.qq.com"
MediaTargetContext = namedtuple("MediaTargetContext", "target_type target_id is_at")
MediaSendResult = namedtuple("MediaSendResult", "success error error_code result")
MediaFileType = {"IMAGE": 1, "VIDEO": 2, "AUDIO": 3, "FILE": 4}


def _normalize_target_type(target_type: str) -> str:
    normalized = (target_type or "").strip().lower()
    mapping = {
        "c2c": "users",
        "user": "users",
        "users": "users",
        "group": "groups",
        "groups": "groups",
    }
    if normalized not in mapping:
        raise ValueError(f"unsupported target_type: {target_type}")
    return mapping[normalized]


def _resolve_target(target: Any) -> MediaTargetContext:
    if isinstance(target, MediaTargetContext):
        return MediaTargetContext(
            _normalize_target_type(target.target_type),
            str(target.target_id),
            bool(target.is_at),
        )
    if isinstance(target, dict):
        return MediaTargetContext(
            _normalize_target_type(target.get("target_type")),
            str(target.get("target_id") or ""),
            bool(target.get("is_at", False)),
        )
    if isinstance(target, (tuple, list)) and len(target) >= 2:
        return MediaTargetContext(
            _normalize_target_type(target[0]),
            str(target[1]),
            bool(target[2]) if len(target) > 2 else False,
        )
    if isinstance(target, str):
        if target.startswith("group:"):
            return MediaTargetContext("groups", target[6:], False)
        return MediaTargetContext("users", target, False)
    raise ValueError("target must be MediaTargetContext, dict, tuple, or str")


def _extract_error(data: Any) -> tuple[str, int]:
    if isinstance(data, dict):
        message = (
            data.get("message")
            or data.get("msg")
            or data.get("error")
            or data.get("errmsg")
            or json.dumps(data, ensure_ascii=False)
        )
        code = data.get("code") or data.get("err_code") or data.get("ret") or -1
        try:
            return str(message), int(code)
        except (TypeError, ValueError):
            return str(message), -1
    return str(data), -1


async def api_request(session, access_token, method, path, data=None):
    """Make an HTTP request to the QQ API and return parsed JSON."""

    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"QQBot {access_token}",
        "Content-Type": "application/json",
    }
    payload = json.dumps(data, ensure_ascii=False) if data is not None else None
    async with session.request(method, url, data=payload, headers=headers) as resp:
        text = await resp.text()
        try:
            result = json.loads(text) if text else {}
        except json.JSONDecodeError:
            result = {"raw": text}
        if resp.status >= 400:
            message, code = _extract_error(result)
            raise RuntimeError(f"QQ API {resp.status} {path}: {message} ({code})")
        return result


async def upload_file_url(session, access_token, target_type, target_id, file_url, file_type):
    """Upload a remote file to QQ rich media API and return file_info."""

    response = await api_request(
        session,
        access_token,
        "POST",
        f"/v2/media/{_normalize_target_type(target_type)}/{target_id}/files",
        {"file_type": file_type, "url": file_url, "srv_send_msg": False},
    )
    file_info = response.get("file_info")
    if not file_info:
        raise RuntimeError("QQ upload response missing file_info")
    return file_info


def _get_md5_hash(file_path: str) -> str:
    hasher = hashlib.md5()
    with open(file_path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


async def upload_local_file(session, access_token, target_type, target_id, file_path, file_type):
    """Upload a local file via multipart form data and return file_info."""

    if not file_exists(file_path):
        raise FileNotFoundError(file_path)

    target_type = _normalize_target_type(target_type)
    file_size, sha256_hash, md5_hash = await asyncio.gather(
        asyncio.to_thread(get_file_size, file_path),
        asyncio.to_thread(get_file_hash, file_path),
        asyncio.to_thread(_get_md5_hash, file_path),
    )

    form = aiohttp.FormData()
    form.add_field("file_type", str(file_type))
    form.add_field("srv_send_msg", "false")
    form.add_field("file_size", str(file_size))
    form.add_field("sha256", sha256_hash)
    form.add_field("md5", md5_hash)

    headers = {"Authorization": f"QQBot {access_token}"}
    url = f"{API_BASE}/v2/media/{target_type}/{target_id}/files"
    with open(file_path, "rb") as file_obj:
        form.add_field("file", file_obj, filename=file_path.rsplit("\\", 1)[-1])
        async with session.post(url, data=form, headers=headers) as resp:
            text = await resp.text()
            try:
                result = json.loads(text) if text else {}
            except json.JSONDecodeError:
                result = {"raw": text}
            if resp.status >= 400:
                message, code = _extract_error(result)
                raise RuntimeError(
                    f"QQ upload failed {resp.status}: {message} ({code})",
                )
            file_info = result.get("file_info")
            if not file_info:
                raise RuntimeError("QQ upload response missing file_info")
            return file_info


async def send_media_message(session, access_token, target_type, target_id, file_info, msg_id=None):
    """Send a QQ rich media message using an uploaded file_info token."""

    body = {"msg_type": 7, "media": {"file_info": file_info}}
    if msg_id:
        body["msg_id"] = msg_id
    return await api_request(
        session,
        access_token,
        "POST",
        f"/v2/media/{_normalize_target_type(target_type)}/{target_id}/messages",
        body,
    )


async def _send_media(target, file_path, access_token, app_id, reply_to_id, file_type):
    del app_id
    try:
        resolved = _resolve_target(target)
        async with aiohttp.ClientSession() as session:
            if is_local_path(file_path):
                file_info = await upload_local_file(
                    session,
                    access_token,
                    resolved.target_type,
                    resolved.target_id,
                    file_path,
                    file_type,
                )
            else:
                file_info = await upload_file_url(
                    session,
                    access_token,
                    resolved.target_type,
                    resolved.target_id,
                    file_path,
                    file_type,
                )
            result = await send_media_message(
                session,
                access_token,
                resolved.target_type,
                resolved.target_id,
                file_info,
                reply_to_id,
            )
            logger.info(
                "qq media sent: target_type=%s target_id=%s file_type=%s",
                resolved.target_type,
                resolved.target_id,
                file_type,
            )
            return MediaSendResult(True, "", 0, result)
    except Exception as exc:
        logger.exception("qq media send failed: path=%s type=%s", file_path, file_type)
        error, error_code = _extract_error(getattr(exc, "args", [str(exc)])[0])
        return MediaSendResult(False, error, error_code, None)


async def send_photo(target, file_path, access_token, app_id, reply_to_id=None):
    return await _send_media(
        target,
        file_path,
        access_token,
        app_id,
        reply_to_id,
        MediaFileType["IMAGE"],
    )


async def send_video_msg(target, file_path, access_token, app_id, reply_to_id=None):
    return await _send_media(
        target,
        file_path,
        access_token,
        app_id,
        reply_to_id,
        MediaFileType["VIDEO"],
    )


async def send_voice(target, file_path, access_token, app_id, reply_to_id=None):
    return await _send_media(
        target,
        file_path,
        access_token,
        app_id,
        reply_to_id,
        MediaFileType["AUDIO"],
    )


async def send_document(target, file_path, access_token, app_id, reply_to_id=None):
    return await _send_media(
        target,
        file_path,
        access_token,
        app_id,
        reply_to_id,
        MediaFileType["FILE"],
    )


async def send_media_auto(target, media_type, file_path, access_token, app_id, reply_to_id=None):
    media_type = (media_type or "").strip().lower()
    handlers = {
        "image": send_photo,
        "video": send_video_msg,
        "voice": send_voice,
        "audio": send_voice,
        "file": send_document,
        "document": send_document,
    }
    handler = handlers.get(media_type)
    if not handler:
        return MediaSendResult(False, f"unsupported media_type: {media_type}", -1, None)
    return await handler(target, file_path, access_token, app_id, reply_to_id)


async def execute_send_queue(target, queue, access_token, app_id, reply_to_id=None):
    results = []
    for item in queue:
        if not isinstance(item, SendQueueItem):
            logger.warning("qq send queue skipped non-SendQueueItem value: %r", item)
            results.append(MediaSendResult(False, "invalid queue item", -1, None))
            continue
        if item.type == "text":
            continue
        if item.type == "image":
            results.append(await send_photo(target, item.content, access_token, app_id, reply_to_id))
            continue
        if item.type == "video":
            results.append(await send_video_msg(target, item.content, access_token, app_id, reply_to_id))
            continue
        if item.type == "voice":
            results.append(await send_voice(target, item.content, access_token, app_id, reply_to_id))
            continue
        if item.type == "file":
            results.append(await send_document(target, item.content, access_token, app_id, reply_to_id))
            continue
        logger.warning("qq send queue skipped unsupported item type: %s", item.type)
        results.append(MediaSendResult(False, f"unsupported queue item type: {item.type}", -1, None))
    return results


__all__ = [
    "API_BASE",
    "MediaFileType",
    "MediaSendResult",
    "MediaTargetContext",
    "SendQueueItem",
    "api_request",
    "execute_send_queue",
    "send_document",
    "send_media_auto",
    "send_media_message",
    "send_photo",
    "send_video_msg",
    "send_voice",
    "upload_file_url",
    "upload_local_file",
]
