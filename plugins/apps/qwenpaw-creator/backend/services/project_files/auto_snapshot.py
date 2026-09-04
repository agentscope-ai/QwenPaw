# -*- coding: utf-8 -*-
"""Auto-snapshot timelines before significant agent modifications.

When the agent is about to commit changes that alter timeline elements
(add/remove/modify), this module creates a versioned copy of the affected
timeline so the user can compare and roll back.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any

from .json_pointer import diff_json

_SNAPSHOT_PREFIX = "snapshot:"
_ELEMENT_POINTER_RE = re.compile(
    r"^/timelines/items/([^/]+)/elements_by_id/",
)


def _timeline_element_changes(
    base_data: dict[str, Any],
    candidate_data: dict[str, Any],
) -> set[str]:
    """Return timeline IDs with element changes between base and candidate."""
    changed_ids: set[str] = set()
    for change in diff_json(base_data, candidate_data):
        pointer = change.pointer or ""
        match = _ELEMENT_POINTER_RE.match(pointer)
        if match:
            changed_ids.add(match.group(1))
    return changed_ids


def _next_snapshot_id(
    timelines_items: dict[str, Any],
    timeline_id: str,
) -> str:
    # Max suffix + 1, not count + 1: snapshots are deletable, and a count
    # after deleting an early snapshot would collide with a surviving id.
    prefix = f"{_SNAPSHOT_PREFIX}{timeline_id}:"
    highest = 0
    for key in timelines_items:
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix) :]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{prefix}{highest + 1}"


def _remap_element_id(element_id: str, snapshot_id: str) -> str:
    """Prefix element ID with snapshot ID to ensure uniqueness."""
    return f"{snapshot_id}:{element_id}"


def _remap_slot_id(slot_id: str, snapshot_id: str) -> str:
    """Remap slot IDs referencing elements (e.g., element:r2v-1:storyboard)."""
    if slot_id.startswith("element:"):
        parts = slot_id.split(":", 2)
        if len(parts) >= 2:
            return f"element:{_remap_element_id(parts[1], snapshot_id)}" + (
                f":{parts[2]}" if len(parts) == 3 else ""
            )
    return slot_id


def _remap_snapshot_elements(
    snapshot_timeline: dict[str, Any],
    snapshot_id: str,
) -> None:
    """Remap element IDs in snapshot to avoid cross-timeline duplicates."""
    elements_by_id = snapshot_timeline.get("elements_by_id", {})

    remapped_elements = {}
    for old_id, element in elements_by_id.items():
        new_id = _remap_element_id(old_id, snapshot_id)
        element["element_id"] = new_id

        # Remap outputs slot_ids
        outputs = element.get("outputs", {})
        for output in outputs.values():
            if "slot_id" in output:
                output["slot_id"] = _remap_slot_id(
                    output["slot_id"],
                    snapshot_id,
                )

        # Remap render_source element references
        render_source = element.get("render_source")
        if render_source and render_source.get("type") == "element_output":
            if "element_id" in render_source:
                render_source["element_id"] = _remap_element_id(
                    render_source["element_id"],
                    snapshot_id,
                )

        # Remap transition element references
        creation = element.get("creation", {})
        if creation.get("type") == "transition":
            if "from_element_id" in creation:
                creation["from_element_id"] = _remap_element_id(
                    creation["from_element_id"],
                    snapshot_id,
                )
            if "to_element_id" in creation:
                creation["to_element_id"] = _remap_element_id(
                    creation["to_element_id"],
                    snapshot_id,
                )

        remapped_elements[new_id] = element

    snapshot_timeline["elements_by_id"] = remapped_elements

    # Remap scene ledger element_ids in edit_plan
    edit_plan = snapshot_timeline.get("edit_plan")
    if edit_plan and "scene_ledger" in edit_plan:
        for row in edit_plan["scene_ledger"]:
            if "element_ids" in row:
                row["element_ids"] = [
                    _remap_element_id(eid, snapshot_id)
                    for eid in row["element_ids"]
                ]


_AUTO_SNAPSHOT_DESCRIPTION = "自动快照：修改前的时间轴副本"
_SNAPSHOT_STAMP_FORMAT = "%Y-%m-%d %H:%M"
_AUTO_SNAPSHOT_DEDUPE_WINDOW_SECONDS = 10 * 60


def _latest_auto_snapshot_age_seconds(
    timelines_items: dict[str, Any],
    timeline_id: str,
    now: datetime,
) -> float | None:
    """Age of the newest auto-snapshot of *timeline_id*, or None."""
    latest: datetime | None = None
    prefix = f"{_SNAPSHOT_PREFIX}{timeline_id}:"
    for key, timeline in timelines_items.items():
        if not key.startswith(prefix):
            continue
        if not str(timeline.get("description", "")).startswith("自动快照"):
            continue
        stamp = str(timeline.get("name", ""))[-16:]
        try:
            created = datetime.strptime(stamp, _SNAPSHOT_STAMP_FORMAT)
        except ValueError:
            continue
        if latest is None or created > latest:
            latest = created
    if latest is None:
        return None
    return (now - latest).total_seconds()


def auto_snapshot_timelines(
    base_data: dict[str, Any],
    candidate_data: dict[str, Any],
) -> None:
    """Inject snapshot timelines into *candidate_data* for changed timelines.

    Mutates *candidate_data* in place. For each timeline whose elements
    changed between *base_data* and *candidate_data*, a frozen copy of the
    **base** (pre-change) timeline is inserted into the candidate with a
    versioned name, so the user can compare against and roll back to the
    state before the modification. The live timeline keeps the candidate's
    edits — the user always modifies the live timeline, never a snapshot.

    Only fires when elements are added, removed, or modified inside
    ``elements_by_id``.  Timeline-level property changes (name, description,
    order) do not trigger a snapshot, and a timeline whose newest
    auto-snapshot is younger than ten minutes is not snapshotted again, so
    an editing session leaves one pre-session baseline instead of one
    snapshot per commit.
    """
    changed_ids = _timeline_element_changes(base_data, candidate_data)
    if not changed_ids:
        return

    candidate_timelines = candidate_data.setdefault(
        "timelines",
        {"items": {}, "order": []},
    )
    candidate_items = candidate_timelines.setdefault("items", {})
    candidate_order = candidate_timelines.setdefault("order", [])

    base_timelines = base_data.get("timelines", {})
    base_items = base_timelines.get("items", {})

    # Local time on purpose: the frontend stamps manual snapshots with the
    # user's local clock, and the panel shows both side by side.
    now = datetime.now()
    stamp = now.strftime(_SNAPSHOT_STAMP_FORMAT)

    for timeline_id in sorted(changed_ids):
        base_timeline = base_items.get(timeline_id)
        if base_timeline is None:
            continue
        elements = base_timeline.get("elements_by_id", {})
        if not elements:
            continue
        age = _latest_auto_snapshot_age_seconds(
            candidate_items,
            timeline_id,
            now,
        )
        if age is not None and age < _AUTO_SNAPSHOT_DEDUPE_WINDOW_SECONDS:
            continue

        snapshot_id = _next_snapshot_id(candidate_items, timeline_id)
        # Internal ids like "timeline:main" must never surface to users.
        original_name = (
            base_timeline.get("name") or base_timeline.get("title") or "时间线"
        )
        snapshot_name = f"快照 · {original_name} · {stamp}"

        snapshot_timeline = copy.deepcopy(base_timeline)
        snapshot_timeline["timeline_id"] = snapshot_id
        snapshot_timeline["name"] = snapshot_name
        snapshot_timeline["description"] = _AUTO_SNAPSHOT_DESCRIPTION
        _remap_snapshot_elements(snapshot_timeline, snapshot_id)

        candidate_items[snapshot_id] = snapshot_timeline
        if snapshot_id not in candidate_order:
            candidate_order.append(snapshot_id)
