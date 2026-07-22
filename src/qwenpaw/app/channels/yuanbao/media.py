# -*- coding: utf-8 -*-
"""Yuanbao media upload: COS pre-signed upload via genUploadInfo API.

Flow:
1. Call /api/resource/genUploadInfo to get COS temporary credentials
2. PUT upload to Tencent COS with HMAC-SHA1 signature
3. Return the CDN resourceUrl for use in TIMImageElem / TIMFileElem
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

import aiohttp

logger = logging.getLogger(__name__)

UPLOAD_INFO_PATH = "/api/resource/genUploadInfo"
DOWNLOAD_INFO_PATH = "/api/resource/v1/download"
MAX_UPLOAD_MB = 20


@dataclass
class CosUploadConfig:
    """COS pre-signed upload configuration from genUploadInfo API."""

    bucket_name: str
    region: str
    location: str
    secret_id: str
    secret_key: str
    token: str
    start_time: int
    expired_time: int
    resource_url: str
    resource_id: str = ""


@dataclass
class UploadResult:
    """Result of a successful media upload."""

    url: str
    filename: str
    size: int
    mime_type: str
    uuid_hex: str
    width: int = 0
    height: int = 0


def _hmac_sha1(key: str, message: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha1).hexdigest()


def _sha1_hex(data: str) -> str:
    return hashlib.sha1(data.encode()).hexdigest()


def _guess_mime(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": (
            "application/vnd.openxmlformats-"
            "officedocument.wordprocessingml.document"
        ),
        ".xls": "application/vnd.ms-excel",
        ".xlsx": (
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
        ".txt": "text/plain",
        ".zip": "application/zip",
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".wav": "audio/wav",
    }
    return mime_map.get(ext, "application/octet-stream")


def _parse_image_size(data: bytes) -> Tuple[int, int]:
    """Parse image dimensions from raw bytes (PNG/JPEG).

    Returns (width, height).
    """
    if len(data) >= 24 and data[:4] == b"\x89PNG":
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height

    if len(data) >= 4 and data[0:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC2):
                h_start = i + 5
                w_start = i + 7
                height = int.from_bytes(data[h_start : h_start + 2], "big")
                width = int.from_bytes(data[w_start : w_start + 2], "big")
                return width, height
            if i + 3 < len(data):
                seg_start = i + 2
                i += 2 + int.from_bytes(data[seg_start : seg_start + 2], "big")
            else:
                break

    return 0, 0


def _sign_cos_request(
    secret_id: str,
    secret_key: str,
    method: str,
    pathname: str,
    headers: Dict[str, str],
    start_time: int,
    expired_time: int,
) -> str:
    """Generate COS request authorization header (HMAC-SHA1)."""
    key_time = f"{start_time};{expired_time}"
    sign_key = _hmac_sha1(secret_key, key_time)

    sorted_header_keys = sorted(k.lower() for k in headers)
    header_list = ";".join(sorted_header_keys)
    http_headers = "&".join(
        f"{k}={quote(headers[next(h for h in headers if h.lower() == k)], safe='')}"  # noqa: E501
        for k in sorted_header_keys
    )

    http_string = f"{method.lower()}\n{pathname}\n\n{http_headers}\n"
    string_to_sign = f"sha1\n{key_time}\n{_sha1_hex(http_string)}\n"
    signature = _hmac_sha1(sign_key, string_to_sign)

    return "&".join(
        [
            "q-sign-algorithm=sha1",
            f"q-ak={secret_id}",
            f"q-sign-time={key_time}",
            f"q-key-time={key_time}",
            f"q-header-list={header_list}",
            "q-url-param-list=",
            f"q-signature={signature}",
        ],
    )


async def get_upload_info(
    session: aiohttp.ClientSession,
    api_domain: str,
    auth_headers: Dict[str, str],
    filename: str,
) -> CosUploadConfig:
    """Call genUploadInfo API to get COS pre-signed upload config."""
    domain = api_domain.rstrip("/")
    if not domain.startswith("http"):
        domain = f"https://{domain}"

    url = f"{domain}{UPLOAD_INFO_PATH}"
    file_id = uuid.uuid4().hex
    body = {
        "fileName": filename,
        "fileId": file_id,
        "docFrom": "localDoc",
        "docOpenId": "",
    }

    async with session.post(url, json=body, headers=auth_headers) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"genUploadInfo failed: {resp.status} {text}")

        data = await resp.json()

    # The API may wrap the result in a "data" field
    if "data" in data and isinstance(data["data"], dict):
        data = data["data"]

    bucket = data.get("bucketName", "")
    location = data.get("location", "")
    if not bucket or not location:
        raise RuntimeError(f"genUploadInfo incomplete: {data}")

    return CosUploadConfig(
        bucket_name=bucket,
        region=data.get("region", ""),
        location=location,
        secret_id=data.get("encryptTmpSecretId", ""),
        secret_key=data.get("encryptTmpSecretKey", ""),
        token=data.get("encryptToken", ""),
        start_time=data.get("startTime", int(time.time())),
        expired_time=data.get("expiredTime", int(time.time()) + 1800),
        resource_url=data.get("resourceUrl", ""),
        resource_id=data.get("resourceID", ""),
    )


async def upload_to_cos(
    session: aiohttp.ClientSession,
    config: CosUploadConfig,
    data: bytes,
    mime_type: str,
) -> str:
    """Upload a buffer to COS via PUT Object REST API.

    Returns resourceUrl.
    """
    pathname = (
        config.location
        if config.location.startswith("/")
        else f"/{config.location}"
    )
    host = f"{config.bucket_name}.cos.{config.region}.myqcloud.com"

    # Headers for signature
    sign_headers: Dict[str, str] = {
        "host": host,
        "content-length": str(len(data)),
    }

    # Extra headers
    extra_headers: Dict[str, str] = {}
    if mime_type.startswith("image/"):
        extra_headers["Content-Type"] = mime_type
        extra_headers["Pic-Operations"] = json.dumps(
            {
                "is_pic_info": 1,
                "rules": [
                    {
                        "fileid": config.location,
                        "rule": "imageMogr2/format/jpg",
                    },
                ],
            },
        )
    else:
        extra_headers["Content-Type"] = "application/octet-stream"

    if config.token:
        token_key = "x-cos-security-token"
        sign_headers[token_key] = config.token
        extra_headers[token_key] = config.token

    authorization = _sign_cos_request(
        secret_id=config.secret_id,
        secret_key=config.secret_key,
        method="PUT",
        pathname=pathname,
        headers=sign_headers,
        start_time=config.start_time,
        expired_time=config.expired_time,
    )

    url = f"https://{host}{pathname}"
    all_headers = {**extra_headers, "Authorization": authorization}

    async with session.put(url, data=data, headers=all_headers) as resp:
        if resp.status not in (200, 204):
            body = await resp.text()
            raise RuntimeError(
                f"COS upload failed: {resp.status} {body[:200]}",
            )

    return config.resource_url


async def download_and_upload_media(
    media_path: str,
    session: aiohttp.ClientSession,
    api_domain: str,
    auth_headers: Dict[str, str],
) -> UploadResult:
    """Download a file (local path or URL) and upload to COS.

    Returns UploadResult with the CDN URL for use in message body.
    """
    file_data: bytes
    filename: str

    # Resolve local file (file:// URI or absolute path)
    local_path = _resolve_local_path(media_path)
    if local_path and os.path.isfile(local_path):
        file_data = Path(local_path).read_bytes()
        filename = os.path.basename(local_path)
        logger.info(
            "yuanbao media: read local file %s (%s bytes)",
            filename,
            len(file_data),
        )
    elif media_path.startswith(("http://", "https://")):
        async with session.get(media_path) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to download media: {resp.status}")
            file_data = await resp.read()
            parsed = urlparse(media_path)
            filename = os.path.basename(parsed.path) or "file"
        logger.info(
            "yuanbao media: downloaded %s (%s bytes)",
            filename,
            len(file_data),
        )
    else:
        raise RuntimeError(f"Cannot resolve media path: {media_path}")

    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    if len(file_data) > max_bytes:
        raise RuntimeError(
            f"File too large: "
            f"{len(file_data) / 1024 / 1024:.1f} MB "
            f"> {MAX_UPLOAD_MB} MB",
        )

    mime_type = _guess_mime(filename)
    file_uuid = hashlib.md5(file_data).hexdigest()
    width, height = (0, 0)
    if mime_type.startswith("image/"):
        width, height = _parse_image_size(file_data)

    # Step 1: Get COS upload config
    cos_config = await get_upload_info(
        session,
        api_domain,
        auth_headers,
        filename,
    )

    # Step 2: Upload to COS
    resource_url = await upload_to_cos(
        session,
        cos_config,
        file_data,
        mime_type,
    )

    logger.info("yuanbao media: uploaded %s → %s", filename, resource_url[:80])

    return UploadResult(
        url=resource_url,
        filename=filename,
        size=len(file_data),
        mime_type=mime_type,
        uuid_hex=file_uuid,
        width=width,
        height=height,
    )


def _resolve_local_path(url: str) -> Optional[str]:
    """Resolve file:// URI or local absolute path to filesystem path."""
    if not url:
        return None
    if url.startswith("file://"):
        parsed = urlparse(url)
        return unquote(parsed.path)
    if url.startswith("/") and not url.startswith("http"):
        return url
    return None


def build_image_msg_body(result: UploadResult) -> list:
    """Build TIMImageElem message body from upload result."""
    return [
        {
            "msg_type": "TIMImageElem",
            "msg_content": {
                "uuid": result.uuid_hex,
                "image_format": 255,
                "image_info_array": [
                    {
                        "type": 1,
                        "size": result.size,
                        "width": result.width,
                        "height": result.height,
                        "url": result.url,
                    },
                ],
            },
        },
    ]


def build_file_msg_body(result: UploadResult) -> list:
    """Build TIMFileElem message body from upload result."""
    return [
        {
            "msg_type": "TIMFileElem",
            "msg_content": {
                "uuid": result.uuid_hex,
                "file_name": result.filename,
                "file_size": result.size,
                "url": result.url,
            },
        },
    ]


def _extract_resource_id(url: str) -> Optional[str]:
    """Extract resourceId from a Yuanbao CDN URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    resource_ids = params.get("resourceId", [])
    return resource_ids[0] if resource_ids else None


async def resolve_download_url(
    media_url: str,
    session: aiohttp.ClientSession,
    api_domain: str,
    auth_headers: Dict[str, str],
) -> str:
    """Resolve a Yuanbao CDN URL to a real download URL via the download API.

    If the URL contains a resourceId query param, calls the download API
    to get a pre-signed URL. Otherwise returns the original URL.
    """
    resource_id = _extract_resource_id(media_url)
    if not resource_id:
        return media_url

    domain = api_domain.rstrip("/")
    if not domain.startswith("http"):
        domain = f"https://{domain}"

    url = f"{domain}{DOWNLOAD_INFO_PATH}"
    params = {"resourceId": resource_id}

    try:
        async with session.get(
            url,
            params=params,
            headers=auth_headers,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.warning(
                    "yuanbao: download API failed: %s %s",
                    resp.status,
                    text[:100],
                )
                return media_url

            data = await resp.json()

        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]

        download_url = data.get("url") or data.get("realUrl") or ""
        if download_url:
            logger.debug(
                "yuanbao: resolved download URL for resourceId=%s",
                resource_id,
            )
            return download_url
    except Exception as exc:
        logger.warning("yuanbao: resolve download URL failed: %s", exc)

    return media_url
