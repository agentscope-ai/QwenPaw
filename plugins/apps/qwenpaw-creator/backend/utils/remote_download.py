# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Download remote files through the shared SSRF-safe transport.

All Creator remote media downloads share one DNS/peer/redirect/size policy in
``services.runtime_files.safe_remote_download``; this module only adds the
durable temp-file + atomic-rename boundary and env-tunable limits.
"""

from collections.abc import Callable
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.runtime_files.safe_remote_download import (
    SafeRemoteDownloadError,
    safe_curl_download_to_file,
    safe_download_to_file,
)

logger = __import__("utils.logger", fromlist=["setup_logger"]).setup_logger(
    "utils.remote_download",
)

# Limits/timeouts are overridable via environment variables. The default is
# 2 GiB, enough to download a full match recording; the previous hard-coded
# 500 MiB blocked ~1 GiB highlight footage, so editing never got a local
# file and failed.
MAX_BYTES = int(
    os.environ.get("CREATOR_DOWNLOAD_MAX_BYTES", 2 * 1024 * 1024 * 1024),
)
TIMEOUT_SECONDS = int(os.environ.get("CREATOR_DOWNLOAD_TIMEOUT_SECONDS", 300))
CONNECT_TIMEOUT_SECONDS = int(
    os.environ.get("CREATOR_DOWNLOAD_CONNECT_TIMEOUT_SECONDS", 15),
)


def _fsync_directory(directory: Path) -> None:
    """Best-effort direntry durability; Windows cannot open directories."""

    if os.name == "nt":
        return
    try:
        directory_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def download_remote_file(
    url: str,
    local_path: str,
    *,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> None:
    """Download a remote file to a local path. Raises RuntimeError on failure.

    ``on_progress`` forwards the httpx transport's per-chunk progress; the curl
    fallback path reports a single terminal sample once the file lands.
    """
    target = Path(local_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".download",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    parsed = urlsplit(url)
    redacted_url = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", ""),
    )
    logger.info(
        "Downloading remote file | url=%s max_bytes=%d timeout=%ds",
        redacted_url[:100],
        MAX_BYTES,
        TIMEOUT_SECONDS,
    )
    try:
        try:
            size_bytes, _media_type, _final_url = safe_download_to_file(
                url,
                temporary,
                max_bytes=MAX_BYTES,
                timeout=httpx.Timeout(
                    TIMEOUT_SECONDS,
                    connect=CONNECT_TIMEOUT_SECONDS,
                ),
                on_progress=on_progress,
            )
        except (httpx.TransportError, OSError) as error:
            # Some local/network stacks cannot establish the OSS route
            # through httpx even though the system curl can (observed as
            # ConnectError / EBADF on short-lived DashScope result URLs).
            # Retry through the bounded, SSRF-validated curl transport;
            # HTTP status failures stay authoritative and are not retried.
            logger.warning(
                "httpx download failed (%s: %s); retrying with bounded curl",
                type(error).__name__,
                str(error)[:200],
            )
            try:
                (
                    size_bytes,
                    _media_type,
                    _final_url,
                ) = safe_curl_download_to_file(
                    url,
                    temporary,
                    max_bytes=MAX_BYTES,
                    timeout_seconds=TIMEOUT_SECONDS,
                    connect_timeout_seconds=CONNECT_TIMEOUT_SECONDS,
                )
                if on_progress is not None:
                    on_progress(size_bytes, size_bytes)
            except SafeRemoteDownloadError as curl_error:
                # curl_error.__context__ keeps the original httpx failure;
                # the message carries both for log-only consumers.
                raise RuntimeError(
                    "Remote file download failed: "
                    f"{type(error).__name__}: {str(error)[:200]}; "
                    f"curl fallback: {str(curl_error)[:200]}",
                ) from curl_error
        except SafeRemoteDownloadError as error:
            hint = ""
            if "bytes 限制" in str(error):
                hint = (
                    f" (文件超过下载上限 {MAX_BYTES / 1024 / 1024:.0f} MiB；"
                    f"可调大环境变量 CREATOR_DOWNLOAD_MAX_BYTES)"
                )
            raise RuntimeError(
                f"Remote file download failed: {str(error)[:300]}{hint}",
            ) from error
        except httpx.HTTPError as error:
            raise RuntimeError(
                f"Remote file download failed: {str(error)[:300]}",
            ) from error

        if size_bytes <= 0:
            raise RuntimeError("Remote file downloaded empty")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
        size_mib = target.stat().st_size / 1024 / 1024
        logger.info(
            f"Downloaded remote file | path={target}, size_mib={size_mib:.1f}",
        )
    finally:
        temporary.unlink(missing_ok=True)
