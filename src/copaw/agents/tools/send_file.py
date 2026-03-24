# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-return-statements
import logging
import os
import mimetypes
import tempfile
import unicodedata

from agentscope.tool import ToolResponse
from agentscope.message import (
    TextBlock,
    ImageBlock,
    AudioBlock,
    VideoBlock,
)

from ..schema import FileBlock
from .file_io import _is_cloud_mode

_logger = logging.getLogger(__name__)


def _auto_as_type(mt: str) -> str:
    if mt.startswith("image/"):
        return "image"
    if mt.startswith("audio/"):
        return "audio"
    if mt.startswith("video/"):
        return "video"
    return "file"


async def _download_from_sandbox(file_path: str) -> str:
    """Download a file from the OpenSandbox to a local temp location.

    Returns the local temp file path.
    """
    from ...fs_backend.adapter import get_fs_adapter
    adapter = get_fs_adapter()
    result = await adapter.read_file(file_path)
    if not result.success:
        raise IOError(f"Failed to read file from sandbox: {result.error_message}")

    # Preserve the original filename and extension
    basename = os.path.basename(file_path)
    _, ext = os.path.splitext(basename)

    tmp_dir = tempfile.mkdtemp(prefix="copaw_send_")
    local_path = os.path.join(tmp_dir, basename)

    content = result.data
    if isinstance(content, bytes):
        with open(local_path, "wb") as f:
            f.write(content)
    else:
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(content)

    return local_path


async def send_file_to_user(
    file_path: str,
) -> ToolResponse:
    """Send a file to the user.

    Args:
        file_path (`str`):
            Path to the file to send.

    Returns:
        `ToolResponse`:
            The tool response containing the file or an error message.
    """

    # Normalize the path: expand ~ and fix Unicode normalization differences
    # (e.g. macOS stores filenames as NFD but paths from the LLM arrive as NFC,
    # causing os.path.exists to return False for files that do exist).
    file_path = os.path.expanduser(unicodedata.normalize("NFC", file_path))

    # In cloud mode, download the file from sandbox first
    if _is_cloud_mode():
        try:
            file_path = await _download_from_sandbox(file_path)
        except Exception as e:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: Failed to download file from sandbox: {e}",
                    ),
                ],
            )

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
