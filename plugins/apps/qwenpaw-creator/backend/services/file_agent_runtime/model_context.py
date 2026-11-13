# -*- coding: utf-8 -*-
"""Bound ephemeral provider input without changing durable conversations."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping, Sequence

from services.project_files.model_view import (
    json_bytes,
    json_text,
    project_snapshot_view,
)

# A conservative serialized-input guard, not a claimed tokenizer count or
# provider context-window size. Leave room for SDK formatting and output.
MODEL_INPUT_BYTES = 384 * 1024
HISTORY_BYTES = 128 * 1024

# Providers bill inline media as vision tokens, not as request bytes. Counting
# a ``data:`` URL by its Base64 text length charges a 2MB image ~2.7MB against
# a 384KB budget, and because media-bearing user messages are contract content
# that compaction may not drop, the request is refused locally and never
# reaches the model — the understanding record just comes back empty. Charge a
# representative text-equivalent instead: decoded bytes / 128, clamped.
# Calibrated against a measured 2MB image costing ~2.5K vision tokens, which is
# roughly 10KB of text budget; the clamp keeps a huge clip from being treated
# as free.
_INLINE_MEDIA_BYTES_DIVISOR = 128
_INLINE_MEDIA_MIN_BYTES = 8 * 1024
_INLINE_MEDIA_MAX_BYTES = 512 * 1024


def _data_url_charge(url: str) -> int:
    """Text-budget representative of one inline ``data:`` URL."""
    _, _, encoded = url.partition(";base64,")
    decoded_bytes = len(encoded) * 3 // 4
    charge = decoded_bytes // _INLINE_MEDIA_BYTES_DIVISOR
    return max(
        _INLINE_MEDIA_MIN_BYTES,
        min(charge, _INLINE_MEDIA_MAX_BYTES),
    )


def _inline_media_relief(node: Any) -> int:
    """Bytes the naive JSON count over-charges for inline media parts.

    Subtracted from ``json_bytes`` so both measurements agree on what one
    image or clip actually costs the provider.
    """
    if node is None or isinstance(node, str):
        # Neither can carry relief, and this runs over the whole history of
        # every context estimate.
        return 0
    if isinstance(node, dict):
        relief = 0
        for key, value in node.items():
            if (
                key == "url"
                and isinstance(value, str)
                and value.startswith("data:")
            ):
                # A data URL is ASCII by construction, so the character
                # count is the byte count. Only the hand-edited exception
                # pays for an encode, which would otherwise copy every
                # megabyte of the payload a second time just to measure it.
                raw = (
                    len(value)
                    if value.isascii()
                    else len(value.encode("utf-8"))
                )
                relief += max(0, raw - _data_url_charge(value))
            elif isinstance(value, (dict, list)):
                # Only a mapping or a sequence can lead to a ``url`` key, so a
                # plain string of the history is not worth a call: a context
                # estimate walks the whole conversation on every turn.
                relief += _inline_media_relief(value)
        return relief
    if isinstance(node, list):
        return sum(_inline_media_relief(item) for item in node)
    return 0


def _media_aware_bytes(value: Any) -> int:
    """Serialized size with inline media charged as vision tokens."""
    return json_bytes(value) - _inline_media_relief(value)


# These are runtime receipts carried in the provider's user role, not human
# requirements. Keep durable messages intact, but let old receipts leave the
# bounded history just like old tool results. Unknown sources fail closed.
_AUTOMATED_HISTORY_SOURCES = frozenset(
    {
        "run_review_feedback",
        "render_review_feedback",
        "runtime_notification",
        "mainline_resume",
        "prompt_contract_resume",
        "yolo_auto_resume",
        "review_approval_resume",
    },
)


class ModelContextBudgetError(ValueError):
    pass


def _snapshot_content(content: Any) -> Mapping[str, Any] | None:
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                snapshot = _snapshot_content(part.get("text"))
                if snapshot is not None:
                    return snapshot
        return None
    if not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
    except ValueError:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("project"), dict):
        if payload["project"].get("project_id") and payload.get("etag"):
            return payload
    return None


def compact_conversation_history(
    history: list[dict[str, Any]],
    *,
    max_bytes: int = HISTORY_BYTES,
) -> list[dict[str, Any]]:
    result = deepcopy(history)
    latest_snapshot: int | None = None
    for index, item in enumerate(result):
        # Streaming/raw argument diagnostics belong to tracing, not context.
        item["metadata"] = {
            key: value
            for key, value in (item.get("metadata") or {}).items()
            if key
            in {
                "toolName",
                "tool",
                "resultKind",
                "transactionId",
                "reviewId",
                "status",
            }
        }
        for part in item.get("content") or []:
            if isinstance(part, dict) and _snapshot_content(part.get("text")):
                latest_snapshot = index
    if _media_aware_bytes(result) <= max_bytes:
        return result
    # Preserve every human goal/constraint and the newest state. Runtime
    # feedback also uses the user role; retaining every old review would make
    # a long production exceed the hard budget even after all tools are gone.
    # The current request/notification batch is outside this history view.
    removed = 0
    # Relief is a plain sum over list items and an elided slot contributes
    # zero, so carry it across the loop instead of re-walking every message
    # on each pass; json_bytes stays the loop's only full traversal, exactly
    # as it was before inline media entered the budget.
    relief = _inline_media_relief(result)
    for index, item in enumerate(result):
        human_input = (
            item.get("role") == "user"
            and item.get("source") not in _AUTOMATED_HISTORY_SOURCES
        )
        if human_input or index == latest_snapshot:
            continue
        if json_bytes(result) - relief <= max_bytes - 256:
            break
        result[index] = None
        relief -= _inline_media_relief(item)
        removed += 1
    return [
        {
            "role": "system",
            "source": "context_compaction",
            "elidedMessageCount": removed,
        },
        *(item for item in result if item is not None),
    ]


def _shrink_continuation(
    content: str,
    max_bytes: int,
    latest_snapshot: Mapping[str, Any] | None,
) -> str:
    marker = "CONVERSATION_HISTORY_JSON="
    ending = "\n\nCURRENT_USER_REQUEST=\n"
    if marker not in content or ending not in content:
        return content
    opening, rest = content.split(marker, 1)
    raw, request = rest.split(ending, 1)
    try:
        history = json.loads(raw)
    except ValueError:
        return content
    if not isinstance(history, list):
        return content
    if latest_snapshot:
        for item in history:
            # Human messages may contain JSON too; never rewrite them.
            if item.get("role") != "tool":
                continue
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                previous = _snapshot_content(part.get("text"))
                if previous and _snapshot_supersedes(
                    latest_snapshot,
                    previous,
                ):
                    part["text"] = json_text(
                        {
                            "resultKind": "project_change_receipt",
                            "projectId": previous["project"]["project_id"],
                            "generation": previous.get("generation"),
                            "etag": previous.get("etag"),
                            "note": "A newer Project view is in this run.",
                        },
                    )
    return (
        opening
        + marker
        + json_text(compact_conversation_history(history, max_bytes=max_bytes))
        + ending
        + request
    )


def _snapshot_supersedes(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
) -> bool:
    current_generation = current.get("generation")
    previous_generation = previous.get("generation")
    return (
        current["project"]["project_id"] == previous["project"]["project_id"]
        and isinstance(current_generation, int)
        and isinstance(previous_generation, int)
        and current_generation >= previous_generation
    )


# Preserve complete protocol groups throughout each compaction stage.
# pylint: disable-next=too-many-branches
def prepare_model_messages(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
    *,
    max_bytes: int = MODEL_INPUT_BYTES,
) -> list[dict[str, Any]]:
    """Drop completed tool exchanges as units; retain user/system contracts.

    Large completed calls include their arguments, so deleting just an old
    tool result is insufficient. Both call and results leave together. A
    removed latest Project view is reattached separately for reconstruction.
    """
    result = deepcopy([dict(item) for item in messages])
    latest_snapshot = None
    for item in result:
        content = item.get("content")
        if item.get("role") != "tool":
            continue
        parts = (
            [{"type": "text", "text": content}]
            if isinstance(content, str)
            else content
        )
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "text":
                continue
            payload = _snapshot_content(part.get("text"))
            if payload:
                part["text"] = json_text(
                    project_snapshot_view(
                        payload,
                        max_bytes=min(64 * 1024, max_bytes // 4),
                    ),
                )
                latest_snapshot = json.loads(part["text"])
        if isinstance(content, str):
            item["content"] = parts[0]["text"]

    # A prior-run snapshot must not be pinned alongside its replacement.
    # That duplicate can evict the script, skills and references just read,
    # trapping long productions in repeated reconstruction instead of work.
    for item in result:
        content = item.get("content")
        if item.get("role") == "user" and isinstance(content, str):
            item["content"] = _shrink_continuation(
                content,
                min(HISTORY_BYTES, max_bytes // 4),
                latest_snapshot,
            )

    def size() -> int:
        # Inline media is charged as vision tokens, not as Base64 text, so a
        # media-bearing contract message can fit alongside the tools schema.
        return _media_aware_bytes({"messages": result, "tools": tools})

    carried_snapshot = None
    while size() > max_bytes:
        removable = None
        for start, item in enumerate(result):
            if item.get("role") != "assistant":
                continue
            calls = item.get("tool_calls") or []
            end = start + 1
            if calls:
                while end < len(result) and result[end].get("role") == "tool":
                    end += 1
                wanted = {call.get("id") for call in calls}
                results_start = start + 1
                received = {
                    row.get("tool_call_id")
                    for row in result[results_start:end]
                }
                if wanted != received:
                    continue  # Never split an outstanding native tool group.
            removable = (start, end)
            break
        if removable is None:
            raise ModelContextBudgetError(
                "模型必要输入仍超过单次上下文预算；请缩小单次请求或分段读取项目。",
            )
        start, end = removable
        for item in result[start:end]:
            payload = _snapshot_content(item.get("content"))
            if payload:
                carried_snapshot = latest_snapshot
        del result[start:end]
        # Keep only the newest carried view, and count it in the next check.
        result = [item for item in result if not item.get("_context_snapshot")]
        if carried_snapshot:
            result.append(
                {
                    "role": "user",
                    "_context_snapshot": True,
                    "content": "CURRENT_PROJECT_MODEL_VIEW="
                    + json_text(carried_snapshot),
                },
            )
    for item in result:
        item.pop("_context_snapshot", None)
    return result
