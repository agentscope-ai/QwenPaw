# -*- coding: utf-8 -*-
"""File handling utilities for downloading and managing files.

This module provides utilities for:
- Downloading files from base64 encoded data
- Downloading files from URLs
- Managing download directories
- Reading text files with encoding fallback for cross-platform compatibility
"""
import os
import mimetypes
import base64
import hashlib
import logging
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)


def read_text_file_with_encoding_fallback(file_path: Path | str) -> str:
    """Read text file with multiple encoding attempts for cross-platform
    compatibility.

    This function handles files created with different text editors on
    different platforms, especially addressing the common issue where Windows
    Notepad saves files in GBK encoding while most editors use UTF-8.

    Tries common encodings in order:
    1. UTF-8 with BOM (Windows Notepad with "UTF-8" option) - tried first
       to handle BOM correctly
    2. UTF-8 (default, most common on macOS/Linux)
    3. GBK/CP936 (Windows Notepad default for Chinese)
    4. CP1252/Latin-1 (Windows Notepad default for Western languages)
    5. UTF-8 with errors='replace' as final fallback

    Args:
        file_path: Path to the file to read (Path object or string)

    Returns:
        File content as string (with original whitespace preserved)

    Raises:
        FileNotFoundError: If file doesn't exist
        IOError: If file cannot be read even with fallback encodings
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    encodings_to_try = [
        "utf-8-sig",  # UTF-8 with BOM - try first
        "utf-8",
        "gbk",  # Windows Chinese default
        "cp936",  # Alias for GBK
        "cp1252",  # Windows Western default
        "latin-1",  # Fallback for Western text
    ]

    for encoding in encodings_to_try:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read()
                if encoding not in ("utf-8", "utf-8-sig"):
                    logger.debug(
                        "File %s read with encoding: %s",
                        file_path.name,
                        encoding,
                    )
                return content
        except (UnicodeDecodeError, LookupError):
            continue

    # Final fallback: UTF-8 with error replacement
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            logger.warning(
                "File %s read with UTF-8 errors='replace' fallback, "
                "some characters may be corrupted",
                file_path.name,
            )
            return content
    except Exception as e:
        logger.error(
            "File %s cannot be read even with fallback: %s",
            file_path.name,
            e,
        )
        raise IOError(
            f"File {file_path.name} cannot be read even with fallback: {e}",
        ) from e


def _default_download_dir() -> str:
    """Return the default download directory under the current workspace."""
    base_dir = get_current_workspace_dir() or WORKING_DIR
    return str(base_dir / "downloads")


def _resolve_local_path(
    url: str,
    parsed: urllib.parse.ParseResult,
) -> Optional[str]:
    """Return local file path for file:// or plain path; None for remote."""
    if parsed.scheme == "file":
        local_path = Path(urllib.request.url2pathname(parsed.path))
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        if local_path.is_file() and local_path.stat().st_size == 0:
            raise ValueError(f"Local file is empty: {local_path}")
        return str(local_path.resolve())
    if parsed.scheme == "" and parsed.netloc == "":
        p = Path(url).expanduser()
        if p.exists():
            if p.is_file() and p.stat().st_size == 0:
                raise ValueError(f"Local file is empty: {p}")
            return str(p.resolve())
    # Windows absolute path: urlparse("C:\\path") -> scheme="c", path="\\path"
    if (
        os.name == "nt"
        and len(parsed.scheme) == 1
        and parsed.scheme.isalpha()
        and (parsed.path.startswith("\\") or parsed.path.startswith("/"))
    ):
        p = Path(url.strip()).resolve()
        if p.exists() and p.is_file():
            if p.stat().st_size == 0:
                raise ValueError(f"Local file is empty: {p}")
            return str(p)
    return None


def _download_remote_to_path(url: str, local_file_path: Path) -> None:
    """
    Download url to local_file_path via wget, curl, or urllib. Raises on fail.
    """
    try:
        subprocess.run(
            ["wget", "-q", "-O", str(local_file_path), url],
            capture_output=True,
            timeout=60,
            check=True,
        )
        logger.debug("Downloaded file via wget to: %s", local_file_path)
        return
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.debug("wget failed, trying curl: %s", e)
    try:
        subprocess.run(
            ["curl", "-s", "-L", "-o", str(local_file_path), url],
            capture_output=True,
            timeout=60,
            check=True,
        )
        logger.debug("Downloaded file via curl to: %s", local_file_path)
        return
    except (subprocess.CalledProcessError, FileNotFoundError) as curl_err:
        logger.debug("curl failed, trying urllib: %s", curl_err)
    try:
        urllib.request.urlretrieve(url, str(local_file_path))
        logger.debug("Downloaded file via urllib to: %s", local_file_path)
    except Exception as urllib_err:
        logger.error(
            "wget, curl and urllib all failed for URL %s: %s",
            url,
            urllib_err,
        )
        raise RuntimeError(
            "Failed to download file: wget, curl and urllib all failed",
        ) from urllib_err


def _guess_suffix_from_url_headers(url: str) -> Optional[str]:
    """
    HEAD request to get Content-Type and return a suffix like '.pdf'.
    Used to fix DingTalk download URLs that always return .file extension.
    Returns None on any failure (e.g. OSS forbids HEAD or returns no type).
    """
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = (
                (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            )
            if not raw:
                return None
            suffix = mimetypes.guess_extension(raw)
            return suffix if suffix else None
    except Exception:
        return None


# Magic bytes (prefix) -> suffix for .file fallback when HEAD fails (e.g. OSS).
_MAGIC_SUFFIX: list[tuple[bytes, str]] = [
    (b"%PDF", ".pdf"),
    (b"PK\x03\x04", ".zip"),
    (b"PK\x05\x06", ".zip"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"\xd0\xcf\x11\xe0", ".doc"),  # MS Office (doc, xls, ppt)
    (b"RIFF", ".webp"),  # or .wav; webp has RIFF....WEBP
]


def _guess_suffix_from_file_content(path: Path) -> Optional[str]:
    """
    Guess file extension from magic bytes. Used when URL HEAD fails (e.g. OSS).
    Returns suffix like '.pdf' or None.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(32)
        for magic, suffix in _MAGIC_SUFFIX:
            if head.startswith(magic):
                return suffix
        return None
    except Exception:
        return None


async def download_file_from_base64(
    base64_data: str,
    filename: Optional[str] = None,
    download_dir: str = "",
) -> str:
    """
    Save base64-encoded file data to local download directory.

    Args:
        base64_data: Base64-encoded file content.
        filename: The filename to save. If not provided, will generate one.
        download_dir: The directory to save files. Defaults to
            workspace_dir/downloads.

    Returns:
        The local file path.
    """
    try:
        file_content = base64.b64decode(base64_data)

        download_path = Path(
            download_dir if download_dir else _default_download_dir(),
        )
        download_path.mkdir(parents=True, exist_ok=True)

        if not filename:
            file_hash = hashlib.md5(file_content).hexdigest()
            filename = f"file_{file_hash}"

        local_file_path = download_path / filename
        with open(local_file_path, "wb") as f:
            f.write(file_content)

        logger.debug("Downloaded file to: %s", local_file_path)
        return str(local_file_path.absolute())

    except Exception as e:
        logger.error("Failed to download file from base64: %s", e)
        raise


async def download_file_from_url(
    url: str,
    filename: Optional[str] = None,
    download_dir: str = "",
) -> str:
    """
    Download a file from URL to local download directory using wget or curl.

    Args:
        url (`str`):
            The URL of the file to download.
        filename (`str`, optional):
            The filename to save. If not provided, will extract from URL or
            generate a hash-based name.
        download_dir (`str`):
            The directory to save files. Defaults to
            workspace_dir/downloads.

    Returns:
        `str`:
            The local file path.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        local = _resolve_local_path(url, parsed)
        if local is not None:
            return local

        download_path = Path(
            download_dir if download_dir else _default_download_dir(),
        )
        download_path.mkdir(parents=True, exist_ok=True)
        if not filename:
            url_filename = os.path.basename(parsed.path)
            filename = (
                url_filename
                if url_filename
                else f"file_{hashlib.md5(url.encode()).hexdigest()}"
            )
        local_file_path = download_path / filename
        _download_remote_to_path(url, local_file_path)
        if not local_file_path.exists():
            raise FileNotFoundError("Downloaded file does not exist")
        if local_file_path.stat().st_size == 0:
            raise ValueError("Downloaded file is empty")
        # DingTalk (and similar) return URLs that save as .file; replace with
        # real extension. Try HEAD first; if that fails (e.g. OSS), use magic.
        if local_file_path.suffix == ".file":
            real_suffix = _guess_suffix_from_url_headers(url)
            if not real_suffix:
                real_suffix = _guess_suffix_from_file_content(local_file_path)
            if real_suffix:
                new_path = local_file_path.with_suffix(real_suffix)
                local_file_path.rename(new_path)
                local_file_path = new_path
                logger.debug(
                    "Replaced .file with %s for %s",
                    real_suffix,
                    local_file_path,
                )
        return str(local_file_path.absolute())
    except subprocess.TimeoutExpired as e:
        logger.error("Download timeout for URL: %s", url)
        raise TimeoutError(f"Download timeout for URL: {url}") from e
    except Exception as e:
        logger.error("Failed to download file from URL %s: %s", url, e)
        raise
