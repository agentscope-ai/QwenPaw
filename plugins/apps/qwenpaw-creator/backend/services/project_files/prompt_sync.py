# -*- coding: utf-8 -*-
"""Durable creative-input provenance for R2V prompt synchronization.

No model calls or file writes live here. Legacy documents stay untracked until
an actual edit; saved media requests are never reinterpreted by this contract.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from domain.errors import ConflictError, NotFoundError, ValidationError

from .json_pointer import split_pointer

_PLAN_FIELDS = (
    "intent",
    "narrative",
    "continuity",
    "character_refs",
    "scene_ref",
    "prop_refs",
    "visual_variant_refs",
    "cast_lineup_refs",
    "storyboard_reference_version_ids",
    "video_reference_version_ids",
)
_PROMPTS = ("storyboard_prompt", "video_prompt")


def is_prompt_sync_pointer(pointer: str) -> bool:
    """Identify derived provenance without matching similarly named content."""
    tokens = split_pointer(pointer)
    return (
        len(tokens) >= 7
        and tokens[:2] == ("timelines", "items")
        and tokens[3] == "elements_by_id"
        and tokens[5:7] == ("creation", "prompt_sync")
    )


def _json(value: Any) -> Any:
    return (
        value.model_dump(mode="json")
        if hasattr(value, "model_dump")
        else value
    )


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
    ).hexdigest()


def live_element(
    document: Mapping[str, Any],
    timeline_id: str,
    element_id: str,
):
    if timeline_id.startswith("snapshot:") or element_id.startswith(
        "snapshot:",
    ):
        raise ValidationError("历史快照只能查看，不能更新提示词")
    timeline = document.get("timelines", {}).get("items", {}).get(timeline_id)
    element = (timeline or {}).get("elements_by_id", {}).get(element_id)
    if not element:
        raise NotFoundError("镜头不存在")
    if element.get("creation", {}).get("type") != "r2v":
        raise ValidationError("仅参考生视频镜头支持提示词同步")
    return timeline, element


def plan_input(
    document: Mapping[str, Any],
    timeline_id: str,
    element_id: str,
) -> dict:
    timeline, element = live_element(document, timeline_id, element_id)
    creation = element["creation"]
    settings = document.get("settings", {})
    return {
        "creation": {key: creation.get(key) for key in _PLAN_FIELDS},
        "durationTick": element.get("span", {}).get("duration_tick"),
        "ticksPerSecond": timeline.get("ticks_per_second"),
        "aspectRatio": settings.get("aspect_ratio"),
        "resolution": settings.get("resolution"),
    }


def sync_stamp(
    document: Mapping[str, Any],
    timeline_id: str,
    element_id: str,
) -> dict:
    _, element = live_element(document, timeline_id, element_id)
    creation = element["creation"]
    return {
        "contract_version": 2,
        "plan_fingerprint": digest(
            plan_input(document, timeline_id, element_id),
        ),
        **{
            f"{field}_fingerprint": digest(creation.get(field, ""))
            for field in _PROMPTS
        },
    }


def prompt_sync_status(
    project: Any,
    timeline_id: str,
    element_id: str,
) -> dict:
    document = _json(project)
    _, element = live_element(document, timeline_id, element_id)
    creation = element["creation"]
    current = sync_stamp(document, timeline_id, element_id)
    previous = creation.get("prompt_sync")
    status, reason = "legacy", "untracked"
    changed = []
    if previous and previous.get("contract_version") == 2:
        changed = [key for key in current if current[key] != previous.get(key)]
        if not changed:
            status, reason = "current", "aligned"
        elif "plan_fingerprint" in changed and not all(
            f"{field}_fingerprint" in changed for field in _PROMPTS
        ):
            status, reason = "needs_update", "plan_changed"
        else:
            status, reason = "needs_confirmation", "prompts_edited"
    return {
        "status": status,
        "reason": reason,
        "changedSources": [
            source
            for key, source in (
                ("plan_fingerprint", "currentPlan"),
                ("storyboard_prompt_fingerprint", "storyboardPrompt"),
                ("video_prompt_fingerprint", "videoPrompt"),
            )
            if key in changed
        ],
        "suggestedSource": (
            "mixed"
            if len(changed) > 1
            else (
                {
                    "plan_fingerprint": "currentPlan",
                    "storyboard_prompt_fingerprint": "storyboardPrompt",
                    "video_prompt_fingerprint": "videoPrompt",
                }.get(changed[0])
                if changed
                else None
            )
        ),
        "baselineToken": digest(
            {
                "projectId": document.get("project_id"),
                "projectCreatedAt": document.get("created_at"),
                "timelineId": timeline_id,
                "elementId": element_id,
                **current,
            },
        ),
    }


def assert_r2v_prompt_sync(
    project: Any,
    timeline_id: str,
    element_id: str,
) -> None:
    status = prompt_sync_status(project, timeline_id, element_id)["status"]
    if status == "needs_update":
        raise ValidationError("片段内容已修改，请先同步分镜图和视频提示词")
    if status == "needs_confirmation":
        raise ValidationError("提示词已修改，请先同步片段内容和另一份提示词")


def _only_redundant_storyboard_refs_changed(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    timeline_id: str,
    element_id: str,
) -> bool:
    """Recognize explicit own-storyboard bookkeeping, not creative edits.

    Callers may refresh provenance only from an already-current baseline.
    Compare raw external references exactly, including duplicates and order;
    never
    turn an explicit list into the automatic-reference fallback here.
    """
    _, old_element = live_element(before, timeline_id, element_id)
    if old_element["creation"].get("prompt_sync") != sync_stamp(
        before,
        timeline_id,
        element_id,
    ):
        return False
    plans = []
    creations = []
    external_refs = []
    bindings = []
    raw_refs = []
    for document in (before, after):
        _, element = live_element(document, timeline_id, element_id)
        creation = element["creation"]
        refs = creation.get("video_reference_version_ids")
        if (
            not isinstance(refs, list)
            or not refs
            or not all(isinstance(ref, str) for ref in refs)
        ):
            return False
        output = element.get("outputs", {}).get("storyboard") or {}
        slot_id = output.get("slot_id")
        assets = document.get("assets", {})
        slot = assets.get("artifact_slots_by_id", {}).get(slot_id) or {}
        selected = slot.get("selected_version_id")
        if (
            not slot_id
            or not selected
            or slot.get("owner_ref") != f"element:{element_id}"
            or slot.get("kind") != "r2v_storyboard_image"
        ):
            return False
        own_versions = set(slot.get("version_ids") or ())
        own_versions.update(
            version_id
            for version_id, artifact in assets.get(
                "artifact_versions_by_id",
                {},
            ).items()
            if artifact.get("slot_id") == slot_id
        )
        own_versions.add(selected)
        bindings.append((slot_id, selected))
        raw_refs.append(refs)
        external_refs.append([ref for ref in refs if ref not in own_versions])
        creations.append(
            {
                key: value
                for key, value in creation.items()
                if key not in {"video_reference_version_ids", "prompt_sync"}
            },
        )
        plan = plan_input(document, timeline_id, element_id)
        plan["creation"].pop("video_reference_version_ids", None)
        plans.append(plan)
    return (
        raw_refs[0] != raw_refs[1]
        and bindings[0] == bindings[1]
        and external_refs[0] == external_refs[1]
        and creations[0] == creations[1]
        and plans[0] == plans[1]
    )


def derive_prompt_sync_changes(
    before: Mapping[str, Any],
    after: dict[str, Any],
    *,
    confirmation: tuple[str, str, str] | None = None,
    changed_pointers: Iterable[str] | None = None,
) -> None:
    """Called under the Project CAS lock for every writer, including agents.

    Ordinary writes cannot forge provenance. Only a validated service accept
    can stamp new provenance, and its read baseline is checked under that lock.
    """
    if confirmation:
        timeline_id, element_id, token = confirmation
        if (
            prompt_sync_status(before, timeline_id, element_id)[
                "baselineToken"
            ]
            != token
        ):
            raise ConflictError("片段内容或提示词已更新，请按最新内容重新生成")
    paths = (
        [split_pointer(pointer) for pointer in changed_pointers]
        if changed_pointers is not None
        else None
    )

    def affected(timeline_id: str, element_id: str) -> bool:
        if paths is None or (
            confirmation and confirmation[:2] == (timeline_id, element_id)
        ):
            return True
        roots = (
            ("settings", "aspect_ratio"),
            ("settings", "resolution"),
            ("timelines", "items", timeline_id, "ticks_per_second"),
            ("timelines", "items", timeline_id, "elements_by_id", element_id),
        )
        return any(
            path[: len(root)] == root or root[: len(path)] == path
            for path in paths
            for root in roots
        )

    old_timelines = before.get("timelines", {}).get("items", {})
    for timeline_id, timeline in (
        after.get("timelines", {}).get("items", {}).items()
    ):
        if timeline_id.startswith("snapshot:"):
            continue
        for element_id, element in timeline.get("elements_by_id", {}).items():
            creation = element.get("creation", {})
            if (
                not affected(timeline_id, element_id)
                or element_id.startswith("snapshot:")
                or creation.get("type") != "r2v"
            ):
                continue
            old = (
                old_timelines.get(timeline_id, {})
                .get("elements_by_id", {})
                .get(element_id)
            )
            if not old or old.get("creation", {}).get("type") != "r2v":
                creation["prompt_sync"] = None
                continue
            old_sync = old["creation"].get("prompt_sync")
            if confirmation and confirmation[:2] == (timeline_id, element_id):
                creation["prompt_sync"] = sync_stamp(
                    after,
                    timeline_id,
                    element_id,
                )
            elif (
                old_sync
                and old["creation"].get("video_reference_version_ids")
                != creation.get("video_reference_version_ids")
                and _only_redundant_storyboard_refs_changed(
                    before,
                    after,
                    timeline_id,
                    element_id,
                )
            ):
                creation["prompt_sync"] = sync_stamp(
                    after,
                    timeline_id,
                    element_id,
                )
            elif old_sync:
                creation["prompt_sync"] = old_sync
            elif sync_stamp(before, timeline_id, element_id) != sync_stamp(
                after,
                timeline_id,
                element_id,
            ):
                creation["prompt_sync"] = sync_stamp(
                    before,
                    timeline_id,
                    element_id,
                )
            else:
                creation["prompt_sync"] = None
