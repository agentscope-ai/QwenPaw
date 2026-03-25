# -*- coding: utf-8 -*-
"""Unified tool functions that route through the fs_backend adapter.

These functions replace the separate local/E2B/AgentScope tool variants.
They have the same signatures and names as the originals so the agent
sees no difference.

Usage in _create_toolkit()::

    from copaw.agents.fs_backend.tools import (
        unified_shell,
        unified_python,
        unified_read_file,
        unified_write_file,
        unified_list_files,
    )
"""

import logging
from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from .adapter import get_backend
from ..tools.utils import truncate_shell_output

logger = logging.getLogger(__name__)


async def execute_shell_command(
    command: str,
    timeout: int = 60,
) -> ToolResponse:
    """Execute given command and return the result.

    When a cloud sandbox backend is active, the command runs inside the
    isolated sandbox container. Otherwise it runs locally.

    Args:
        command (`str`):
            The shell command to execute.
        timeout (`int`, defaults to `60`):
            Maximum time in seconds the command is allowed to run.

    Returns:
        `ToolResponse`:
            The tool response containing the command output.
    """
    cmd = (command or "").strip()
    if not cmd:
        return ToolResponse(
            content=[
                TextBlock(type="text", text="Error: No command provided.")
            ],
        )

    backend = get_backend()
    result = await backend.run_command(cmd, timeout=timeout)

    stdout = truncate_shell_output(result.stdout)
    stderr = truncate_shell_output(result.stderr)

    if result.exit_code == 0:
        response_text = (
            stdout if stdout else "Command executed successfully (no output)."
        )
    else:
        parts = [f"Command failed with exit code {result.exit_code}."]
        if stdout:
            parts.append(f"\n[stdout]\n{stdout}")
        if stderr:
            parts.append(f"\n[stderr]\n{stderr}")
        response_text = "".join(parts)

    return ToolResponse(
        content=[TextBlock(type="text", text=response_text)],
    )


async def execute_python_code(
    code: str,
    timeout: float = 300,
) -> ToolResponse:
    """Execute the given Python code.

    Capture the return code, stdout and stderr.

    Note you must ``print`` the output to get the result. When a cloud
    sandbox backend is active, the code runs inside the isolated sandbox.

    Args:
        code (`str`):
            The Python code to be executed.
        timeout (`float`, defaults to `300`):
            Maximum time in seconds the code is allowed to run.

    Returns:
        `ToolResponse`:
            The response containing returncode, stdout, stderr in XML tags.
    """
    if not (code or "").strip():
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="<returncode>-1</returncode><stdout></stdout>"
                    "<stderr>Error: No code provided.</stderr>",
                )
            ],
        )

    backend = get_backend()
    result = await backend.run_python(code, timeout=timeout)

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=(
                    f"<returncode>{result.exit_code}</returncode>"
                    f"<stdout>{result.stdout}</stdout>"
                    f"<stderr>{result.stderr}</stderr>"
                ),
            )
        ],
    )


async def sandbox_read_file(file_path: str) -> ToolResponse:
    """Read the content of a file in the sandbox (or locally if no sandbox).

    Args:
        file_path (`str`):
            Path to the file.

    Returns:
        `ToolResponse`: The file contents or an error message.
    """
    if not (file_path or "").strip():
        return ToolResponse(
            content=[
                TextBlock(type="text", text="Error: file_path is required.")
            ],
        )

    backend = get_backend()
    try:
        content = await backend.read_file(file_path)
    except Exception as exc:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Failed to read file '{file_path}': {exc}",
                )
            ],
        )

    return ToolResponse(
        content=[TextBlock(type="text", text=content or "(empty file)")],
    )


async def sandbox_write_file(file_path: str, content: str) -> ToolResponse:
    """Write content to a file in the sandbox (or locally if no sandbox).

    Args:
        file_path (`str`):
            Path to the file.
        content (`str`):
            Text content to write.

    Returns:
        `ToolResponse`: Success or error message.
    """
    if not (file_path or "").strip():
        return ToolResponse(
            content=[
                TextBlock(type="text", text="Error: file_path is required.")
            ],
        )

    backend = get_backend()
    try:
        await backend.write_file(file_path, content or "")
    except Exception as exc:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Failed to write file '{file_path}': {exc}",
                )
            ],
        )

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"Written {len(content or '')} bytes to '{file_path}'",
            )
        ],
    )


async def sandbox_list_files(
    dir_path: str = "/home/user",
    depth: int = 1,
) -> ToolResponse:
    """List files in a directory in the sandbox (or locally if no sandbox).

    Args:
        dir_path (`str`, defaults to ``/home/user``):
            Directory path to list.
        depth (`int`, defaults to ``1``):
            Recursion depth.

    Returns:
        `ToolResponse`: Formatted directory listing or error message.
    """
    path = (dir_path or "/home/user").strip() or "/home/user"
    depth = max(1, int(depth))

    backend = get_backend()
    try:
        entries = await backend.list_files(path, depth)
    except Exception as exc:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Failed to list directory '{path}': {exc}",
                )
            ],
        )

    if not entries:
        return ToolResponse(
            content=[
                TextBlock(type="text", text=f"(empty directory: {path})")
            ],
        )

    lines = []
    for entry in entries:
        size_str = f"  {entry.size}B" if entry.size is not None else ""
        lines.append(f"{'d' if entry.is_dir else 'f'}  {entry.path}{size_str}")

    return ToolResponse(
        content=[TextBlock(type="text", text="\n".join(lines))],
    )


async def sandbox_download_file(
    file_path: str, local_path: str
) -> ToolResponse:
    """Download a file from the sandbox and save it locally.

    Only meaningful when a cloud backend is active. For E2B, uses the
    SDK's binary download. For AgentScope, reads via shell and saves.

    Args:
        file_path (`str`):
            Path to the file inside the sandbox.
        local_path (`str`):
            Local path to save the file.

    Returns:
        `ToolResponse`: Success or error message.
    """
    if not (file_path or "").strip():
        return ToolResponse(
            content=[
                TextBlock(type="text", text="Error: file_path is required.")
            ],
        )
    if not (local_path or "").strip():
        return ToolResponse(
            content=[
                TextBlock(type="text", text="Error: local_path is required.")
            ],
        )

    backend = get_backend()

    try:
        # Try E2B-specific binary download first
        if hasattr(backend, "download_file"):
            content = await backend.download_file(file_path)
        else:
            # Fallback: read as text and encode
            text = await backend.read_file(file_path)
            content = text.encode("utf-8")
    except Exception as exc:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Failed to download '{file_path}': {exc}",
                )
            ],
        )

    try:
        dest = Path(local_path).expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    except Exception as exc:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Error: Downloaded but failed to save"
                        f" to '{local_path}': {exc}"
                    ),
                )
            ],
        )

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=(
                    f"Downloaded '{file_path}'"
                    f" ({len(content)} bytes) -> '{local_path}'"
                ),
            )
        ],
    )
