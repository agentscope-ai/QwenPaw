# -*- coding: utf-8 -*-
"""Custom memory implementation with bugfixes and extensions."""
import logging

from agentscope.agent._react_agent import _MemoryMark
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

logger = logging.getLogger(__name__)


def build_previous_summary(summary: str) -> str:
    """Build wrapped summary text that is prepended to memory context."""
    if not summary:
        return ""

    return (
        "<previous-summary>\n"
        f"{summary}\n"
        "</previous-summary>\n"
        "The above is a summary of our previous conversation.\n"
        "Use it as context to maintain continuity."
    )


class CoPawInMemoryMemory(InMemoryMemory):
    """Extended InMemoryMemory with bugfixes and summary support."""

    async def get_memory(
        self,
        mark: str | None = None,
        exclude_mark: str | None = _MemoryMark.COMPRESSED,
        prepend_summary: bool = True,
        **_kwargs,
    ) -> list[Msg]:
        """Get the messages from the memory by mark (if provided).

        Args:
            mark: Optional mark to filter messages
            exclude_mark: Optional mark to exclude messages
            prepend_summary: Whether to prepend compressed summary
            **_kwargs: Additional keyword arguments (ignored)

        Returns:
            List of filtered messages
        """
        if not (mark is None or isinstance(mark, str)):
            raise TypeError(
                f"The mark should be a string or None, but got {type(mark)}.",
            )

        if not (exclude_mark is None or isinstance(exclude_mark, str)):
            raise TypeError(
                f"The exclude_mark should be a string or None, but got "
                f"{type(exclude_mark)}.",
            )

        # Filter messages based on mark
        filtered_content = [
            (msg, marks)
            for msg, marks in self.content
            if mark is None or mark in marks
        ]

        # Further filter messages based on exclude_mark
        if exclude_mark is not None:
            filtered_content = [
                (msg, marks)
                for msg, marks in filtered_content
                if exclude_mark not in marks
            ]

        if prepend_summary and self._compressed_summary:
            previous_summary = build_previous_summary(
                self._compressed_summary,
            )

            return [
                Msg(
                    "user",
                    previous_summary,
                    "user",
                ),
                *[msg for msg, _ in filtered_content],
            ]

        return [msg for msg, _ in filtered_content]

    def get_compressed_summary(self) -> str:
        """Get the compressed summary of the memory."""
        return self._compressed_summary

    def state_dict(self) -> dict:
        """Get the state dictionary for serialization."""
        return {
            "content": [[msg.to_dict(), marks] for msg, marks in self.content],
            "_compressed_summary": self._compressed_summary,
        }

    def load_state_dict(self, state_dict: dict, strict: bool = True) -> None:
        """Load the state dictionary for deserialization."""
        if strict and "content" not in state_dict:
            raise KeyError(
                "The state_dict does not contain 'content' key required for "
                "InMemoryMemory.",
            )

        self.content = []
        for item in state_dict.get("content", []):
            if isinstance(item, (tuple, list)) and len(item) == 2:
                msg_dict, marks = item
                msg = Msg.from_dict(msg_dict)
                self.content.append((msg, marks))

            elif isinstance(item, dict):
                # For compatibility with older versions
                msg = Msg.from_dict(item)
                self.content.append((msg, []))

            else:
                raise ValueError(
                    "Invalid item format in state_dict for InMemoryMemory.",
                )

        self._compressed_summary = state_dict.get("_compressed_summary", "")
