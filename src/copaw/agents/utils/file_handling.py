# -*- coding: utf-8 -*-
"""File handling utilities for downloading and managing files.

This module provides utilities for:
- Downloading files from base64 encoded data
- Downloading files from URLs
- Managing download directories
- Image compression for large files
"""
import io
import os
import mimetypes
import base64
import hashlib
import logging
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)

# Default downloads directory under WORKING_DIR
_DEFAULT_DOWNLOADS_DIR = str(WORKING_DIR / "downloads")
# Media directory for storing images separately from session files
_DEFAULT_MEDIA_DIR = WORKING_DIR / "media"
# Maximum image size before compression (7MB)
_MAX_IMAGE_SIZE_BYTES = 7 * 1024 * 1024


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
        return _guess_suffix_from_file_content_bytes(head)
    except Exception:
        return None


def _guess_suffix_from_file_content_bytes(data: bytes) -> Optional[str]:
    """
    Guess file extension from magic bytes in raw data.
    Returns suffix like '.png' or None.
    """
    try:
        head = data[:32] if len(data) >= 32 else data
        for magic, suffix in _MAGIC_SUFFIX:
            if head.startswith(magic):
                return suffix
        return None
    except Exception:
        return None


async def download_file_from_base64(
    base64_data: str,
    filename: Optional[str] = None,
    download_dir: str = _DEFAULT_DOWNLOADS_DIR,
    media_type: Optional[str] = None,
) -> str:
    """
    Save base64-encoded file data to local download directory.

    Args:
        base64_data: Base64-encoded file content.
        filename: The filename to save. If not provided, will generate one.
        download_dir: The directory to save files. Defaults to "downloads".
        media_type: Optional MIME type (e.g., "image/png") to determine
            extension.

    Returns:
        The local file path.
    """
    try:
        file_content = base64.b64decode(base64_data)

        download_path = Path(download_dir)
        download_path.mkdir(parents=True, exist_ok=True)

        if not filename:
            file_hash = hashlib.md5(file_content).hexdigest()[:12]
            # Try to get extension from media_type
            ext = ""
            if media_type:
                ext = mimetypes.guess_extension(media_type) or ""
            # Fallback to magic bytes detection
            if not ext:
                ext = (
                    _guess_suffix_from_file_content_bytes(file_content)
                    or ".bin"
                )
            filename = f"file_{file_hash}{ext}"

        local_file_path = download_path / filename
        with open(local_file_path, "wb") as f:
            f.write(file_content)

        logger.debug("Downloaded file to: %s", local_file_path)
        return str(local_file_path.absolute())

    except Exception as e:
        logger.error("Failed to download file from base64: %s", e)
        raise


def _save_data_url_to_file(
    url: str,
    filename: Optional[str],
    download_dir: str,
) -> str:
    """
    Parse and save a data: URL to file.

    Args:
        url: data: URL (e.g., "data:image/png;base64,...")
        filename: Optional filename to save as.
        download_dir: Directory to save file.

    Returns:
        Local file path.
    """
    # Parse data URL: data:[<mediatype>][;base64],<data>
    header, encoded_data = url.split(",", 1)
    # Extract media type and check if base64
    parts = header[5:].split(";")  # Remove "data:" prefix
    media_type = parts[0] if parts else ""
    is_base64 = "base64" in parts

    if not is_base64:
        raise ValueError("Only base64-encoded data URLs are supported")

    # Decode base64 data
    file_content = base64.b64decode(encoded_data)

    # Generate filename if not provided
    if not filename:
        ext = mimetypes.guess_extension(media_type) or ".bin"
        file_hash = hashlib.md5(file_content).hexdigest()[:12]
        filename = f"file_{file_hash}{ext}"

    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)
    local_file_path = download_path / filename

    with open(local_file_path, "wb") as f:
        f.write(file_content)

    logger.debug("Saved data URL to: %s", local_file_path)
    return str(local_file_path.absolute())


def _fix_file_extension(local_file_path: Path, url: str) -> Path:
    """
    Fix .file extension by detecting real file type.

    DingTalk and similar services return URLs that save as .file;
    this replaces with the real extension.
    """
    if local_file_path.suffix != ".file":
        return local_file_path

    real_suffix = _guess_suffix_from_url_headers(url)
    if not real_suffix:
        real_suffix = _guess_suffix_from_file_content(local_file_path)

    if real_suffix:
        new_path = local_file_path.with_suffix(real_suffix)
        local_file_path.rename(new_path)
        logger.debug("Replaced .file with %s for %s", real_suffix, new_path)
        return new_path

    return local_file_path


async def download_file_from_url(
    url: str,
    filename: Optional[str] = None,
    download_dir: str = _DEFAULT_DOWNLOADS_DIR,
) -> str:
    """
    Download a file from URL to local download directory using wget or curl.
    Also handles data: URLs (base64-encoded content).

    Args:
        url (`str`):
            The URL of the file to download. Can be:
            - http:// or https:// URLs
            - file:// URLs
            - data: URLs (base64-encoded, e.g., "data:image/png;base64,...")
        filename (`str`, optional):
            The filename to save. If not provided, will extract from URL or
            generate a hash-based name.
        download_dir (`str`):
            The directory to save files. Defaults to "downloads".

    Returns:
        `str`:
            The local file path.
    """
    try:
        # Handle data: URLs (base64-encoded content)
        if url.startswith("data:"):
            try:
                return _save_data_url_to_file(url, filename, download_dir)
            except Exception as e:
                logger.error("Failed to parse data URL: %s", e)
                raise

        parsed = urllib.parse.urlparse(url)
        local = _resolve_local_path(url, parsed)
        if local is not None:
            return local

        download_path = Path(download_dir)
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

        # Fix .file extension if needed
        local_file_path = _fix_file_extension(local_file_path, url)

        return str(local_file_path.absolute())
    except subprocess.TimeoutExpired as e:
        logger.error("Download timeout for URL: %s", url)
        raise TimeoutError(f"Download timeout for URL: {url}") from e
    except Exception as e:
        logger.error("Failed to download file from URL %s: %s", url, e)
        raise


def _compress_image(
    image_data: bytes,
    media_type: Optional[str] = None,
    max_size: int = _MAX_IMAGE_SIZE_BYTES,
    initial_quality: int = 85,
) -> Tuple[bytes, str]:
    """
    Compress an image if it exceeds the maximum size.

    Args:
        image_data: Raw image bytes.
        media_type: Original MIME type.
        max_size: Maximum allowed size in bytes.
        initial_quality: Starting JPEG quality (will be reduced if needed).

    Returns:
        Tuple of (compressed_bytes, new_media_type).
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed, skipping image compression")
        return image_data, media_type or "image/jpeg"

    if len(image_data) <= max_size:
        return image_data, media_type or "image/jpeg"

    logger.info(
        "Image size %.2f MB exceeds limit %.2f MB, compressing...",
        len(image_data) / (1024 * 1024),
        max_size / (1024 * 1024),
    )

    try:
        img = Image.open(io.BytesIO(image_data))

        # Convert to RGB if necessary (for JPEG output)
        if img.mode in ("RGBA", "P"):
            # Create white background for transparent images
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(
                img,
                mask=img.split()[-1] if img.mode == "RGBA" else None,
            )
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # First try: resize if very large dimensions
        max_dimension = 4096
        if img.width > max_dimension or img.height > max_dimension:
            ratio = min(max_dimension / img.width, max_dimension / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logger.debug("Resized image to %s", new_size)

        # Compress with decreasing quality until under max_size
        quality = initial_quality
        while quality >= 20:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            compressed_data = buffer.getvalue()

            if len(compressed_data) <= max_size:
                logger.info(
                    "Compressed image from %.2f MB to %.2f MB (quality=%d)",
                    len(image_data) / (1024 * 1024),
                    len(compressed_data) / (1024 * 1024),
                    quality,
                )
                return compressed_data, "image/jpeg"

            quality -= 10

        # If still too large, resize further
        scale = 0.8
        while scale >= 0.3:
            new_size = (int(img.width * scale), int(img.height * scale))
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=60, optimize=True)
            compressed_data = buffer.getvalue()

            if len(compressed_data) <= max_size:
                logger.info(
                    "Compressed image from %.2f MB to %.2f MB (scale=%.1f)",
                    len(image_data) / (1024 * 1024),
                    len(compressed_data) / (1024 * 1024),
                    scale,
                )
                return compressed_data, "image/jpeg"

            scale -= 0.1

        # Return best effort
        logger.warning(
            "Could not compress image below %.2f MB, using %.2f MB",
            max_size / (1024 * 1024),
            len(compressed_data) / (1024 * 1024),
        )
        return compressed_data, "image/jpeg"

    except Exception as e:
        logger.error("Failed to compress image: %s", e)
        return image_data, media_type or "image/jpeg"


def compress_base64_image(
    base64_data: str,
    media_type: Optional[str] = None,
    max_size: int = _MAX_IMAGE_SIZE_BYTES,
) -> Tuple[str, Optional[str]]:
    """
    Compress a base64-encoded image if it exceeds the maximum size.

    This function is used to ensure images sent to LLM APIs don't exceed
    their size limits (e.g., OpenAI's 10MB per data-uri limit).

    Args:
        base64_data: Base64-encoded image content (without data: prefix).
        media_type: Optional MIME type (e.g., "image/png").
        max_size: Maximum allowed size in bytes (default 7MB).

    Returns:
        Tuple of (compressed_base64, new_media_type if compressed else None).
        If no compression needed, returns (original_base64, None).
    """
    try:
        # Decode base64 to bytes
        image_data = base64.b64decode(base64_data)

        # Check if compression is needed
        if len(image_data) <= max_size:
            return base64_data, None

        # Compress the image
        compressed_data, new_media_type = _compress_image(
            image_data,
            media_type,
            max_size,
        )

        # If compression happened, re-encode to base64
        if len(compressed_data) < len(image_data):
            compressed_base64 = base64.b64encode(compressed_data).decode(
                "utf-8",
            )
            return compressed_base64, new_media_type

        return base64_data, None

    except Exception as e:
        logger.error("Failed to compress base64 image: %s", e)
        return base64_data, None


def save_base64_to_media(
    base64_data: str,
    media_type: Optional[str] = None,
    media_dir: Optional[Path] = None,
    compress_if_large: bool = True,
) -> Tuple[str, Optional[str]]:
    """
    Save base64-encoded image data to media directory.

    This function saves images to a dedicated media directory to keep
    session files small. Large images (>7MB) are automatically compressed.
    Returns a file:// URL for storage in session.

    Args:
        base64_data: Base64-encoded image content (without data: prefix).
        media_type: Optional MIME type (e.g., "image/png") to determine
            extension.
        media_dir: Optional custom media directory. Defaults to
            WORKING_DIR/media.
        compress_if_large: Whether to compress images exceeding 7MB.

    Returns:
        Tuple of (file:// URL, new_media_type if compressed else None).
    """
    try:
        file_content = base64.b64decode(base64_data)
        new_media_type = None

        # Compress if image is too large
        if compress_if_large and len(file_content) > _MAX_IMAGE_SIZE_BYTES:
            file_content, new_media_type = _compress_image(
                file_content,
                media_type,
            )

        save_dir = media_dir or _DEFAULT_MEDIA_DIR
        save_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename based on content hash
        file_hash = hashlib.md5(file_content).hexdigest()[:12]

        # Determine extension from media_type or magic bytes
        ext = ""
        final_media_type = new_media_type or media_type
        if final_media_type:
            ext = mimetypes.guess_extension(final_media_type) or ""
        if not ext:
            ext = _guess_suffix_from_file_content_bytes(file_content) or ".bin"

        filename = f"img_{file_hash}{ext}"
        local_file_path = save_dir / filename

        # Only write if file doesn't exist (content-addressable storage)
        if not local_file_path.exists():
            with open(local_file_path, "wb") as f:
                f.write(file_content)
            logger.debug("Saved image to media: %s", local_file_path)
        else:
            logger.debug("Image already exists in media: %s", local_file_path)

        return local_file_path.as_uri(), new_media_type

    except Exception as e:
        logger.error("Failed to save base64 to media: %s", e)
        raise


def load_media_as_base64(file_path: str) -> Optional[str]:
    """
    Load an image file and convert to base64 data URL.

    This function reads an image file from the media directory and
    converts it to a data URL for frontend display.

    Args:
        file_path: Local file path or file:// URL.

    Returns:
        Base64 data URL (e.g., "data:image/png;base64,...") or None on error.
    """
    try:
        # Handle file:// URL
        if file_path.startswith("file://"):
            parsed = urllib.parse.urlparse(file_path)
            file_path = urllib.request.url2pathname(parsed.path)

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            logger.warning("Media file not found: %s", file_path)
            return None

        # Read file content
        with open(path, "rb") as f:
            file_content = f.read()

        # Determine media type from extension
        media_type = (
            mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        )

        # Encode to base64
        base64_data = base64.b64encode(file_content).decode("utf-8")

        return f"data:{media_type};base64,{base64_data}"

    except Exception as e:
        logger.error("Failed to load media as base64: %s", e)
        return None


def is_media_file_url(url: str) -> bool:
    """
    Check if a URL points to a file in the media directory.

    Args:
        url: URL to check (file:// URL or local path).

    Returns:
        True if the URL points to a file in the media directory.
    """
    try:
        if url.startswith("file://"):
            parsed = urllib.parse.urlparse(url)
            file_path = urllib.request.url2pathname(parsed.path)
        else:
            file_path = url

        resolved = Path(file_path).expanduser().resolve()
        media_root = _DEFAULT_MEDIA_DIR.resolve()
        return str(resolved).startswith(str(media_root))
    except Exception:
        return False
