# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-return-statements
import os
import mimetypes
import unicodedata
from pathlib import Path

from agentscope.tool import ToolResponse
from agentscope.message import (
    TextBlock,
    ImageBlock,
    AudioBlock,
    VideoBlock,
)

from ..schema import FileBlock
from ...constant import WORKING_DIR

# Only allow files under this directory, mirroring message_processing.py
_ALLOWED_MEDIA_ROOT = WORKING_DIR / "media"


def _is_allowed_media_path(path: str) -> bool:
    """True if path is a file under _ALLOWED_MEDIA_ROOT.

    Returns False when the path is invalid, cannot be resolved,
    is not a regular file, or lies outside the allowed media root.
    """
    try:
        resolved = Path(path).expanduser().resolve()
        root = _ALLOWED_MEDIA_ROOT.resolve()
        return resolved.is_file() and resolved.is_relative_to(root)
    except Exception:
        return False


def _auto_as_type(mt: str) -> str:
    if mt.startswith("image/"):
        return "image"
    if mt.startswith("audio/"):
        return "audio"
    if mt.startswith("video/"):
        return "video"
    return "file"


async def send_file_to_user(
    file_path: str,
) -> ToolResponse:
    """Send a file to the user.

    The file must be located inside the allowed media directory
    (``<working_dir>/media``).  Attempting to send a file from outside that
    directory will return an error so that the agent is aware of the failure.

    Args:
        file_path (`str`):
            Path to the file to send.  Must be inside the media directory.

    Returns:
        `ToolResponse`:
            The tool response containing the file or an error message.
    """

    # Normalize the path: expand ~ and fix Unicode normalization differences
    # (e.g. macOS stores filenames as NFD but paths from the LLM arrive as NFC,
    # causing os.path.exists to return False for files that do exist).
    file_path = os.path.expanduser(unicodedata.normalize("NFC", file_path))

    if not os.path.exists(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The file {file_path} does not exist.",
                ),
            ],
        )

    if not os.path.isfile(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {file_path} is not a file.",
                ),
            ],
        )

    # Detect MIME type
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        # Default to application/octet-stream for unknown types
        mime_type = "application/octet-stream"
    as_type = _auto_as_type(mime_type)

    try:
        # Use local file URL instead of base64
        absolute_path = os.path.abspath(file_path)

        if not _is_allowed_media_path(absolute_path):
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: Media file outside allowed directory: {os.path.basename(file_path)}",
                    ),
                ],
            )

        file_url = f"file://{absolute_path}"
        source = {"type": "url", "url": file_url}

        if as_type == "image":
            return ToolResponse(
                content=[
                    ImageBlock(type="image", source=source),
                    TextBlock(type="text", text="File sent successfully."),
                ],
            )
        if as_type == "audio":
            return ToolResponse(
                content=[
                    AudioBlock(type="audio", source=source),
                    TextBlock(type="text", text="File sent successfully."),
                ],
            )
        if as_type == "video":
            return ToolResponse(
                content=[
                    VideoBlock(type="video", source=source),
                    TextBlock(type="text", text="File sent successfully."),
                ],
            )

        return ToolResponse(
            content=[
                FileBlock(
                    type="file",
                    source=source,
                    filename=os.path.basename(file_path),
                ),
                TextBlock(type="text", text="File sent successfully."),
            ],
        )

    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Send file failed due to \n{e}",
                ),
            ],
        )
