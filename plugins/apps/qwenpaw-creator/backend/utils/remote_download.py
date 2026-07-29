# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Download remote files through the shared SSRF-safe transport.

All Creator remote media downloads share one DNS/peer/redirect/size policy in
``services.runtime_files.safe_remote_download``; this module only adds the
durable temp-file + atomic-rename boundary and env-tunable limits.
"""

import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.runtime_files.safe_remote_download import (
    SafeRemoteDownloadError,
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


def download_remote_file(url: str, local_path: str) -> None:
    """Download a remote file to a local path. Raises RuntimeError on failure."""
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
            )
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
