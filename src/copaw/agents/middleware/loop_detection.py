# -*- coding: utf-8 -*-
"""Loop detection middleware.

Detects repeated tool calls (same name + same args) and breaks the loop
by injecting a warning message, then force-stripping tool calls if the
agent persists.

Runs as a pre_reasoning hook — inspects memory after each acting step.
"""
import hashlib
import json
import logging
from collections import defaultdict
from typing import Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock

logger = logging.getLogger(__name__)

# Defaults
WARN_THRESHOLD = 3
HARD_LIMIT = 5
WINDOW_SIZE = 20


class LoopDetectionMiddleware:
    """Detect and break repetitive tool call loops.

    Strategy:
      1. After each model response, hash the tool calls (name + args).
      2. Track recent hashes in a sliding window.
      3. If same hash appears >= warn_threshold: inject warning message.
      4. If same hash appears >= hard_limit: strip tool_calls, force text output.
    """

    def __init__(
        self,
        warn_threshold: int = WARN_THRESHOLD,
        hard_limit: int = HARD_LIMIT,
        window_size: int = WINDOW_SIZE,
    ):
        self._warn_threshold = warn_threshold
        self._hard_limit = hard_limit
        self._window: list[str] = []
        self._window_size = window_size
        self._warned_hashes: set[str] = set()
        self._hard_broken = False

    @staticmethod
    def _hash_tool_call(name: str, args: Any) -> str:
        """Create a deterministic hash of a tool call."""
        raw = json.dumps({"name": name, "args": args}, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _count_hash(self, h: str) -> int:
        """Count occurrences of a hash in the window."""
        return self._window.count(h)

    def _extract_last_tool_calls(self, memory) -> list[tuple[str, Any]]:
        """Extract tool calls from the last assistant message in memory."""
        if not hasattr(memory, "content") or not memory.content:
            return []

        # Walk backwards to find last assistant message with tool calls
        for item in reversed(memory.content):
            msg = item[0] if isinstance(item, tuple) else item
            if not hasattr(msg, "role") or msg.role != "assistant":
                continue

            tool_calls = []
            content = msg.content if hasattr(msg, "content") else None
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        name = getattr(block, "name", "")
                        args = getattr(block, "input", {})
                        tool_calls.append((name, args))
            if tool_calls:
                return tool_calls
        return []

    async def __call__(
        self,
        agent: ReActAgent,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Pre-reasoning hook: check for tool call loops."""
        try:
            tool_calls = self._extract_last_tool_calls(agent.memory)
            if not tool_calls:
                return None

            # Hash all tool calls from last response
            hashes = [
                self._hash_tool_call(name, args)
                for name, args in tool_calls
            ]

            for h in hashes:
                self._window.append(h)

            # Trim window
            if len(self._window) > self._window_size:
                self._window = self._window[-self._window_size:]

            # Check for loops
            for h in set(hashes):
                count = self._count_hash(h)

                if count >= self._hard_limit:
                    # Hard break: inject stop message
                    if not self._hard_broken:
                        self._hard_broken = True
                        logger.warning(
                            "Loop hard break: hash=%s count=%d", h, count
                        )
                        stop_msg = Msg(
                            name="system",
                            role="system",
                            content=[TextBlock(
                                type="text",
                                text=(
                                    "⚠️ 检测到重复工具调用循环（同一操作已执行 "
                                    f"{count} 次）。请停止重复调用，"
                                    "直接用文字回答用户的问题。"
                                ),
                            )],
                        )
                        agent.memory.add(stop_msg)
                    return None

                if count >= self._warn_threshold and h not in self._warned_hashes:
                    self._warned_hashes.add(h)
                    logger.info(
                        "Loop warning: hash=%s count=%d", h, count
                    )
                    warn_msg = Msg(
                        name="system",
                        role="system",
                        content=[TextBlock(
                            type="text",
                            text=(
                                f"⚠️ 注意：你似乎在重复相同的操作（已执行 {count} 次）。"
                                "请检查是否需要换一种方法，或者直接回答用户。"
                            ),
                        )],
                    )
                    agent.memory.add(warn_msg)

        except Exception as e:
            logger.debug("LoopDetection error (non-fatal): %s", e)

        return None
