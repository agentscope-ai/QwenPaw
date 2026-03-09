# -*- coding: utf-8 -*-
"""Read media file (image, video, audio) and return appropriate Block.

Supports:
- Local file paths (any location accessible by the system)
- file:// URLs
- http(s):// URLs

Media Types:
- Images: PNG, JPG, GIF, WEBP, BMP
- Videos: MP4, AVI, MOV, MKV, WEBM, FLV, WMV
- Audio: MP3, WAV, AAC, OGG, M4A, FLAC, WMA

Features:
- Image compression (using Pillow)
- Video compression with frame extraction (using FFmpeg)
- Automatic media type detection and appropriate Block return

Security:
- Maximum file size: 20MB (before compression)
- File content validation via magic numbers
"""
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-return-statements,too-many-branches
import base64
import os
import tempfile
import asyncio
from pathlib import Path
from typing import Optional

import httpx

from agentscope.message import TextBlock, ImageBlock, AudioBlock, VideoBlock
from agentscope.tool import ToolResponse


# Supported media formats and their MIME types
SUPPORTED_FORMATS = {
    # Images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    # Videos
    ".mp4": "video/mp4",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
    # Audio
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".wma": "audio/x-ms-wma",
}

# File extension categories
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".ogg", ".m4a", ".flac", ".wma"}

# Image format magic numbers (file signatures) for validation
# Each entry: (offset, signature bytes)
IMAGE_MAGIC_SIGNATURES = {
    ".png": (0, b"\x89PNG\r\n\x1a\n"),
    ".jpg": (0, b"\xff\xd8\xff"),
    ".jpeg": (0, b"\xff\xd8\xff"),
    ".gif": (0, b"GIF87a"),  # Also matches GIF89a (first 6 bytes same)
    ".webp": (8, b"WEBP"),  # RIFF header at 0, WEBP at offset 8
    ".bmp": (0, b"BM"),
}

# Video format magic numbers
VIDEO_MAGIC_SIGNATURES = {
    ".mp4": (4, b"ftyp"),  # ftyp box at offset 4
    ".avi": (0, b"RIFF"),  # RIFF header
    ".mov": (4, b"ftyp"),  # QuickTime uses ftyp
    ".mkv": (0, b"\x1a\x45\xdf\xa3"),  # EBML header
    ".webm": (0, b"\x1a\x45\xdf\xa3"),  # Same as MKV
    ".flv": (0, b"FLV"),
    ".wmv": (0, b"\x30\x26\xb2\x75"),  # ASF header
}

# Audio format magic numbers
AUDIO_MAGIC_SIGNATURES = {
    ".mp3": (0, b"\xff\xfb"),  # MPEG-1 Layer 3
    ".wav": (0, b"RIFF"),  # RIFF/WAVE
    ".aac": (0, b"\xff\xf1"),  # ADTS
    ".ogg": (0, b"OggS"),
    ".m4a": (4, b"ftyp"),  # Same as MP4
    ".flac": (0, b"fLaC"),
    ".wma": (0, b"\x30\x26\xb2\x75"),  # Same as WMV (ASF)
}

# Maximum file size: 20MB
MAX_FILE_SIZE = 20 * 1024 * 1024


def _get_media_type(file_path: str) -> Optional[str]:
    """Get MIME type from file extension.

    Args:
        file_path: Path to the file.

    Returns:
        MIME type string or None if unsupported.
    """
    ext = Path(file_path).suffix.lower()
    return SUPPORTED_FORMATS.get(ext)


def _check_special_format(ext: str, header: bytes) -> bool:
    """Check special format signatures for files with multiple variants.

    Args:
        ext: File extension.
        header: File header bytes.

    Returns:
        True if format is valid, False otherwise.
    """
    if ext == ".gif":
        return header[0:6] in (b"GIF87a", b"GIF89a")
    if ext == ".webp":
        return header[0:4] == b"RIFF" and header[8:12] == b"WEBP"
    if ext in (".mp4", ".mov", ".m4a"):
        return b"ftyp" in header[4:12]
    if ext == ".wav":
        return header[0:4] == b"RIFF" and b"WAVE" in header
    if ext == ".avi":
        return header[0:4] == b"RIFF" and b"AVI " in header
    return False


def _validate_media_magic(file_path: str) -> tuple[bool, str]:
    """Validate that file content matches expected format.

    Args:
        file_path: Path to the file.

    Returns:
        Tuple of (is_valid, error_message).
    """
    ext = Path(file_path).suffix.lower()

    # Get appropriate magic signatures based on extension
    if ext in IMAGE_EXTENSIONS:
        signatures = IMAGE_MAGIC_SIGNATURES
    elif ext in VIDEO_EXTENSIONS:
        signatures = VIDEO_MAGIC_SIGNATURES
    elif ext in AUDIO_EXTENSIONS:
        signatures = AUDIO_MAGIC_SIGNATURES
    else:
        return (False, f"Unsupported media format: {ext}")

    if ext not in signatures:
        # No magic signature validation for this format
        return (True, "")

    offset, signature = signatures[ext]

    try:
        with open(file_path, "rb") as f:
            # Read enough bytes to check signature
            header = f.read(offset + len(signature) + 16)

        if len(header) < offset + len(signature):
            return (False, "File too small to validate format")

        # Check signature at expected offset
        actual_signature = header[offset : offset + len(signature)]

        # Special handling for formats with multiple variants
        if _check_special_format(ext, header):
            return (True, "")

        if actual_signature == signature:
            return (True, "")

        return (
            False,
            f"File format mismatch: file extension is {ext}, but content is not valid {ext} format",
        )

    except Exception as e:
        return (False, f"File validation failed: {e}")


def _parse_source(source: str) -> tuple[str, Optional[str], str]:
    """Parse media source into type and path/URL.

    Args:
        source: Media source (local path, file:// URL, or http(s):// URL).

    Returns:
        Tuple of (source_type, parsed_path_or_url, error_message).
        source_type is "local", "file_url", "http_url", or "unknown".
    """
    source = source.strip()

    # HTTP(S) URL
    if source.startswith(("http://", "https://")):
        return ("http_url", source, "")

    # file:// URL
    if source.startswith("file://"):
        # Remove file:// prefix and decode URL encoding
        path = source[7:]
        # Handle URL-encoded characters
        from urllib.parse import unquote

        path = unquote(path)
        return ("file_url", path, "")

    # Local path (check if it looks like a path)
    return ("local", source, "")


async def _fetch_http_media(url: str) -> tuple[bytes, str, str]:
    """Fetch media from HTTP URL.

    Args:
        url: HTTP(S) URL to fetch.

    Returns:
        Tuple of (media_data, media_type, error_message).
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get("content-type", "")

            # Check size
            content_length = len(response.content)
            if content_length > MAX_FILE_SIZE:
                size_mb = content_length / (1024 * 1024)
                return (
                    b"",
                    "",
                    f"File too large: {size_mb:.2f}MB, maximum allowed is 20MB",
                )

            # Determine media type from content-type header
            media_type = content_type.split(";")[0].strip()

            return (response.content, media_type, "")

    except httpx.TimeoutException:
        return (b"", "", f"Request timeout: {url}")
    except httpx.HTTPStatusError as e:
        return (b"", "", f"HTTP error: {e.response.status_code}")
    except Exception as e:
        return (b"", "", f"Request failed: {e}")


def _compress_image(
    input_path: str,
    output_path: str,
    target_size_mb: float,
) -> bool:
    """Compress image to target size using Pillow.

    Args:
        input_path: Path to input image.
        output_path: Path to save compressed image.
        target_size_mb: Target file size in MB.

    Returns:
        True if compression succeeded and file is within target size.
    """
    try:
        from PIL import Image
    except ImportError:
        return False

    target_bytes = target_size_mb * 1024 * 1024
    quality = 95

    try:
        with Image.open(input_path) as img:
            # Convert to RGB if necessary (handle RGBA, P, LA modes)
            if img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if img.mode in ("RGBA", "LA"):
                    background.paste(
                        img,
                        mask=img.split()[-1]
                        if img.mode in ("RGBA", "LA")
                        else None,
                    )
                    img = background
                else:
                    img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Try reducing quality first
            while quality >= 20:
                img.save(output_path, "JPEG", optimize=True, quality=quality)
                if os.path.getsize(output_path) <= target_bytes:
                    return True
                quality -= 5

            # If quality reduction isn't enough, also resize
            if os.path.getsize(output_path) > target_bytes:
                ratio = 0.8
                while ratio > 0.3:
                    new_size = (
                        int(img.width * ratio),
                        int(img.height * ratio),
                    )
                    resized = img.resize(new_size, Image.Resampling.LANCZOS)
                    resized.save(
                        output_path,
                        "JPEG",
                        optimize=True,
                        quality=75,
                    )
                    if os.path.getsize(output_path) <= target_bytes:
                        return True
                    ratio -= 0.1

        return os.path.getsize(output_path) <= target_bytes
    except Exception:
        return False


async def _compress_video(
    input_path: str,
    output_path: str,
    target_size_mb: float,
    fps: int = 1,
) -> bool:
    """Compress video using FFmpeg with optional frame extraction.

    Args:
        input_path: Path to input video.
        output_path: Path to save compressed video.
        target_size_mb: Target file size in MB.
        fps: Frames per second to extract (1 = 1 frame per second).
             Use 0 to keep original frame rate.

    Returns:
        True if compression succeeded.
    """
    # Calculate CRF based on target size (higher = more compression)
    # 5MB -> CRF 28, 10MB -> CRF 26, etc.
    crf = max(18, min(28, int(28 - (target_size_mb - 5) / 5 * 2)))

    # Build FFmpeg command
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i",
        input_path,
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        "slow",  # Better compression ratio
        "-c:a",
        "aac",  # Audio codec
        "-b:a",
        "64k",  # Low audio bitrate
        "-movflags",
        "+faststart",
    ]

    # Add frame rate filter if specified
    if fps > 0:
        cmd.extend(["-vf", f"fps={fps}"])
        cmd.extend(["-r", str(fps)])  # Output frame rate

    cmd.append(output_path)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, _ = await process.communicate()

        if process.returncode != 0:
            return False

        # Check if output file exists and is smaller
        if not os.path.exists(output_path):
            return False

        return True
    except Exception:
        return False


def _get_file_category(file_path: str) -> str:
    """Get the category of file (image, video, audio).

    Args:
        file_path: Path to the file.

    Returns:
        Category string: "image", "video", "audio", or "unknown".
    """
    ext = Path(file_path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    elif ext in VIDEO_EXTENSIONS:
        return "video"
    elif ext in AUDIO_EXTENSIONS:
        return "audio"
    return "unknown"


def _create_media_block(
    category: str,
    media_type: str,
    base64_data: str,
) -> ImageBlock | VideoBlock | AudioBlock:
    """Create appropriate media block based on category.

    Args:
        category: File category ("image", "video", "audio").
        media_type: MIME type of the media.
        base64_data: Base64-encoded media data.

    Returns:
        ImageBlock, VideoBlock, or AudioBlock.
    """
    source = {
        "type": "base64",
        "media_type": media_type,
        "data": base64_data,
    }
    if category == "image":
        return ImageBlock(type="image", source=source)
    elif category == "video":
        return VideoBlock(type="video", source=source)
    else:  # audio
        return AudioBlock(type="audio", source=source)


async def _handle_http_media(url: str) -> ToolResponse:
    """Handle media fetching from HTTP URL.

    Args:
        url: HTTP(S) URL to fetch media from.

    Returns:
        ToolResponse with media block or error.
    """
    media_data, media_type, error = await _fetch_http_media(url)
    if error:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: {error}")],
        )

    base64_data = base64.b64encode(media_data).decode("utf-8")

    if media_type.startswith("image/"):
        block = ImageBlock(
            type="image",
            source={
                "type": "base64",
                "media_type": media_type,
                "data": base64_data,
            },
        )
    elif media_type.startswith("video/"):
        block = VideoBlock(
            type="video",
            source={
                "type": "base64",
                "media_type": media_type,
                "data": base64_data,
            },
        )
    elif media_type.startswith("audio/"):
        block = AudioBlock(
            type="audio",
            source={
                "type": "base64",
                "media_type": media_type,
                "data": base64_data,
            },
        )
    else:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Unsupported media type: {media_type}",
                ),
            ],
        )

    return ToolResponse(content=[block])


def _validate_local_file(file_path: str) -> tuple[bool, str]:
    """Validate local file path and return resolved path or error.

    Args:
        file_path: Path to validate.

    Returns:
        Tuple of (is_valid, resolved_path_or_error).
    """
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    if not os.path.lexists(file_path):
        return False, f"Error: File does not exist: {file_path}"

    if os.path.islink(file_path) and not os.path.exists(file_path):
        return (
            False,
            f"Error: Symbolic link points to non-existent location: {file_path}",
        )

    file_path = os.path.realpath(file_path)

    if not os.path.isfile(file_path):
        return False, f"Error: Path is not a file: {file_path}"

    return True, file_path


def _check_file_validity(file_path: str) -> tuple[bool, str]:
    """Check file format and size validity.

    Args:
        file_path: Path to the file.

    Returns:
        Tuple of (is_valid, media_type_or_error).
    """
    media_type = _get_media_type(file_path)
    if not media_type:
        supported = ", ".join(SUPPORTED_FORMATS.keys())
        return (
            False,
            f"Error: Unsupported media format. Supported formats: {supported}",
        )

    is_valid, error = _validate_media_magic(file_path)
    if not is_valid:
        return False, f"Error: {error}"

    file_size = os.path.getsize(file_path)
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        return (
            False,
            f"Error: File too large ({size_mb:.2f}MB), maximum allowed is 20MB.",
        )

    return True, media_type


def _compress_image_file(
    file_path: str,
    max_size_mb: float,
) -> tuple[str | None, bool]:
    """Compress image file and return temp path.

    Args:
        file_path: Path to image file.
        max_size_mb: Target max size in MB.

    Returns:
        Tuple of (temp_file_path, was_compressed).
    """
    fd, temp_file = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)

    if _compress_image(file_path, temp_file, max_size_mb):
        return temp_file, True
    os.unlink(temp_file)
    return None, False


async def _compress_video_file(
    file_path: str,
    max_size_mb: float,
    video_fps: int,
) -> tuple[str | None, bool]:
    """Compress video file and return temp path.

    Args:
        file_path: Path to video file.
        max_size_mb: Target max size in MB.
        video_fps: Frame rate for compression.

    Returns:
        Tuple of (temp_file_path, was_compressed).
    """
    fd, temp_file = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    if await _compress_video(file_path, temp_file, max_size_mb, video_fps):
        return temp_file, True
    os.unlink(temp_file)
    return None, False


async def _compress_file_if_needed(
    file_path: str,
    category: str,
    compress: bool,
    max_size_mb: float,
    video_fps: int,
) -> tuple[str, bool, str | None]:
    """Compress file if needed and return path to use.

    Args:
        file_path: Original file path.
        category: File category.
        compress: Whether compression is enabled.
        max_size_mb: Target max size in MB.
        video_fps: Video frame rate for compression.

    Returns:
        Tuple of (file_to_read, was_compressed, temp_file_path).
    """
    file_size = os.path.getsize(file_path)
    if not compress or file_size <= max_size_mb * 1024 * 1024:
        return file_path, False, None

    temp_file: str | None = None
    was_compressed = False

    if category == "image":
        temp_file, was_compressed = _compress_image_file(
            file_path,
            max_size_mb,
        )
    elif category == "video":
        temp_file, was_compressed = await _compress_video_file(
            file_path,
            max_size_mb,
            video_fps,
        )

    if was_compressed and temp_file:
        return temp_file, True, temp_file
    return file_path, False, None


async def read_media(
    source: str,
    compress: bool = True,
    max_size_mb: float = 5.0,
    video_fps: int = 1,
) -> ToolResponse:
    """Read media file (image, video, audio) and return appropriate Block.

    Supports image, video and audio formats with automatic compression
    to fit model input limits.

    Args:
        source (`str`):
            Media file source, can be:
            - Local file path (e.g., /Users/xxx/video.mp4)
            - file:// URL (e.g., file:///Users/xxx/audio.mp3)
            - http(s):// URL (e.g., https://example.com/image.png)

        compress (`bool`):
            Whether to enable compression (default True). For large files,
            compression can reduce size to fit model input limits.

        max_size_mb (`float`):
            Target file size limit after compression (MB), default 5MB.
            Returns error if original file exceeds 20MB.

        video_fps (`int`):
            Video frame extraction parameter, frames per second to keep (default 1).
            - 1 = 1 frame per second (suitable for video content analysis)
            - 5 = 5 frames per second (smoother)
            - 0 = No frame extraction, keep original frame rate
            Frame extraction can significantly reduce video file size.

    Returns:
        `ToolResponse`: Contains appropriate Block (ImageBlock, VideoBlock, AudioBlock)
                       or error message.

    Examples:
        >>> # Read local image
        >>> await read_media("/path/to/photo.png")

        >>> # Read video with frame extraction (2 fps)
        >>> await read_media("/path/to/video.mp4", video_fps=2)

        >>> # Read audio from URL
        >>> await read_media("https://example.com/audio.mp3")

        >>> # Disable compression
        >>> await read_media("/path/to/small.gif", compress=False)
    """
    if not source:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: No media file source provided.",
                ),
            ],
        )

    source_type, parsed_source, error = _parse_source(source)
    if error:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: {error}")],
        )

    # Handle HTTP URLs
    if source_type == "http_url":
        if parsed_source is None:
            return ToolResponse(
                content=[TextBlock(type="text", text="Error: Invalid URL")],
            )
        return await _handle_http_media(parsed_source)

    # Handle local files and file:// URLs
    file_path = parsed_source
    if file_path is None:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: Cannot parse media file source",
                ),
            ],
        )

    # Validate local file
    is_valid, result = _validate_local_file(file_path)
    if not is_valid:
        return ToolResponse(content=[TextBlock(type="text", text=result)])
    file_path = result

    # Check file format and size
    is_valid, result = _check_file_validity(file_path)
    if not is_valid:
        return ToolResponse(content=[TextBlock(type="text", text=result)])
    media_type = result

    # Determine file category
    category = _get_file_category(file_path)

    # Compress if needed
    file_to_read, was_compressed, temp_file = await _compress_file_if_needed(
        file_path,
        category,
        compress,
        max_size_mb,
        video_fps,
    )
    if was_compressed and category == "video":
        media_type = "video/mp4"

    try:
        # Read and encode file
        with open(file_to_read, "rb") as f:
            media_data = f.read()

        base64_data = base64.b64encode(media_data).decode("utf-8")

        # Build info text
        final_size_mb = len(media_data) / (1024 * 1024)
        info_text = f"Media file loaded: {os.path.basename(source)} ({final_size_mb:.2f}MB)"
        if was_compressed:
            info_text += " [compressed]"
        if category == "video" and video_fps != 1 and video_fps > 0:
            info_text += f" [frame extraction: {video_fps}fps]"

        # Create block
        block = _create_media_block(category, media_type, base64_data)

        return ToolResponse(
            content=[TextBlock(type="text", text=info_text), block],
        )

    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Failed to read file: {e}",
                ),
            ],
        )
    finally:
        # Clean up temp file if created
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except Exception:
                pass
