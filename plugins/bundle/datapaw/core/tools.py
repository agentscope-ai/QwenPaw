# -*- coding: utf-8 -*-
"""Built-in tool functions for DataPaw agents."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Awaitable, Callable

import aiohttp
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from .path_context import PathContext

logger = logging.getLogger("qwenpaw.datapaw.tools")


def _resolve_save_path(
    save_path: str,
    workspace_dir: str | Path | None,
) -> Path:
    """Resolve a model-provided save path to the host filesystem."""
    dest = Path(save_path).expanduser()
    if dest.is_absolute() or workspace_dir is None:
        return dest

    context = PathContext(mount_dir=Path(workspace_dir).expanduser())
    resolved, error = context.to_host(save_path)
    if error is not None:
        raise ValueError(error)
    return resolved


async def download_file(
    url: str,
    save_path: str,
    *,
    workspace_dir: str | Path | None = None,
) -> ToolResponse:
    """Download a file from a URL and save it to the specified path.

    Use this when a tool such as ``execute_sql`` returns a ``download_url``
    for large result sets. Parent directories are created automatically.

    Args:
        url: The URL to download from.
        save_path: The local file path to save the downloaded content.

    Returns:
        A message indicating success or failure.
    """
    try:
        dest = _resolve_save_path(save_path, workspace_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)

        size = dest.stat().st_size
        msg = f"下载成功，已保存为 {dest}（{size} bytes）"
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("DataPaw download_file failed", exc_info=True)
        msg = f"下载失败：{exc}"
    return ToolResponse(content=[TextBlock(type="text", text=msg)])


def bind_download_file_tool(
    workspace_dir: str | Path | None,
) -> Callable[[str, str], Awaitable[ToolResponse]]:
    """Bind ``download_file`` to an agent workspace without exposing it."""

    async def workspace_download_file(url: str, save_path: str) -> ToolResponse:
        """Download a file from a URL and save it to the specified path."""
        return await download_file(
            url,
            save_path,
            workspace_dir=workspace_dir,
        )

    workspace_download_file.__name__ = "download_file"
    workspace_download_file.__qualname__ = "download_file"
    return workspace_download_file


DEFAULT_TOOL_NAMES = ["download_file"]
TOOL_REGISTRY = {
    "download_file": download_file,
}
