# -*- coding: utf-8 -*-
"""QQ chunked upload implementation for large files."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections import namedtuple
from typing import Any, Dict, List, Optional

import aiohttp

API_BASE = "https://api.sgroup.qq.com"

logger = logging.getLogger(__name__)

ChunkedUploadProgress = namedtuple(
    "ChunkedUploadProgress",
    "completed_parts total_parts uploaded_bytes total_bytes",
)
ChunkedUploadOptions = namedtuple(
    "ChunkedUploadOptions",
    "on_progress log_prefix",
)

DEFAULT_CONCURRENT_PARTS = 1
MAX_CONCURRENT_PARTS = 10
PART_UPLOAD_TIMEOUT_MS = 300000


async def _api_request(
    session: aiohttp.ClientSession,
    access_token: str,
    method: str,
    path: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make HTTP request to QQ API."""
    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"QQBot {access_token}",
        "Content-Type": "application/json",
    }
    async with session.request(
        method, url, json=data, headers=headers, timeout=aiohttp.ClientTimeout(total=60)
    ) as resp:
        result = await resp.json()
        if resp.status >= 400:
            raise QQApiError(f"API {path} failed: {resp.status} {result}", resp.status, result)
        return result


class QQApiError(Exception):
    """QQ API error."""

    def __init__(self, message: str, status: int, data: Any):
        super().__init__(message)
        self.status = status
        self.data = data


async def _upload_prepare(
    session: aiohttp.ClientSession,
    access_token: str,
    target_type: str,
    target_id: str,
    file_path: str,
    file_type: int,
) -> Dict[str, Any]:
    """Call upload_prepare API."""
    file_size = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    data = {
        "file_type": file_type,
        "file_size": file_size,
        "sha256": file_hash,
    }
    path = f"/v2/media/{target_type}/{target_id}/upload_prepare"
    return await _api_request(session, access_token, "POST", path, data)


async def _upload_part(
    session: aiohttp.ClientSession,
    access_token: str,
    target_type: str,
    target_id: str,
    upload_id: str,
    part_number: int,
    data: bytes,
    file_type: int,
) -> Dict[str, Any]:
    """Upload single part."""
    path = f"/v2/media/{target_type}/{target_id}/upload/{upload_id}/part/{part_number}"
    headers = {
        "Authorization": f"QQBot {access_token}",
        "Content-Type": "application/octet-stream",
    }
    url = f"{API_BASE}{path}"
    async with session.put(
        url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=300)
    ) as resp:
        result = await resp.json()
        if resp.status >= 400:
            raise QQApiError(f"Upload part {part_number} failed: {resp.status}", resp.status, result)
        return result


async def _complete_upload(
    session: aiohttp.ClientSession,
    access_token: str,
    target_type: str,
    target_id: str,
    upload_id: str,
    part_keys: List[str],
    file_type: int,
) -> Dict[str, Any]:
    """Complete upload and get file_info."""
    data = {
        "upload_id": upload_id,
        "part_info": [{"part_number": i + 1, "part_key": key} for i, key in enumerate(part_keys)],
    }
    path = f"/v2/media/{target_type}/{target_id}/upload_complete"
    return await _api_request(session, access_token, "POST", path, data)


async def chunked_upload_c2c(
    app_id: str,
    client_secret: str,
    user_id: str,
    file_path: str,
    file_type: int,
    access_token: str,
) -> str:
    """Chunked upload for C2C messages."""
    async with aiohttp.ClientSession() as session:
        prepare_result = await _upload_prepare(
            session, access_token, "users", user_id, file_path, file_type
        )
        upload_id = prepare_result.get("upload_id")
        block_size = prepare_result.get("block_size", 1024 * 1024)

        file_size = os.path.getsize(file_path)
        total_parts = (file_size + block_size - 1) // block_size
        part_keys = []

        with open(file_path, "rb") as f:
            for part_num in range(total_parts):
                chunk = f.read(block_size)
                result = await _upload_part(
                    session, access_token, "users", user_id, upload_id, part_num + 1, chunk, file_type
                )
                part_keys.append(result.get("part_key", ""))

        complete_result = await _complete_upload(
            session, access_token, "users", user_id, upload_id, part_keys, file_type
        )
        return complete_result.get("file_info", "")


async def chunked_upload_group(
    app_id: str,
    client_secret: str,
    group_id: str,
    file_path: str,
    file_type: int,
    access_token: str,
) -> str:
    """Chunked upload for Group messages."""
    async with aiohttp.ClientSession() as session:
        prepare_result = await _upload_prepare(
            session, access_token, "groups", group_id, file_path, file_type
        )
        upload_id = prepare_result.get("upload_id")
        block_size = prepare_result.get("block_size", 1024 * 1024)

        file_size = os.path.getsize(file_path)
        total_parts = (file_size + block_size - 1) // block_size
        part_keys = []

        with open(file_path, "rb") as f:
            for part_num in range(total_parts):
                chunk = f.read(block_size)
                result = await _upload_part(
                    session, access_token, "groups", group_id, upload_id, part_num + 1, chunk, file_type
                )
                part_keys.append(result.get("part_key", ""))

        complete_result = await _complete_upload(
            session, access_token, "groups", group_id, upload_id, part_keys, file_type
        )
        return complete_result.get("file_info", "")


def get_media_file_type(media_type: str) -> int:
    """Map media type string to QQ API file_type int."""
    mapping = {
        "image": 1,
        "video": 2,
        "audio": 3,
        "file": 4,
        "voice": 3,
    }
    return mapping.get(media_type.lower(), 4)
