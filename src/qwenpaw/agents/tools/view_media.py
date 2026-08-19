# -*- coding: utf-8 -*-
"""Load image or video files into the LLM context for analysis."""

import asyncio
import hashlib
import ipaddress
import logging
import mimetypes
import os
import socket
import unicodedata
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import httpx
from agentscope.message import (
    DataBlock,
    TextBlock,
    URLSource,
    ToolResultState,
)
from agentscope.tool import ToolChunk

from ...config.context import get_current_workspace_dir
from ...constant import EnvVarLoader, WORKING_DIR
from ...runtime.tool_registry import tool_descriptor
from ...utils.io_utils import make_dirs_async, run_sync_io, write_bytes_async
from ...providers.capping_formatter import MAX_INLINE_MEDIA_BYTES
from .file_io import _path_to_file_url, _resolve_file_path
from ..utils.image_freezing import (
    freeze_image_bytes,
    freeze_local_image,
    validate_image_bytes,
)

logger = logging.getLogger(__name__)

_REMOTE_IMAGE_CHUNK_SIZE = 64 * 1024
_REMOTE_IMAGE_CONNECT_TIMEOUT = 5.0
_REMOTE_IMAGE_READ_TIMEOUT = 10.0
_REMOTE_IMAGE_TOTAL_TIMEOUT = 30.0
_REMOTE_IMAGE_MAX_REDIRECTS = 3
_REMOTE_IMAGE_DOWNLOAD_MAX_MB_ENV = "QWENPAW_REMOTE_IMAGE_DOWNLOAD_MAX_MB"
_REMOTE_IMAGE_DOWNLOAD_DEFAULT_MB = 50
_REMOTE_IMAGE_SUFFIXES = {
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tiff",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class _RemoteImageTarget:
    """Describe one validated remote target with a DNS-pinned URL."""

    request_url: str
    host_header: str
    server_hostname: str


def _remote_image_download_max_bytes() -> int:
    """Return the configured remote image download limit in bytes."""
    max_mb = EnvVarLoader.get_int(
        _REMOTE_IMAGE_DOWNLOAD_MAX_MB_ENV,
        default=_REMOTE_IMAGE_DOWNLOAD_DEFAULT_MB,
    )
    if max_mb <= 0:
        max_mb = _REMOTE_IMAGE_DOWNLOAD_DEFAULT_MB
    return max_mb * 1024 * 1024


def _media_data_block(url: str, modality: str) -> DataBlock:
    """Build a DataBlock from a URL, inferring ``media_type`` from the path.

    Mirrors the behaviour of the deleted ``_compat.message.ImageBlock`` /
    ``VideoBlock`` shim: when ``mimetypes.guess_type`` can't decide we
    fall back to a wildcard like ``image/*`` so the formatter still
    routes the block as the right modality.
    """
    media_type, _ = mimetypes.guess_type(url)
    if not media_type:
        media_type = f"{modality}/*"
    return DataBlock(source=URLSource(url=url, media_type=media_type))


_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
}

_VIDEO_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mpeg",
    ".mov",
    ".avi",
    ".mkv",
}


def _is_url(path: str) -> bool:
    """Return True if *path* looks like an HTTP(S) URL."""
    return path.startswith(("http://", "https://"))


def _resolve_host_addresses(host: str, port: int) -> tuple[str, ...]:
    """Resolve a remote host to its candidate IP addresses."""
    infos = socket.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
    )
    addresses = (
        str(info[4][0]).split("%", maxsplit=1)[0] for info in infos if info[4]
    )
    return tuple(dict.fromkeys(addresses))


def _url_host(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Format an IP address for use as a URL host."""
    return f"[{address}]" if address.version == 6 else str(address)


def _host_header(host: str, port: int | None, scheme: str) -> str:
    """Build the original authority for HTTP virtual hosting."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        authority = host.encode("idna").decode("ascii")
    else:
        authority = _url_host(literal)

    default_port = 443 if scheme == "https" else 80
    if port is not None and port != default_port:
        return f"{authority}:{port}"
    return authority


# pylint: disable-next=too-many-branches,too-many-return-statements
async def _resolve_remote_image_target(
    url: str,
) -> tuple[_RemoteImageTarget | None, str | None]:
    """Validate a URL and pin its request to one checked IP address."""
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (UnicodeError, ValueError):
        return None, "remote image URL is invalid"

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None, "remote image URL must use HTTP or HTTPS"
    if parsed.username is not None or parsed.password is not None:
        return None, "remote image URL must not contain credentials"

    host = parsed.hostname.rstrip(".")
    if host.lower() == "localhost":
        return None, "remote image URL targets a non-public address"

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = await run_sync_io(
                _resolve_host_addresses,
                host,
                port,
            )
        except OSError:
            return None, "remote image host could not be resolved"
    else:
        addresses = (str(literal),)

    if not addresses:
        return None, "remote image host could not be resolved"
    validated: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return None, "remote image host resolved to an invalid address"
        if not address.is_global:
            return None, "remote image URL targets a non-public address"
        validated.append(address)

    selected = validated[0]
    request_netloc = _url_host(selected)
    if parsed.port is not None:
        request_netloc = f"{request_netloc}:{parsed.port}"
    request_url = urllib.parse.urlunsplit(
        (
            parsed.scheme,
            request_netloc,
            parsed.path,
            parsed.query,
            "",
        ),
    )
    try:
        server_hostname = host.encode("idna").decode("ascii")
        host_header = _host_header(host, parsed.port, parsed.scheme)
    except UnicodeError:
        return None, "remote image URL is invalid"
    return (
        _RemoteImageTarget(
            request_url=request_url,
            host_header=host_header,
            server_hostname=server_hostname,
        ),
        None,
    )


# pylint: disable-next=too-many-return-statements
async def _download_remote_image(
    url: str,
    max_bytes: int,
) -> tuple[bytes | None, str | None]:
    """Download one remote image with bounded resource usage."""
    current_url = url
    timeout = httpx.Timeout(
        _REMOTE_IMAGE_READ_TIMEOUT,
        connect=_REMOTE_IMAGE_CONNECT_TIMEOUT,
    )
    try:
        async with asyncio.timeout(_REMOTE_IMAGE_TOTAL_TIMEOUT):
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=timeout,
                trust_env=False,
            ) as client:
                for _ in range(_REMOTE_IMAGE_MAX_REDIRECTS + 1):
                    (
                        target,
                        validation_error,
                    ) = await _resolve_remote_image_target(current_url)
                    if validation_error is not None or target is None:
                        return None, validation_error

                    # Connect to the checked IP while preserving the origin.
                    async with client.stream(
                        "GET",
                        target.request_url,
                        headers={"Host": target.host_header},
                        extensions={
                            "sni_hostname": target.server_hostname,
                        },
                    ) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                return (
                                    None,
                                    "remote image redirect is missing a URL",
                                )
                            current_url = urllib.parse.urljoin(
                                current_url,
                                location,
                            )
                            continue

                        try:
                            response.raise_for_status()
                        except httpx.HTTPStatusError:
                            return (
                                None,
                                "remote server returned HTTP "
                                f"{response.status_code}",
                            )

                        content_length = response.headers.get(
                            "content-length",
                        )
                        if content_length:
                            try:
                                reported_size = int(content_length)
                            except ValueError:
                                reported_size = 0
                            if 0 < max_bytes < reported_size:
                                return (
                                    None,
                                    "remote image exceeds the "
                                    f"{max_bytes}-byte download limit",
                                )

                        content = bytearray()
                        async for chunk in response.aiter_bytes(
                            chunk_size=_REMOTE_IMAGE_CHUNK_SIZE,
                        ):
                            if 0 < max_bytes < len(content) + len(chunk):
                                return (
                                    None,
                                    "remote image exceeds the "
                                    f"{max_bytes}-byte download limit",
                                )
                            content.extend(chunk)
                        return bytes(content), None
                return None, "remote image exceeded redirect limit"
    except (TimeoutError, httpx.TimeoutException):
        return None, "remote image download timed out"
    except (httpx.RequestError, OSError, ValueError):
        return None, "remote image download failed"


def _remote_image_name(url: str) -> str:
    """Return a display-only filename for a remote image URL."""
    path = urllib.parse.urlsplit(url).path
    return Path(unquote(path)).name or "remote-image"


async def _stage_remote_image_for_compression(
    image_bytes: bytes,
    media_type: str,
) -> Path:
    """Store an oversized remote image in the current workspace."""
    workspace_dir = get_current_workspace_dir() or WORKING_DIR
    downloads_dir = workspace_dir / "downloads"
    await make_dirs_async(downloads_dir)

    digest = hashlib.sha256(image_bytes).hexdigest()[:16]
    suffix = _REMOTE_IMAGE_SUFFIXES[media_type]
    image_path = downloads_dir / f"remote-image-{digest}{suffix}"
    await write_bytes_async(
        image_path,
        image_bytes,
        new_file_mode=0o644,
    )
    return image_path.resolve()


def _oversized_remote_image_chunk(
    image_path: Path,
    image_size: int,
) -> ToolChunk:
    """Tell the agent how to process a downloaded oversized image."""
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            TextBlock(
                type="text",
                text=(
                    f"Remote image is {image_size} bytes and exceeds the "
                    f"{MAX_INLINE_MEDIA_BYTES}-byte inline image limit. "
                    f"It was downloaded to: {image_path}. Compress or "
                    "resize this local file below the inline limit, then "
                    "call view_image with the compressed file path."
                ),
            ),
        ],
    )


def _image_error_chunk(error: str | None) -> ToolChunk:
    """Build a text-only result for an unavailable remote image."""
    detail = error or "unknown error"
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            TextBlock(
                type="text",
                text=f"Error: failed to load remote image: {detail}",
            ),
        ],
    )


def _validate_url_extension(
    url: str,
    allowed_extensions: set[str],
    mime_prefix: str,
) -> Optional[ToolChunk]:
    """Optionally validate that the URL path has an allowed extension.

    Returns an error ``ToolChunk`` when the extension is clearly
    unsupported, or ``None`` to let it through (including when the URL
    has no recognisable extension, e.g. dynamic endpoints).
    """
    url_path = urllib.parse.urlparse(url).path
    ext = Path(url_path).suffix.lower()
    if not ext:
        return None
    mime, _ = mimetypes.guess_type(url_path)
    if ext not in allowed_extensions and (
        not mime or not mime.startswith(f"{mime_prefix}/")
    ):
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: URL does not point to a "
                    f"supported {mime_prefix} format: {url}",
                ),
            ],
        )
    return None


def _validate_media_path(
    file_path: str,
    allowed_extensions: set[str],
    mime_prefix: str,
) -> tuple[Path, Optional[ToolChunk]]:
    """Validate a local media file path.

    Returns ``(resolved_path, None)`` on success or
    ``(_, error_response)`` on failure.
    """
    file_path = unquote(file_path)
    file_path = unicodedata.normalize(
        "NFC",
        os.path.expanduser(file_path),
    )
    resolved = Path(_resolve_file_path(file_path))

    if not resolved.exists() or not resolved.is_file():
        return resolved, ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: {file_path} does not exist "
                    "or is not a file.",
                ),
            ],
        )

    ext = resolved.suffix.lower()
    mime, _ = mimetypes.guess_type(str(resolved))
    if ext not in allowed_extensions and (
        not mime or not mime.startswith(f"{mime_prefix}/")
    ):
        return resolved, ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: {resolved.name} is not a "
                    f"supported {mime_prefix} format.",
                ),
            ],
        )

    return resolved, None


def _load_local_image(
    image_path: str,
) -> tuple[Path, DataBlock | None, ToolChunk | None, str | None]:
    """Resolve, validate, and freeze one local image transaction."""
    resolved, validation_error = _validate_media_path(
        image_path,
        _IMAGE_EXTENSIONS,
        "image",
    )
    if validation_error is not None:
        return resolved, None, validation_error, None
    frozen, freeze_error = freeze_local_image(resolved)
    return resolved, frozen, None, freeze_error


async def _probe_multimodal_if_needed(
    media_type: str = "image",
) -> bool | None:
    """Trigger a multimodal probe if capability is unknown (None).

    For ``image``: runs an image-only probe (~3s) and fires the full
    probe (image + video) as a background task so video support is
    persisted without blocking the caller.

    For ``video``: runs the full probe and waits for the video result,
    since video support cannot be inferred from the image probe alone.

    Uses the same agent-specific model resolution as
    ``_get_active_model_info`` so that per-agent model overrides are
    respected.

    Returns the probe result (True/False) for the requested media type,
    or None if no probe was needed or the probe failed.
    """
    try:
        from ..prompt import _get_active_model_info
        from ...providers.provider_manager import ProviderManager

        model_info, _ = _get_active_model_info()
        if model_info is None or model_info.supports_multimodal is not None:
            return None

        # Resolve agent-specific active model (mirrors _get_active_model_info)
        manager = ProviderManager.get_instance()
        active = None
        try:
            from ...app.agent_context import get_current_agent_id
            from ...config.config import load_agent_config

            agent_id = get_current_agent_id()
            agent_config = load_agent_config(agent_id)
            if agent_config.active_model:
                active = agent_config.active_model
        except Exception:
            pass
        if not active:
            active = manager.get_active_model()
        if not active:
            return None

        if media_type == "image":
            logger.info(
                "Multimodal capability unknown for %s/%s — "
                "running image-only probe...",
                active.provider_id,
                active.model,
            )
            result = await manager.probe_model_multimodal(
                active.provider_id,
                active.model,
                image_only=True,
            )
            supports = result.get("supports_image", False)
            logger.info(
                "Image probe completed for %s/%s: supports_image=%s",
                active.provider_id,
                active.model,
                supports,
            )
            # Fire full probe in background to persist video support too
            asyncio.create_task(
                manager.probe_model_multimodal(
                    active.provider_id,
                    active.model,
                ),
            )
        else:
            # video: must run full probe to get video result
            logger.info(
                "Multimodal capability unknown for %s/%s — "
                "running full probe for video support...",
                active.provider_id,
                active.model,
            )
            result = await manager.probe_model_multimodal(
                active.provider_id,
                active.model,
            )
            supports = result.get("supports_video", False)
            logger.info(
                "Full probe completed for %s/%s: supports_video=%s",
                active.provider_id,
                active.model,
                supports,
            )
        return supports
    except Exception as e:
        logger.warning("Auto-probe in view_media failed: %s", e)
        return None


def _check_multimodal_support(media_type: str = "image") -> bool:
    """Check whether the active model supports the given media type (sync).

    For ``image``: returns True when supports_image or supports_multimodal
    is explicitly True.
    For ``video``: returns True only when supports_video is explicitly True.

    Returns False for unknown (None) or explicitly unsupported (False).
    The tool is still *registered*; the async probe path handles the
    probe-on-demand logic.
    """
    try:
        from ..prompt import _get_active_model_info

        model_info, _ = _get_active_model_info()
        if model_info is None:
            return True
        if media_type == "video":
            return model_info.supports_video is True
        # image: True if supports_image or the combined supports_multimodal
        return (
            model_info.supports_image is True
            or model_info.supports_multimodal is True
        )
    except Exception:
        return True


def _get_multimodal_fallback_hint(media_type: str, path: str) -> str:
    """Build a text hint for the model when multimodal is not available.

    The actual media block is still included in the response so the
    frontend/user can see it; the hint tells the agent it cannot perceive
    the media itself.
    """
    try:
        from ..prompt import get_active_model_multimodal_raw

        raw = get_active_model_multimodal_raw()
    except Exception:
        raw = None

    if raw is None:
        logger.warning(
            "view_%s was called but multimodal capability has not been "
            "confirmed for the active model. The %s at '%s' will be "
            "shown to the user but the model cannot see it. "
            "To fix, set supports_multimodal=true in provider settings.",
            media_type,
            media_type,
            path,
        )
        return (
            f"[Note: this model does not appear to support multimodal "
            f"input — no multimodal capability was detected. You cannot "
            f"see this {media_type}, but it has been shown to the user. "
            f"Inform the user that you cannot analyze the {media_type} "
            f"content. If they believe this model supports vision, they "
            f"can override this in provider settings by setting "
            f"`supports_multimodal: true`, then retry.]"
        )

    logger.warning(
        "view_%s was called but the active model explicitly does not "
        "support multimodal input. The %s at '%s' will be shown to "
        "the user but the model cannot see it.",
        media_type,
        media_type,
        path,
    )
    return (
        f"[Note: the current model does not support multimodal input — "
        f"you cannot see this {media_type}, but it has been shown to "
        f"the user. Inform the user that you cannot analyze the "
        f"{media_type} content. If they believe this model actually "
        f"supports vision, they can override `supports_multimodal: true` "
        f"in the provider settings, or switch to a vision-capable model.]"
    )


@tool_descriptor(
    requires_sandbox=("file_read", "file_write"),
    async_execution=True,
    tool_type="file",
    target_param="image_path",
    policy_name="ViewImage",
    default_policy="allow",
    policy_reason="Image view (global)",
    ui_description="Load an image into LLM context for visual analysis",
    ui_icon="🖼️",
    display_to_user=False,
)
# pylint: disable-next=too-many-return-statements
async def view_image(image_path: str) -> ToolChunk:
    """Load an image file into the LLM context so the model can see it.

    Use this after desktop_screenshot or any tool that
    produces an image file path.  Also accepts an HTTP(S) URL for
    online images. Remote images are downloaded, validated, and frozen
    before they are added to the model context.

    When the model does not support multimodal, the image is still
    returned (so the user/frontend can see it) along with a text hint
    telling the agent it cannot perceive the image. The downstream
    media-stripping pipeline will remove the ImageBlock before sending
    to the model.

    Args:
        image_path (`str`):
            Local path or HTTP(S) URL of the image to view.

    Returns:
        `ToolChunk`:
            An ImageBlock the model can inspect, or an error message.
    """
    # Determine whether we need a fallback hint
    fallback_hint: str | None = None
    if not _check_multimodal_support("image"):
        probe_result = await _probe_multimodal_if_needed("image")
        if probe_result is not True:
            fallback_hint = _get_multimodal_fallback_hint("image", image_path)

    if _is_url(image_path):
        err = _validate_url_extension(
            image_path,
            _IMAGE_EXTENSIONS,
            "image",
        )
        if err is not None:
            return err

        download_limit = _remote_image_download_max_bytes()
        image_bytes, download_error = await _download_remote_image(
            image_path,
            download_limit,
        )
        if download_error is not None or image_bytes is None:
            return _image_error_chunk(download_error)

        if len(image_bytes) > MAX_INLINE_MEDIA_BYTES:
            media_type, validation_error = await run_sync_io(
                validate_image_bytes,
                image_bytes,
                _remote_image_name(image_path),
            )
            if validation_error is not None or media_type is None:
                return _image_error_chunk(validation_error)
            try:
                local_path = await _stage_remote_image_for_compression(
                    image_bytes,
                    media_type,
                )
            except OSError as exc:
                return _image_error_chunk(
                    f"failed to save oversized remote image: {exc}",
                )
            return _oversized_remote_image_chunk(
                local_path,
                len(image_bytes),
            )

        frozen_image, freeze_error = await run_sync_io(
            freeze_image_bytes,
            image_bytes,
            _remote_image_name(image_path),
        )
        if freeze_error is not None or frozen_image is None:
            return _image_error_chunk(freeze_error)

        text_msg = (
            fallback_hint
            if fallback_hint
            else "Image loaded from remote source."
        )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                frozen_image,
                TextBlock(type="text", text=text_msg),
            ],
        )

    resolved, frozen_image, validation_error, freeze_error = await run_sync_io(
        _load_local_image,
        image_path,
    )
    if validation_error is not None:
        return validation_error
    if freeze_error is not None or frozen_image is None:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=freeze_error or f"Error: failed to load {resolved}",
                ),
            ],
        )

    text_msg = (
        fallback_hint if fallback_hint else f"Image loaded: {resolved.name}"
    )
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            frozen_image,
            TextBlock(type="text", text=text_msg),
        ],
    )


@tool_descriptor(
    requires_sandbox=("file_read",),
    async_execution=True,
    tool_type="file",
    target_param="video_path",
    policy_name="ViewVideo",
    default_policy="allow",
    policy_reason="Video view (global)",
    ui_description="Load a video into LLM context for visual analysis",
    ui_icon="🎥",
    display_to_user=False,
)
async def view_video(video_path: str) -> ToolChunk:
    """Load a video file into the LLM context so the model can see it.

    Use this when the user asks about a video file or when another
    tool produces a video file path. Unlike remote images, an HTTP(S)
    video URL is passed directly to the model without downloading or
    freezing. Durable remote video handling is outside the current scope.

    When the model does not support multimodal, the video is still
    returned (so the user/frontend can see it) along with a text hint
    telling the agent it cannot perceive the video.

    Args:
        video_path (`str`):
            Local path or HTTP(S) URL of the video to view.

    Returns:
        `ToolChunk`:
            A VideoBlock the model can inspect, or an error message.
    """
    fallback_hint: str | None = None
    if not _check_multimodal_support("video"):
        probe_result = await _probe_multimodal_if_needed("video")
        if probe_result is not True:
            fallback_hint = _get_multimodal_fallback_hint("video", video_path)

    if _is_url(video_path):
        err = _validate_url_extension(
            video_path,
            _VIDEO_EXTENSIONS,
            "video",
        )
        if err is not None:
            return err
        text_msg = (
            fallback_hint
            if fallback_hint
            else f"Video loaded from URL: {video_path}"
        )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                _media_data_block(video_path, "video"),
                TextBlock(type="text", text=text_msg),
            ],
        )

    resolved, err = _validate_media_path(
        video_path,
        _VIDEO_EXTENSIONS,
        "video",
    )
    if err is not None:
        return err

    file_url = _path_to_file_url(str(resolved))
    text_msg = (
        fallback_hint if fallback_hint else f"Video loaded: {resolved.name}"
    )
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            _media_data_block(file_url, "video"),
            TextBlock(type="text", text=text_msg),
        ],
    )
