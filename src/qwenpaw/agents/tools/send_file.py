# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-return-statements
import os
import mimetypes
import unicodedata
from urllib.parse import unquote

from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState
from agentscope.message import TextBlock, DataBlock, URLSource

from ...runtime.tool_registry import tool_descriptor
from .file_io import _resolve_file_path, _path_to_file_url


@tool_descriptor(requires_sandbox=("file_read",), async_execution=True)
async def send_file_to_user(
    file_path: str,
) -> ToolChunk:
    """Send a file to the user.

    Args:
        file_path (`str`):
            Path to the file to send.

    Returns:
        `ToolChunk`:
            The tool response containing the file or an error message.
    """

    # Decode percent-encoded chars (model may pass URL-encoded paths from context)
    # then normalize Unicode (macOS NFD vs NFC).
    file_path = unquote(file_path)
    file_path = os.path.expanduser(unicodedata.normalize("NFC", file_path))

    # Resolve relative paths to absolute paths based on workspace directory
    file_path = _resolve_file_path(file_path)

    if not os.path.exists(file_path):
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    text=f"Error: The file {file_path} does not exist.",
                ),
            ],
        )

    if not os.path.isfile(file_path):
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    text=f"Error: The path {file_path} is not a file.",
                ),
            ],
        )

    # Detect MIME type
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        # Default to application/octet-stream for unknown types
        mime_type = "application/octet-stream"

    try:
        file_url = _path_to_file_url(file_path)

        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                DataBlock(
                    source=URLSource(
                        url=file_url,
                        media_type=mime_type,
                    ),
                    name=os.path.basename(file_path),
                ),
                TextBlock(text="File sent successfully."),
            ],
        )

    except Exception as e:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    text=f"Error: Send file failed due to \n{e}",
                ),
            ],
        )
