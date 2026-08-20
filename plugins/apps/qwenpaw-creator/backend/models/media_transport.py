# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-return-statements
import asyncio
import base64
import hashlib
import io
import mimetypes
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from PIL import Image

from models import config as model_config
from services.runtime_files.safe_remote_download import safe_download_bytes
from utils.logger import setup_logger
from utils.paths import local_path_from_file_url, media_path_from_url

logger = setup_logger("models.media_transport")

OSS_POLICY_URL = "https://dashscope.aliyuncs.com/api/v1/uploads"
DEFAULT_CREATOR_MEDIA_BUCKET = "creator-store"
WAN_MEDIA_PREFIX = "wan_media"
SD2_MEDIA_PREFIX = "sd2_media"
GROUNDING_LENS_MEDIA_PREFIX = "grounding_lens"
UGUU_UPLOAD_URL = "https://uguu.se/upload"
UGUU_UPLOAD_MAX_ATTEMPTS = 5
UGUU_RETRY_BACKOFF_CAP_SECONDS = 10.0
# When configured, Creator OSS keeps Lens media private behind a short-lived
# signed URL; callers use Uguu only when OSS configuration is entirely absent.
GROUNDING_LENS_SIGNED_URL_EXPIRES_SECONDS = 15 * 60
DASHSCOPE_TEMP_UPLOAD_MAX_BYTES = 1024 * 1024 * 1024
DASHSCOPE_TEMP_UPLOAD_CACHE_SECONDS = 47 * 60 * 60
# Ark (Volcengine) Seedance accepts Base64 data URLs for reference images:
# a single image must stay below 30MB and the request body below 64MB.
SEEDANCE_REFERENCE_IMAGE_MAX_BYTES = 30 * 1024 * 1024
REFERENCE_IMAGE_DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024

_dashscope_temp_upload_cache: dict[
    tuple[str, int, int, str, str],
    tuple[str, float],
] = {}
_dashscope_temp_upload_locks: dict[
    tuple[str, int, int, str, str],
    asyncio.Lock,
] = {}
_dashscope_credential_tokens: dict[str, str] = {}
# Process-local salt for credential cache tokens; never persisted.
_CREDENTIAL_TOKEN_SALT = uuid.uuid4().bytes


async def get_oss_policy(model: str = "wan2.7-r2v") -> dict:
    api_key = model_config.get_oss_policy_api_key()
    if not api_key:
        raise RuntimeError(
            "creator_media_oss.policy_api_key or OSS_POLICY_API_KEY is required for OSS upload policy",
        )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            OSS_POLICY_URL,
            params={"action": "getPolicy", "model": model},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        return resp.json().get("data", resp.json())


async def upload_file_to_oss(
    file_content: bytes,
    filename: str,
    policy_data: dict,
) -> str:
    """Upload a file to OSS using the policy credentials. Returns oss:// URL."""
    upload_host = policy_data["upload_host"]
    upload_dir = policy_data["upload_dir"]
    key = f"{upload_dir}/{filename}"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            upload_host,
            data={
                "OSSAccessKeyId": policy_data["oss_access_key_id"],
                "Signature": policy_data["signature"],
                "policy": policy_data["policy"],
                "x-oss-object-acl": policy_data.get(
                    "x_oss_object_acl",
                    "default",
                ),
                "x-oss-forbid-overwrite": policy_data.get(
                    "x_oss_forbid_overwrite",
                    "true",
                ),
                "key": key,
                "success_action_status": "200",
            },
            files={"file": (filename, file_content)},
        )
        resp.raise_for_status()

    return f"oss://{key}"


def _dashscope_transport_filename(path: Path, media_type: str) -> str:
    filename = path.name or "selected-media"
    if not Path(filename).suffix:
        extension = mimetypes.guess_extension(media_type) or ".bin"
        filename = f"{filename}{extension}"
    return _safe_filename(filename)


def _credential_cache_token(api_key: str) -> str:
    """Opaque per-process stand-in for *api_key* inside cache keys.

    Keys are salted PBKDF2 digests so raw credentials never persist in
    process memory maps and cannot be cheaply brute-forced; values are
    random tokens that keep entries isolated.
    """
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        api_key.encode("utf-8"),
        _CREDENTIAL_TOKEN_SALT,
        50_000,
    ).hex()
    if len(_dashscope_credential_tokens) >= 256:
        _dashscope_credential_tokens.clear()
    return _dashscope_credential_tokens.setdefault(digest, uuid.uuid4().hex)


def _prune_dashscope_temp_upload_cache(now: float) -> None:
    expired = [
        key
        for key, (_, deadline) in _dashscope_temp_upload_cache.items()
        if deadline <= now
    ]
    for key in expired:
        _dashscope_temp_upload_cache.pop(key, None)
        lock = _dashscope_temp_upload_locks.get(key)
        if lock is not None and not lock.locked():
            _dashscope_temp_upload_locks.pop(key, None)


def _dashscope_temp_upload_cache_key(
    path: Path,
    *,
    api_key: str,
    model_name: str,
) -> tuple[str, int, int, str, str]:
    stat = path.stat()
    credential_fingerprint = _credential_cache_token(api_key)
    return (
        str(path.resolve()),
        int(stat.st_size),
        int(stat.st_mtime_ns),
        model_name,
        credential_fingerprint,
    )


def _mask_key(key: str, prefix: int = 10) -> str:
    if not key:
        return "(empty)"
    if len(key) <= prefix:
        return key
    return f"{key[:prefix]}...({len(key)} chars)"


def _fetch_dashscope_upload_policy(
    client: httpx.Client,
    *,
    api_key: str,
    model_name: str,
    size: int,
) -> dict:
    """Fetch the model-bound upload policy and enforce its size limit."""
    logger.info(
        "DashScope upload policy request | url=%s, model=%s, api_key=%s, size=%d",
        OSS_POLICY_URL,
        model_name,
        _mask_key(api_key),
        size,
    )
    policy_response = client.get(
        OSS_POLICY_URL,
        params={"action": "getPolicy", "model": model_name},
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    logger.info(
        "DashScope upload policy response | status=%d, body=%s",
        policy_response.status_code,
        policy_response.text[:500],
    )
    policy_response.raise_for_status()
    payload = policy_response.json()
    policy = payload.get("data", payload)
    try:
        max_policy_bytes = int(
            float(policy["max_file_size_mb"]) * 1024 * 1024,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "DashScope upload policy missing max_file_size_mb",
        ) from exc
    if size > max_policy_bytes:
        raise RuntimeError(
            "media exceeds the current model-bound DashScope upload "
            f"policy ({size} bytes > {max_policy_bytes} bytes); provide a safe "
            "public nativeModelUrl/publicSourceUrl",
        )
    return policy


def _post_dashscope_temp_upload(
    client: httpx.Client,
    policy: dict,
    filename: str,
    file_source: object,
    media_type: str,
) -> str:
    """POST one payload to the policy's temporary OSS. Returns oss:// URL."""
    upload_dir = str(policy["upload_dir"]).rstrip("/")
    key = f"{upload_dir}/{uuid.uuid4().hex}-{filename}"
    form = {
        "OSSAccessKeyId": str(policy["oss_access_key_id"]),
        "Signature": str(policy["signature"]),
        "policy": str(policy["policy"]),
        "x-oss-object-acl": str(policy.get("x_oss_object_acl", "private")),
        "x-oss-forbid-overwrite": str(
            policy.get("x_oss_forbid_overwrite", "true"),
        ),
        "key": key,
        "success_action_status": "200",
    }
    upload_response = client.post(
        str(policy["upload_host"]),
        data=form,
        files={"file": (filename, file_source, media_type)},
    )
    upload_response.raise_for_status()
    return f"oss://{key}"


def _upload_local_file_to_dashscope_temp_sync(
    path: Path,
    *,
    api_key: str,
    model_name: str,
    media_type: str,
) -> str:
    """Stream one local file to DashScope's model-bound temporary OSS."""

    size = path.stat().st_size
    if size > DASHSCOPE_TEMP_UPLOAD_MAX_BYTES:
        raise RuntimeError(
            "DashScope temporary upload rejects files larger than 1GB; "
            "provide a safe public nativeModelUrl/publicSourceUrl instead",
        )
    logger.info(
        "DashScope temp upload start | path=%s, size=%d, model=%s, media_type=%s",
        path,
        size,
        model_name,
        media_type,
    )
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=3600.0, pool=30.0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        policy = _fetch_dashscope_upload_policy(
            client,
            api_key=api_key,
            model_name=model_name,
            size=size,
        )
        filename = _dashscope_transport_filename(path, media_type)
        with path.open("rb") as file_handle:
            result = _post_dashscope_temp_upload(
                client,
                policy,
                filename,
                file_handle,
                media_type,
            )
            logger.info("DashScope temp upload complete | result=%s", result)
            return result


async def upload_local_file_to_dashscope_temp(
    path: Path,
    *,
    api_key: str,
    model_name: str,
    media_type: str,
) -> str:
    """Return a cached 48-hour provider URL without reading the file into memory."""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(
            f"selected local media does not exist: {resolved}",
        )
    if not api_key.strip() or not model_name.strip():
        raise RuntimeError(
            "DashScope temporary upload requires API key and model name",
        )
    cache_key = _dashscope_temp_upload_cache_key(
        resolved,
        api_key=api_key,
        model_name=model_name,
    )
    now = time.monotonic()
    _prune_dashscope_temp_upload_cache(now)
    cached = _dashscope_temp_upload_cache.get(cache_key)
    if cached is not None and cached[1] > now:
        return cached[0]
    lock = _dashscope_temp_upload_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _dashscope_temp_upload_cache.get(cache_key)
        if cached is not None and cached[1] > now:
            return cached[0]
        url = await asyncio.to_thread(
            _upload_local_file_to_dashscope_temp_sync,
            resolved,
            api_key=api_key,
            model_name=model_name,
            media_type=media_type,
        )
        _dashscope_temp_upload_cache[cache_key] = (
            url,
            now + DASHSCOPE_TEMP_UPLOAD_CACHE_SECONDS,
        )
        return url


def _reference_media_type(filename: str, content: bytes) -> str:
    media_type = mimetypes.guess_type(filename or "")[0]
    if not media_type:
        media_type = mimetypes.guess_type(
            f"reference{_suffix_from_magic(content)}",
        )[0]
    return media_type or "application/octet-stream"


def _upload_reference_bytes_to_dashscope_temp_sync(
    content: bytes,
    filename: str,
    *,
    api_key: str,
    model_name: str,
) -> str:
    size = len(content)
    if size > DASHSCOPE_TEMP_UPLOAD_MAX_BYTES:
        raise RuntimeError(
            "DashScope temporary upload rejects files larger than 1GB",
        )
    media_type = _reference_media_type(filename, content)
    logger.info(
        "DashScope reference upload start | filename=%s, size=%d, model=%s, media_type=%s",
        filename,
        size,
        model_name,
        media_type,
    )
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=3600.0, pool=30.0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        policy = _fetch_dashscope_upload_policy(
            client,
            api_key=api_key,
            model_name=model_name,
            size=size,
        )
        result = _post_dashscope_temp_upload(
            client,
            policy,
            _safe_filename(filename),
            content,
            media_type,
        )
        logger.info("DashScope reference upload complete | result=%s", result)
        return result


async def upload_reference_bytes_to_dashscope_temp(
    content: bytes,
    filename: str,
    *,
    api_key: str,
    model_name: str,
) -> str:
    """Upload in-memory reference media to DashScope's model-bound temp OSS.

    Official Bailian temporary-file upload (getPolicy + form POST). The URL is
    an ``oss://`` reference valid for 48 hours (files up to 1GB) and is only
    resolvable by the bound model when the request carries the
    ``X-DashScope-OssResourceResolve: enable`` header.
    """
    if not api_key.strip() or not model_name.strip():
        raise RuntimeError(
            "DashScope temporary upload requires API key and model name",
        )
    return await asyncio.to_thread(
        _upload_reference_bytes_to_dashscope_temp_sync,
        content,
        filename,
        api_key=api_key,
        model_name=model_name,
    )


def reference_media_data_url(content: bytes, filename: str) -> str:
    """Inline reference media as a Base64 data URL for the Ark Seedance API.

    Volcengine's video-generation task API accepts ``data:<mime>;base64,...``
    reference images directly (the Ark File API's file_id is only usable by
    Chat/Responses), so no upload or extra storage configuration is needed.
    """
    if len(content) >= SEEDANCE_REFERENCE_IMAGE_MAX_BYTES:
        raise RuntimeError(
            "Seedance reference images must be smaller than 30MB; "
            "downscale the media or provide a public HTTPS URL",
        )
    media_type = _reference_media_type(filename, content)
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _creator_media_bucket() -> str:
    return model_config.get_oss_bucket(DEFAULT_CREATOR_MEDIA_BUCKET)


def _creator_media_public_base_url() -> str:
    return model_config.get_oss_public_base_url()


def creator_oss_readiness() -> dict:
    """Return explicit absent/ready/invalid Creator OSS readiness."""
    access_key_id = model_config.get_oss_access_key_id()
    access_key_secret = model_config.get_oss_access_key_secret()
    endpoint = model_config.get_oss_endpoint()
    configured = bool(
        access_key_id
        or access_key_secret
        or endpoint
        or model_config.get_oss_bucket("")
        or _creator_media_public_base_url(),
    )
    blockers = []
    if not access_key_id:
        blockers.append(
            "creator_media_oss.access_key_id or OSS_ACCESS_KEY_ID is required",
        )
    if not access_key_secret:
        blockers.append(
            "creator_media_oss.access_key_secret or OSS_ACCESS_KEY_SECRET is required",
        )
    if not endpoint:
        blockers.append(
            "creator_media_oss.endpoint or OSS_ENDPOINT is required",
        )
    return {
        "status": (
            "ready" if not blockers else "invalid" if configured else "absent"
        ),
        "bucket": _creator_media_bucket(),
        "endpoint_set": bool(endpoint),
        "access_key_set": bool(access_key_id and access_key_secret),
        "public_base_url_set": bool(_creator_media_public_base_url()),
        "blockers": blockers,
    }


def _safe_filename(filename: str) -> str:
    stem = Path(filename or "reference").stem or "reference"
    suffix = Path(filename or "").suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "reference"
    if not suffix or not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix):
        suffix = ".bin"
    return f"{stem}{suffix}"


def _object_key(filename: str, backend: str) -> str:
    prefix = SD2_MEDIA_PREFIX if backend == "seedance2" else WAN_MEDIA_PREFIX
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{prefix}/{date}/{uuid.uuid4().hex}-{_safe_filename(filename)}"


def _public_url(endpoint: str, bucket: str, key: str) -> str:
    quoted_key = quote(key)
    public_base_url = _creator_media_public_base_url()
    if public_base_url:
        return f"{public_base_url.rstrip('/')}/{quoted_key}"
    endpoint_host = (
        endpoint.replace("https://", "").replace("http://", "").rstrip("/")
    )
    return f"https://{bucket}.{endpoint_host}/{quoted_key}"


def _upload_with_oss2(file_content: bytes, filename: str, backend: str) -> str:
    try:
        import oss2  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "oss2 package is required for creator-media uploads",
        ) from exc

    access_key_id = model_config.get_oss_access_key_id()
    access_key_secret = model_config.get_oss_access_key_secret()
    endpoint = model_config.get_oss_endpoint()
    if not access_key_id or not access_key_secret or not endpoint:
        readiness = creator_oss_readiness()
        raise RuntimeError("; ".join(readiness["blockers"]))

    bucket_name = _creator_media_bucket()
    key = _object_key(filename, backend)
    content_type = (
        mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    headers = {
        "Content-Type": content_type,
        "x-oss-object-acl": "public-read",
    }
    bucket.put_object(key, file_content, headers=headers)
    return _public_url(endpoint, bucket_name, key)


async def upload_reference_media_to_creator_oss(
    file_content: bytes,
    filename: str,
    backend: str,
) -> str:
    """Upload reference media to creator-media and return a public HTTPS URL."""
    if backend not in {"wan", "seedance2"}:
        raise ValueError(
            f"Unsupported video backend for OSS upload: {backend}",
        )
    return await asyncio.to_thread(
        _upload_with_oss2,
        file_content,
        filename,
        backend,
    )


def _presign_upload_with_oss2(
    file_content: bytes,
    filename: str,
    expires_seconds: int,
) -> str:
    try:
        import oss2  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "oss2 package is required for creator-media uploads",
        ) from exc

    access_key_id = model_config.get_oss_access_key_id()
    access_key_secret = model_config.get_oss_access_key_secret()
    endpoint = model_config.get_oss_endpoint()
    if not access_key_id or not access_key_secret or not endpoint:
        readiness = creator_oss_readiness()
        raise RuntimeError("; ".join(readiness["blockers"]))

    bucket_name = _creator_media_bucket()
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = (
        f"{GROUNDING_LENS_MEDIA_PREFIX}/{date}/"
        f"{uuid.uuid4().hex}-{_safe_filename(filename)}"
    )
    content_type = (
        mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    # Keep the bucket default (private) ACL: the object is only reachable
    # through the expiring signed URL below.
    bucket.put_object(
        key,
        file_content,
        headers={"Content-Type": content_type},
    )
    return bucket.sign_url("GET", key, expires_seconds)


async def upload_image_for_temporary_public_url(
    file_content: bytes,
    filename: str,
    *,
    expires_seconds: int = GROUNDING_LENS_SIGNED_URL_EXPIRES_SECONDS,
) -> str:
    """Upload an image privately and return a short-lived presigned URL."""
    return await asyncio.to_thread(
        _presign_upload_with_oss2,
        file_content,
        filename,
        expires_seconds,
    )


def _is_retryable_upload_response(response: httpx.Response) -> bool:
    return response.status_code == 429 or response.status_code >= 500


async def upload_image_to_uguu_for_temporary_public_url(
    file_content: bytes,
    filename: str,
    *,
    max_attempts: int = UGUU_UPLOAD_MAX_ATTEMPTS,
) -> str:
    """Upload one validated image to Uguu and return its temporary URL."""
    attempts = max(1, int(max_attempts))
    media_type = (
        mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
    ) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.post(
                    UGUU_UPLOAD_URL,
                    files={
                        "files[]": (filename, file_content, media_type),
                    },
                )
                if _is_retryable_upload_response(response):
                    response.raise_for_status()
                response.raise_for_status()
                payload = response.json()
                files = (
                    payload.get("files") if isinstance(payload, dict) else None
                )
                public_url = (
                    str(files[0].get("url") or "").strip()
                    if isinstance(files, list)
                    and files
                    and isinstance(files[0], dict)
                    else ""
                )
                if not public_url.startswith("https://"):
                    raise RuntimeError(
                        "Uguu upload response did not contain a public HTTPS URL",
                    )
                return public_url
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not _is_retryable_upload_response(exc.response):
                    raise
            if attempt >= attempts:
                break
            await asyncio.sleep(
                min(
                    UGUU_RETRY_BACKOFF_CAP_SECONDS,
                    float(2 ** (attempt - 1)),
                ),
            )
    raise RuntimeError(
        f"Uguu upload failed after {attempts} attempts: {last_error}",
    )


async def read_reference_media(
    url: str,
    *,
    max_bytes: int = REFERENCE_IMAGE_DOWNLOAD_MAX_BYTES,
) -> tuple[bytes, str]:
    """Read one bounded local or SSRF-safe public reference into memory."""

    if max_bytes <= 0:
        raise ValueError("reference media max_bytes must be positive")

    def read_local_bounded(media_path: Path) -> bytes:
        if media_path.stat().st_size > max_bytes:
            raise ValueError(
                f"reference media exceeds {max_bytes} bytes",
            )
        return media_path.read_bytes()

    if url.startswith("file://"):
        media_path = local_path_from_file_url(url)
        content = await asyncio.to_thread(read_local_bounded, media_path)
        filename = media_path.name or f"reference-{uuid.uuid4().hex}"
        if not Path(filename).suffix:
            filename += _suffix_from_magic(content)
        return content, filename
    if url.startswith("/generated/"):
        media_path = media_path_from_url(url)
        content = await asyncio.to_thread(read_local_bounded, media_path)
        return (
            content,
            media_path.name or f"reference-{uuid.uuid4().hex}.bin",
        )
    if url.startswith(("http://", "https://")):
        content = await asyncio.to_thread(
            safe_download_bytes,
            url,
            max_bytes=max_bytes,
            timeout=60.0,
        )
        filename = (
            Path(urlparse(url).path).name
            or f"reference-{uuid.uuid4().hex}.bin"
        )
        return content, filename
    raise ValueError(f"Unsupported reference media URL: {url}")


def validate_reference_image_bytes(content: bytes) -> None:
    """Reject empty, mislabeled, or truncated image-reference payloads."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            image.verify()
    except Exception as exc:
        raise ValueError("reference image cannot be decoded") from exc
    if width <= 0 or height <= 0:
        raise ValueError("reference image has invalid dimensions")


def _suffix_from_magic(content: bytes) -> str:
    """Recover a transport filename for suffix-free content-addressed blobs."""

    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return ".mp4"
    if content.startswith(b"\x1aE\xdf\xa3"):
        return ".webm"
    return ".bin"
