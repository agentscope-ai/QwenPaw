# -*- coding: utf-8 -*-
"""Bounded, explicitly partial model views; never used as commit inputs."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping

from .json_pointer import join_pointer
from .models import is_snapshot_timeline_id

PROJECT_VIEW_BYTES = 64 * 1024


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_bytes(value: Any) -> int:
    return len(json_text(value).encode("utf-8"))


def bounded_json_view(value: Any, *, max_bytes: int) -> dict[str, Any]:
    """Preserve small values exactly, label every projection of a large one.

    Pointers are relative to the supplied value. Omitted collections and
    strings can be retrieved with read_project(pointer, offset, maxBytes).
    """
    for string_limit, item_limit in (
        (8192, 128),
        (2048, 64),
        (512, 24),
        (128, 8),
        (64, 2),
    ):
        omitted: list[str] = []

        # This recursive visitor cannot escape the current projection pass.
        # pylint: disable=cell-var-from-loop
        def visit(item: Any, pointer: str, depth: int = 0) -> Any:
            if depth > 24:
                omitted.append(pointer)
                return {"contextOmitted": True}
            if isinstance(item, str) and len(item) > string_limit:
                omitted.append(pointer)
                return item[:string_limit] + "… [context preview]"
            if isinstance(item, (dict, list)):
                pairs = (
                    list(item.items())
                    if isinstance(item, dict)
                    else list(enumerate(item))
                )
                # Keep the Project's top-level fields discoverable. In the
                # real schema, timelines/assets follow descriptive metadata;
                # truncating root keys would hide the entire working state.
                if depth > 0 and len(pairs) > item_limit:
                    omitted.append(pointer)
                    pairs = pairs[:item_limit]
                entries = [
                    (
                        key,
                        visit(
                            child,
                            join_pointer(pointer, str(key)),
                            depth + 1,
                        ),
                    )
                    for key, child in pairs
                ]
                return (
                    dict(entries)
                    if isinstance(item, dict)
                    else [child for _, child in entries]
                )
            return item

        # pylint: enable=cell-var-from-loop
        projected = visit(value, "")
        result = {
            "value": projected,
            "partial": bool(omitted),
            "omittedPointers": omitted[:128],
            "omittedPointerCount": len(omitted),
        }
        if json_bytes(result) <= max_bytes:
            return result
    return {
        "value": None,
        "partial": True,
        "omittedPointers": [""],
        "note": "Value exceeds this page; read a narrower JSON pointer.",
    }


def project_snapshot_view(
    payload: Mapping[str, Any],
    *,
    max_bytes: int = PROJECT_VIEW_BYTES,
) -> dict[str, Any]:
    """Drop frozen timeline bodies and bound the latest snapshot as well.

    The validated Project and the observed CAS base stay complete on disk.
    View metadata lives outside Project, so it cannot be mistaken for schema.
    """
    result = deepcopy(dict(payload))
    project = result.get("project")
    if not isinstance(project, dict):
        return result
    previous = result.get("projectView") or {}
    history = list(previous.get("historyTimelines") or [])
    timelines = project.get("timelines")
    if isinstance(timelines, dict) and isinstance(
        timelines.get("items"),
        dict,
    ):
        for timeline_id, timeline in list(timelines["items"].items()):
            if is_snapshot_timeline_id(timeline_id):
                history.append(
                    {
                        "timelineId": timeline_id,
                        "name": timeline.get("name", ""),
                    },
                )
                del timelines["items"][timeline_id]
        if isinstance(timelines.get("order"), list):
            timelines["order"] = [
                tid
                for tid in timelines["order"]
                if not is_snapshot_timeline_id(tid)
            ]
    if not history and json_bytes(result) <= max_bytes:
        return result
    result["projectView"] = {
        "partial": True,
        "historyTimelines": history[:32],
        "historyTimelineCount": previous.get(
            "historyTimelineCount",
            len(history),
        ),
        "omittedPointers": previous.get("omittedPointers") or [],
        "note": (
            "Model view only. Frozen history is indexed, not materialized. "
            "Read omitted values with "
            "read_project(pointer, offset, maxBytes). "
            "Never replace a whole collection from this partial view; "
            "patch stable ID paths. Runtime jq/patch use the complete Project."
        ),
    }
    # Most real projects fit once frozen copies leave. Keep their live
    # content exactly, instead of truncating it to an arbitrary half-budget.
    if json_bytes(result) <= max_bytes:
        return result
    if json_bytes(result["projectView"]) > max_bytes // 4:
        result["projectView"]["historyTimelines"] = []
        result["projectView"]["omittedPointers"] = [""]
    envelope = {
        key: value for key, value in result.items() if key != "project"
    }
    remaining = max_bytes - json_bytes(envelope) - 512
    projected = bounded_json_view(
        project,
        max_bytes=max(max_bytes // 4, remaining),
    )
    result["project"] = projected["value"]
    if not isinstance(result["project"], dict):
        result["project"] = {}
    result["project"].update(
        {
            "project_id": project.get("project_id"),
            "generation": project.get("generation"),
        },
    )
    result["projectView"]["omittedPointers"] = list(
        dict.fromkeys(
            [
                *result["projectView"]["omittedPointers"],
                *projected["omittedPointers"],
            ],
        ),
    )[:128]
    if json_bytes(result) > max_bytes:
        # Large advisories/changed-pointer lists must not bypass the bound.
        result = {
            key: result[key]
            for key in (
                "project",
                "generation",
                "etag",
                "projectView",
                "transactionId",
                "reviewId",
            )
            if key in result
        }
    if json_bytes(result) > max_bytes:
        # Even names/JSON keys in metadata can be large. Fall back to a
        # paged root read rather than letting the index defeat the bound.
        result["projectView"]["historyTimelines"] = []
        result["projectView"]["omittedPointers"] = [""]
    if json_bytes(result) > max_bytes:
        result["project"] = {
            "project_id": project.get("project_id"),
            "generation": project.get("generation"),
        }
    return result
