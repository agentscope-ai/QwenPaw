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
    if json_bytes(result) <= max_bytes:
        return result
    # Preserve every human goal/constraint and the newest state. Runtime
    # feedback also uses the user role; retaining every old review would make
    # a long production exceed the hard budget even after all tools are gone.
    # The current request/notification batch is outside this history view.
    removed = 0
    for index, item in enumerate(result):
        human_input = (
            item.get("role") == "user"
            and item.get("source") not in _AUTOMATED_HISTORY_SOURCES
        )
        if human_input or index == latest_snapshot:
            continue
        if json_bytes(result) <= max_bytes - 256:
            break
        result[index] = None
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
        return json_bytes({"messages": result, "tools": tools})

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
