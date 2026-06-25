# -*- coding: utf-8 -*-
"""Execution-layer hard cap for final tool responses."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ..constant import TRUNCATION_NOTICE_MARKER
from ._context import ToolCallContext

logger = logging.getLogger(__name__)


class ToolResultLimiter:
    """Apply a strict aggregate text-byte cap to a final ToolResponse."""

    def __init__(
        self,
        *,
        enabled: bool,
        max_text_bytes: int,
        cache_dir: Path | str | None,
    ) -> None:
        self._enabled = enabled
        self._max_text_bytes = max_text_bytes
        self._cache_dir = Path(cache_dir) if cache_dir else None

    def limit(
        self,
        response: ToolResponse,
        context: ToolCallContext,
    ) -> ToolResponse:
        """Return a response whose aggregate text content is byte-bounded."""
        if not self._enabled:
            return response

        try:
            return self._limit(response, context)
        except Exception:
            logger.exception(
                "Failed to limit tool result",
                extra={
                    "tool_name": context.tool_name,
                    "tool_call_id": context.tool_call_id,
                },
            )
            return self._fail_closed(response)

    def _limit(
        self,
        response: ToolResponse,
        context: ToolCallContext,
    ) -> ToolResponse:
        content = list(response.content or [])
        original_bytes = _total_text_bytes(content)
        if original_bytes == 0:
            return response
        if self._max_text_bytes <= 0:
            return self._fail_closed(response)
        if original_bytes <= self._max_text_bytes:
            return response

        saved_path = self._save_original_text(content, context)
        limited_content, retained_bytes = self._limit_content(
            content,
            original_bytes=original_bytes,
            saved_path=saved_path,
        )
        result = _copy_response_with_content(response, limited_content)

        if _total_text_bytes(result.content or []) > self._max_text_bytes:
            return self._fail_closed(response)

        logger.info(
            "Capped tool result",
            extra={
                "tool_name": context.tool_name,
                "tool_call_id": context.tool_call_id,
                "original_bytes": original_bytes,
                "retained_bytes": retained_bytes,
            },
        )
        return result

    def _limit_content(
        self,
        content: list[Any],
        *,
        original_bytes: int,
        saved_path: str | None,
    ) -> tuple[list[Any], int]:
        notice = _build_notice(
            original_bytes=original_bytes,
            retained_bytes=0,
            saved_path=saved_path,
        )
        retained_content: list[Any] = []
        retained_bytes = 0

        for _ in range(8):
            bounded_notice = _utf8_prefix(notice, self._max_text_bytes)
            payload_budget = max(
                0,
                self._max_text_bytes - _byte_len(bounded_notice),
            )
            retained_content, retained_bytes = _retain_text_content(
                content,
                payload_budget,
            )
            next_notice = _build_notice(
                original_bytes=original_bytes,
                retained_bytes=retained_bytes,
                saved_path=saved_path,
            )
            if next_notice == notice:
                notice = next_notice
                break
            notice = next_notice

        for _ in range(8):
            bounded_notice = _utf8_prefix(notice, self._max_text_bytes)
            payload_budget = max(
                0,
                self._max_text_bytes - _byte_len(bounded_notice),
            )
            retained_content, retained_bytes = _retain_text_content(
                content,
                payload_budget,
            )
            bounded_notice = _utf8_prefix(
                _build_notice(
                    original_bytes=original_bytes,
                    retained_bytes=retained_bytes,
                    saved_path=saved_path,
                ),
                self._max_text_bytes,
            )
            total_bytes = retained_bytes + _byte_len(bounded_notice)
            if total_bytes <= self._max_text_bytes:
                retained_content.append(
                    TextBlock(type="text", text=bounded_notice),
                )
                return retained_content, retained_bytes
            notice = bounded_notice

        retained_content, _ = _retain_text_content(content, 0)
        fallback_notice = _utf8_prefix(
            _build_notice(
                original_bytes=original_bytes,
                retained_bytes=0,
                saved_path=saved_path,
            ),
            self._max_text_bytes,
        )
        if fallback_notice:
            retained_content.append(
                TextBlock(type="text", text=fallback_notice),
            )
        return retained_content, 0

    def _save_original_text(
        self,
        content: list[Any],
        context: ToolCallContext,
    ) -> str | None:
        if self._cache_dir is None:
            return None

        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            safe_id = _safe_filename_part(context.tool_call_id)
            path = self._cache_dir / f"{safe_id}-{uuid.uuid4().hex}.txt"
            path.write_text(_join_text_blocks(content), encoding="utf-8")
            return str(path)
        except OSError as exc:
            logger.warning(
                "Failed to save full tool result",
                extra={
                    "tool_name": context.tool_name,
                    "tool_call_id": context.tool_call_id,
                    "error": str(exc),
                },
            )
            return None

    def _fail_closed(self, response: ToolResponse) -> ToolResponse:
        content = [
            block
            for block in list(response.content or [])
            if not _is_text_block(block)
        ]
        notice = _utf8_prefix(
            (
                f"{TRUNCATION_NOTICE_MARKER}\n"
                "Tool output omitted because it exceeded the safe size limit."
            ),
            max(0, self._max_text_bytes),
        )
        if notice:
            content.append(TextBlock(type="text", text=notice))
        return _copy_response_with_content(response, content)


def _build_notice(
    *,
    original_bytes: int,
    retained_bytes: int,
    saved_path: str | None,
) -> str:
    lines = [
        TRUNCATION_NOTICE_MARKER,
        "Tool output truncated before entering agent context.",
        f"Original size: {original_bytes} bytes.",
        f"Retained size: {retained_bytes} bytes.",
    ]
    if saved_path:
        lines.append(f"Full output saved to: {saved_path}.")
    else:
        lines.append("Full output could not be persisted.")
    lines.append("Refine the query or read a smaller range.")
    return "\n".join(lines)


def _retain_text_content(
    content: list[Any],
    budget_bytes: int,
) -> tuple[list[Any], int]:
    remaining = max(0, budget_bytes)
    retained_bytes = 0
    retained_content: list[Any] = []

    for block in content:
        if not _is_text_block(block):
            retained_content.append(block)
            continue

        if remaining <= 0:
            continue

        text = _get_text(block)
        retained_text = _utf8_prefix(text, remaining)
        if not retained_text:
            continue

        current_bytes = _byte_len(retained_text)
        retained_content.append(_copy_text_block(block, retained_text))
        retained_bytes += current_bytes
        remaining -= current_bytes

    return retained_content, retained_bytes


def _join_text_blocks(content: list[Any]) -> str:
    return "\n\n".join(
        _get_text(block) for block in content if _is_text_block(block)
    )


def _total_text_bytes(content: list[Any]) -> int:
    return sum(
        _byte_len(_get_text(block))
        for block in content
        if _is_text_block(block)
    )


def _is_text_block(block: Any) -> bool:
    if isinstance(block, dict):
        return block.get("type") == "text" and isinstance(
            block.get("text"),
            str,
        )
    return getattr(block, "type", None) == "text" and isinstance(
        getattr(block, "text", None),
        str,
    )


def _get_text(block: Any) -> str:
    if isinstance(block, dict):
        return block.get("text", "")
    return getattr(block, "text", "")


def _copy_text_block(block: Any, text: str) -> Any:
    if isinstance(block, dict):
        copied = dict(block)
        copied["text"] = text
        return copied
    if hasattr(block, "model_copy"):
        return block.model_copy(update={"text": text})
    copied = TextBlock(type="text", text=text)
    block_id = getattr(block, "id", None)
    if block_id is not None and hasattr(copied, "id"):
        copied.id = block_id
    return copied


def _copy_response_with_content(
    response: ToolResponse,
    content: list[Any],
) -> ToolResponse:
    if hasattr(response, "model_copy"):
        return response.model_copy(update={"content": content})
    response.content = content
    return response


def _utf8_prefix(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _safe_filename_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:64].strip("._-")
    return safe or "tool-result"
