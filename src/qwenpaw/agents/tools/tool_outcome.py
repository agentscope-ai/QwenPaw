# -*- coding: utf-8 -*-
"""Helpers for consistent machine- and model-readable tool outcomes."""

from __future__ import annotations

from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

TOOL_OUTCOME_METADATA_KEY = "tool_outcome"


def error_tool_chunk(
    message: str,
    *,
    code: str,
    retryable: bool,
    same_args_retry_useful: bool,
    next_action: str,
    metadata: dict[str, Any] | None = None,
) -> ToolChunk:
    """Build an error result that remains clear after model formatting.

    Provider formatters currently omit ``ToolResultState`` and tool metadata
    from model requests. The short outcome footer therefore mirrors the
    machine-readable metadata without replacing the human-readable error.
    """
    outcome = {
        "status": "error",
        "code": code,
        "retryable": retryable,
        "same_args_retry_useful": same_args_retry_useful,
        "next_action": next_action,
    }
    chunk_metadata = dict(metadata or {})
    chunk_metadata[TOOL_OUTCOME_METADATA_KEY] = outcome
    outcome_text = (
        f"{message}\n\n"
        f"TOOL_OUTCOME: status=error; code={code}; "
        f"retryable={str(retryable).lower()}; "
        f"same_args_retry_useful="
        f"{str(same_args_retry_useful).lower()}; "
        f"next_action={next_action}"
    )
    return ToolChunk(
        is_last=True,
        state=ToolResultState.ERROR,
        content=[TextBlock(type="text", text=outcome_text)],
        metadata=chunk_metadata,
    )
