# -*- coding: utf-8 -*-
"""Offloader for persisting compressed context and tool results.

Implements the agentscope ``Offloader`` protocol so the native
``Agent.compress_context()`` automatically persists evicted messages
to date-grouped JSONL files and truncated tool results to individual
text files.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
import aiofiles.os

if TYPE_CHECKING:
    from agentscope.message import Msg, ToolResultBlock

logger = logging.getLogger(__name__)


class QwenPawOffloader:
    """Persist compressed context and tool results to disk.

    * ``offload_context`` — messages to
      ``{dialog_path}/{YYYY-MM-DD}.jsonl`` (append).
    * ``offload_tool_result`` — tool output to
      ``{tool_results_dir}/{uuid}.txt``.
    """

    def __init__(
        self,
        dialog_path: str,
        tool_results_dir: str,
    ) -> None:
        self._dialog_path = dialog_path
        self._tool_results_dir = tool_results_dir

    async def offload_context(
        self,
        session_id: str,  # pylint: disable=unused-argument
        msgs: list["Msg"],
    ) -> str:
        """Persist compressed messages grouped by date.

        ``session_id`` is required by the AgentScope ``Offloader``
        protocol but intentionally unused here: QwenPaw archives
        all sessions into shared date-grouped files
        (``{dialog_path}/{YYYY-MM-DD}.jsonl``), matching the
        original ``LightContextManager`` timeline design.
        """
        if not msgs:
            return ""

        await aiofiles.os.makedirs(self._dialog_path, exist_ok=True)

        messages_by_date: dict[str, list["Msg"]] = {}
        for msg in msgs:
            try:
                date_str = (
                    msg.timestamp.split()[0]
                    if msg.timestamp
                    else datetime.now().strftime("%Y-%m-%d")
                )
            except Exception:
                date_str = datetime.now().strftime("%Y-%m-%d")
            messages_by_date.setdefault(date_str, []).append(msg)

        last_path = ""
        for date_str, date_msgs in messages_by_date.items():
            filepath = os.path.join(self._dialog_path, f"{date_str}.jsonl")
            try:
                sorted_msgs = sorted(
                    date_msgs,
                    key=lambda m: m.timestamp or "",
                )
            except Exception:
                sorted_msgs = date_msgs

            async with aiofiles.open(
                filepath,
                mode="a",
                encoding="utf-8",
            ) as f:
                for msg in sorted_msgs:
                    await f.write(
                        json.dumps(msg.to_dict(), ensure_ascii=False) + "\n",
                    )
            last_path = filepath
            logger.info(
                "Offloaded %d messages to %s",
                len(sorted_msgs),
                filepath,
            )

        return last_path

    async def offload_tool_result(
        self,
        session_id: str,  # pylint: disable=unused-argument
        tool_result: "ToolResultBlock",
    ) -> str:
        """Persist a truncated tool result to a text file.

        ``session_id`` unused — same rationale as
        :meth:`offload_context`.
        """
        await aiofiles.os.makedirs(self._tool_results_dir, exist_ok=True)

        filepath = os.path.join(
            self._tool_results_dir,
            f"{uuid.uuid4().hex}.txt",
        )

        output = getattr(tool_result, "output", None) or ""
        if isinstance(output, list):
            parts = [self._render_block(block) for block in output]
            content = "\n".join(part for part in parts if part)
        else:
            content = str(output)

        # Never persist an empty file: downstream readers treat a missing
        # payload as a hard error, so fall back to a compact repr of the
        # raw output when no renderable block was found.
        if not content:
            content = str(output)

        async with aiofiles.open(filepath, mode="w", encoding="utf-8") as f:
            await f.write(content)

        logger.info("Offloaded tool result to %s", filepath)
        return filepath

    @staticmethod
    def _render_block(block: object) -> str:
        """Render a single tool-result block to text for on-disk storage.

        Handles both plain ``dict`` blocks and the typed message blocks
        (``TextBlock`` / ``DataBlock``) produced by the runtime. Text blocks
        contribute their text; binary blocks (images, audio, video) are
        replaced with a short placeholder so the persisted file stays
        human-readable and never ends up empty.
        """
        if isinstance(block, dict):
            block_type = block.get("type")
            text = block.get("text")
            source = block.get("source")
        else:
            block_type = getattr(block, "type", None)
            text = getattr(block, "text", None)
            source = getattr(block, "source", None)

        if block_type == "text" and text:
            return str(text)

        # Binary payloads have no textual form; emit a short placeholder so
        # the persisted file stays human-readable and is never empty. The
        # runtime models these as ``DataBlock(type="data")`` with the
        # concrete kind carried in ``source.media_type`` (e.g. "image/jpeg").
        if block_type in ("data", "image", "audio", "video", "file"):
            media_type = None
            if isinstance(source, dict):
                media_type = source.get("media_type")
            elif source is not None:
                media_type = getattr(source, "media_type", None)
            if media_type:
                kind = str(media_type).split("/", maxsplit=1)[0]
            elif block_type != "data":
                kind = block_type
            else:
                kind = "binary"
            return f"<{kind} content omitted>"

        if text:
            return str(text)
        return ""

    def cleanup_expired(self, retention_days: int = 5) -> int:
        """Delete tool-result files older than *retention_days*.

        Returns the number of files deleted.
        """
        tool_dir = Path(self._tool_results_dir)
        if not tool_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=retention_days)
        deleted = failed = 0

        for fp in tool_dir.glob("*.txt"):
            try:
                st = os.stat(fp)
                if sys.platform == "win32":
                    ts = st.st_ctime
                else:
                    ts = getattr(st, "st_birthtime", st.st_mtime)
                if datetime.fromtimestamp(ts) < cutoff:
                    fp.unlink()
                    deleted += 1
            except FileNotFoundError:
                pass
            except Exception as e:
                failed += 1
                logger.warning("Failed to delete %s: %s", fp, e)

        if deleted or failed:
            logger.info(
                "Cleaned up %d expired tool result files (%d failed)",
                deleted,
                failed,
            )
        return deleted
