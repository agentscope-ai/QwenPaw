# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""Token counting and block-level statistics for AgentScope messages.

Used by :func:`context_stats.format_history_str` to render the ``/history``
command output with per-message token breakdowns.
"""

import json
import logging

from agentscope.message import Msg

from .as_msg_stat import AsMsgStat, AsBlockStat
from .estimate_token_counter import EstimatedTokenCounter

logger = logging.getLogger(__name__)


class AsMsgHandler:
    """Byte-estimation based token accounting for AgentScope messages.

    Uses :class:`EstimatedTokenCounter` (byte-length / divisor) for fast
    token estimation without requiring a model instance.  This makes it
    suitable for the ``/history`` UI command which runs in standalone mode
    (no agent or model loaded).
    """

    def __init__(self, token_counter: EstimatedTokenCounter):
        self._token_counter = token_counter

    async def count_str_token(self, text: str) -> int:
        """Count tokens in a string."""
        return await self._token_counter.count(text=text)

    async def _format_tool_result_output(
        self,
        output: str | list[dict],
    ) -> tuple[str, int]:
        """Convert tool result output to (text, token_count)."""
        if isinstance(output, str):
            return output, await self.count_str_token(output)

        textual_parts = []
        total_token_count = 0
        for block in output:  # pylint: disable=too-many-nested-blocks
            try:
                if not isinstance(block, dict) or "type" not in block:
                    logger.warning(
                        f"Invalid block: {block}, expected a dict "
                        f"with 'type' key, skipped.",
                    )
                    continue

                block_type = block["type"]

                if block_type == "text":
                    textual_parts.append(block.get("text", ""))
                    total_token_count += await self.count_str_token(
                        textual_parts[-1],
                    )

                elif block_type in ["image", "audio", "video", "file", "data"]:
                    source = block.get("source", {})
                    if (
                        isinstance(source, dict)
                        and source.get("type") == "base64"
                    ):
                        data = source.get("data", "")
                        total_token_count += len(data) // 4 if data else 10
                    else:
                        url = (
                            source.get("url", "")
                            if isinstance(source, dict)
                            else ""
                        )
                        total_token_count += (
                            await self.count_str_token(url) if url else 10
                        )
                        display_type = block_type
                        if block_type == "data" and isinstance(source, dict):
                            mt = source.get("media_type", "")
                            for prefix in ("image", "audio", "video"):
                                if mt.startswith(f"{prefix}/"):
                                    display_type = prefix
                                    break
                        textual_parts.append(f"[{display_type}] {url}")

                else:
                    logger.warning(
                        f"Unsupported block type '{block_type}' in "
                        f"tool result, skipped.",
                    )

            except Exception as e:
                logger.warning(
                    f"Failed to process block {block}: {e}, skipped.",
                )

        return "\n".join(textual_parts), total_token_count

    async def stat_message(self, message: Msg) -> AsMsgStat:
        """Analyze a message and return per-block token statistics."""
        blocks = []
        if isinstance(message.content, str):
            blocks.append(
                AsBlockStat(
                    block_type="text",
                    text=message.content,
                    token_count=await self.count_str_token(message.content),
                ),
            )
            return AsMsgStat(
                name=message.name or message.role,
                role=message.role,
                content=blocks,
                timestamp=message.timestamp or "",
                metadata=message.metadata or {},
            )

        for block in message.content:
            # agentscope 2.0 returns Pydantic block models (TextBlock,
            # DataBlock, ToolCallBlock, ...) instead of the 1.x dicts.
            # Normalise to a dict so the downstream ``.get()`` lookups still
            # work without rewriting every branch below.
            if hasattr(block, "model_dump"):
                block = block.model_dump()
            block_type = block.get("type", "unknown")

            if block_type == "text":
                text = block.get("text", "")
                token_count = await self.count_str_token(text)
                blocks.append(
                    AsBlockStat(
                        block_type=block_type,
                        text=text,
                        token_count=token_count,
                    ),
                )

            elif block_type == "thinking":
                thinking = block.get("thinking", "")
                token_count = await self.count_str_token(thinking)
                blocks.append(
                    AsBlockStat(
                        block_type=block_type,
                        text=thinking,
                        token_count=token_count,
                    ),
                )

            elif block_type in ("image", "audio", "video", "file", "data"):
                source = block.get("source", {})
                url = ""
                if isinstance(source, dict):
                    url = source.get("url", "")
                    if source.get("type") == "base64":
                        data = source.get("data", "")
                        token_count = len(data) // 4 if data else 10
                    else:
                        token_count = (
                            await self.count_str_token(url) if url else 10
                        )
                else:
                    token_count = 10
                display_type = block_type
                if block_type == "data":
                    mt = ""
                    if isinstance(source, dict):
                        mt = source.get("media_type", "")
                    for prefix in ("image", "audio", "video"):
                        if mt.startswith(f"{prefix}/"):
                            display_type = prefix
                            break
                blocks.append(
                    AsBlockStat(
                        block_type=display_type,
                        text="",
                        token_count=token_count,
                        media_url=url,
                    ),
                )

            elif block_type in ("tool_use", "tool_call"):
                tool_name = block.get("name", "")
                tool_input = block.get("input", "")
                try:
                    input_str = json.dumps(tool_input, ensure_ascii=False)
                except (TypeError, ValueError):
                    input_str = str(tool_input)
                token_count = await self.count_str_token(tool_name + input_str)
                blocks.append(
                    AsBlockStat(
                        block_type=block_type,
                        text="",
                        token_count=token_count,
                        tool_name=tool_name,
                        tool_input=input_str,
                    ),
                )

            elif block_type == "tool_result":
                tool_name = block.get("name", "")
                output = block.get("output", "")
                (
                    formatted_output,
                    token_count,
                ) = await self._format_tool_result_output(output)
                blocks.append(
                    AsBlockStat(
                        block_type=block_type,
                        text="",
                        token_count=token_count,
                        tool_name=tool_name,
                        tool_output=formatted_output,
                    ),
                )

            else:
                logger.warning(
                    f"Unsupported block type {block_type}, skipped.",
                )

        return AsMsgStat(
            name=message.name or message.role,
            role=message.role,
            content=blocks,
            timestamp=message.timestamp or "",
            metadata=message.metadata or {},
        )
