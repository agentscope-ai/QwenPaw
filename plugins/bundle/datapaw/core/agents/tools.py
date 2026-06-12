# -*- coding: utf-8 -*-
"""Built-in tool functions for DataPaw sub-agents."""
from __future__ import annotations

import logging
from pathlib import Path

import aiohttp
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

logger = logging.getLogger("qwenpaw.datapaw.tools")


async def download_file(url: str, save_path: str) -> ToolResponse:
    """Download a file from a URL and save it to the specified path.

    Use this when a tool (e.g. execute_sql) returns a download_url
    for large result sets.  The file is saved to ``save_path``
    (parent directories are created automatically).

    Args:
        url: The URL to download from.
        save_path: The local file path to save the downloaded content.

    Returns:
        A message indicating success or failure.
    """
    try:
        dest = Path(save_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)

        size = dest.stat().st_size
        msg = f"下载成功，已保存为 {save_path}（{size} bytes）"
    except Exception as exc:
        msg = f"下载失败：{exc}"
    return ToolResponse(content=[TextBlock(type="text", text=msg)])
