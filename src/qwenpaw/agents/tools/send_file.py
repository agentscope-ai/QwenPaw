# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-return-statements
import os
import mimetypes
import unicodedata
from urllib.parse import quote

from agentscope.tool import ToolResponse
from agentscope.message import TextBlock, DataBlock, URLSource

from .file_io import _resolve_file_path


def _path_to_file_url(path: str) -> str:
    """Convert a local file path to a proper file:// URL (RFC 8089).

    On Windows, converts:
      C:\\path\\file.txt      →  file:///C:/path/file.txt
      \\\\server\\share\\f.txt  →  file://server/share/f.txt

    Non-ASCII characters and ``%`` are percent-encoded so the URL is
    always valid ASCII and round-trips correctly through url2pathname.
    """
    # Normalize to absolute path
    abs_path = os.path.abspath(path)

    # Convert backslashes to forward slashes (Windows)
    if os.name == "nt":
        abs_path = abs_path.replace("\\", "/")

    # Percent-encode non-ASCII and special characters.
    # ``%`` must NOT be in *safe* — otherwise a literal ``%25`` in a
    # filename would survive un-encoded and be mis-decoded later.
    encoded_path = quote(abs_path, safe="/:@")

    # RFC 8089: file:///  (authority is empty → three slashes)
    if os.name == "nt":
        # UNC path: //server/share/… → file://server/share/…
        if encoded_path.startswith("//"):
            return f"file:{encoded_path}"
        # Local drive: C:/… → file:///C:/…
        return f"file:///{encoded_path}"
    # POSIX: abs_path already starts with "/" → file:///…
    return f"file://{encoded_path}"


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

    # Resolve relative paths to absolute paths based on workspace directory
    file_path = _resolve_file_path(file_path)

    if not os.path.exists(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    text=f"Error: The file {file_path} does not exist.",
                ),
            ],
        )

    if not os.path.isfile(file_path):
        return ToolResponse(
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

        return ToolResponse(
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
        return ToolResponse(
            content=[
                TextBlock(
                    text=f"Error: Send file failed due to \n{e}",
                ),
            ],
        )
