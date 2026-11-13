# -*- coding: utf-8 -*-
"""Deterministic pre-validation normalization of jq_project candidates.

Models repeatedly emit harmless *identity echoes*: denormalized id fields
inside EntityCollection items whose value merely repeats the collection key
or the owning parent's id (for example ``entityId`` inside a VisualVariant).
StrictModel rejects them as ``extra_forbidden``, costing one full recovery
turn even though the payload carries zero new information.

This layer strips such echoes deterministically before schema validation.
Admission criteria for every rule — all four must hold:

1. Provably zero information loss: the stripped value must be derivable
   from the candidate itself (equal to the collection key or parent id).
   On any mismatch the field is left intact so validation reports it.
2. Grounded in observed model behavior from real session traces.
3. Deterministic: pure structural comparison, never guessing or coercion.
   Value rewrites and structural repair are out of scope by design.
4. Receipted: every strip is reported as a JSON Pointer so the tool result
   tells the model what was removed, and rule hit-rates stay observable.
"""

from __future__ import annotations

from typing import Any


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _strip_identity_echoes(
    item: Any,
    echoes: dict[str, str],
    pointer_prefix: str,
    receipts: list[str],
) -> None:
    """Remove echo keys whose value equals the expected identity."""

    if not isinstance(item, dict):
        return
    for key, expected in echoes.items():
        if key in item and item[key] == expected:
            del item[key]
            receipts.append(f"{pointer_prefix}/{_escape_pointer_token(key)}")


def _collection_items(node: Any) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    items = node.get("items")
    return items if isinstance(items, dict) else {}


def _span_intersects(start1: int, dur1: int, start2: int, dur2: int) -> bool:
    """Check if two spans [start, start+dur) intersect."""
    return start1 < start2 + dur2 and start2 < start1 + dur1


def _is_overlay_element(element: Any) -> bool:
    """Check if an element is an overlay (creation.type == 'overlay')."""
    if not isinstance(element, dict):
        return False
    creation = element.get("creation")
    if not isinstance(creation, dict):
        return False
    return creation.get("type") == "overlay"


def _get_element_span(element: Any) -> tuple[int, int] | None:
    """Extract (start_tick, duration_tick) from an element's span."""
    if not isinstance(element, dict):
        return None
    span = element.get("span")
    if not isinstance(span, dict):
        return None
    start = span.get("start_tick")
    dur = span.get("duration_tick")
    if not isinstance(start, int) or not isinstance(dur, int):
        return None
    return (start, dur)


def _extract_overlay_shot_prefix(element_id: str) -> str | None:
    """Extract shot number prefix from overlay element_id.

    Convention: subtitle:XXY:Z → XX (e.g., subtitle:03b:6 → "03")
    Returns None if the pattern doesn't match.
    """
    parts = element_id.split(":")
    if len(parts) >= 2 and parts[0] in ("subtitle", "overlay"):
        middle = parts[1]
        prefix = ""
        for ch in middle:
            if ch.isdigit():
                prefix += ch
            else:
                break
        return prefix if prefix else None
    return None


def _collect_shot_candidates(
    elements: dict[str, Any],
) -> tuple[list[tuple[str, int, int]], dict[str, tuple[str, int, int]]]:
    """Collect non-overlay elements as shot candidates.

    Returns (shot_candidates, shot_by_prefix) where shot_by_prefix maps
    shot number prefixes to their info.
    """
    shot_candidates: list[tuple[str, int, int]] = []
    shot_by_prefix: dict[str, tuple[str, int, int]] = {}
    for elem_id, elem in elements.items():
        if _is_overlay_element(elem):
            continue
        span_info = _get_element_span(elem)
        if span_info is None:
            continue
        shot_info = (elem_id, span_info[0], span_info[1])
        shot_candidates.append(shot_info)
        parts = elem_id.split(":")
        if len(parts) >= 2:
            prefix = ""
            for ch in parts[1]:
                if ch.isdigit():
                    prefix += ch
                else:
                    break
            if prefix:
                shot_by_prefix[prefix] = shot_info
    return shot_candidates, shot_by_prefix


def _find_target_shot_for_overlay(
    elem_id: str,
    overlay_span: tuple[int, int],
    shot_candidates: list[tuple[str, int, int]],
    shot_by_prefix: dict[str, tuple[str, int, int]],
) -> tuple[str, int, int] | None:
    """Find the target shot for an overlay element.

    Uses prefix matching first, then falls back to fitting heuristic.
    Returns None if no unambiguous match is found.
    """
    ov_start, ov_dur = overlay_span
    ov_end = ov_start + ov_dur

    overlay_prefix = _extract_overlay_shot_prefix(elem_id)
    if overlay_prefix and overlay_prefix in shot_by_prefix:
        shot_info = shot_by_prefix[overlay_prefix]
        _shot_id, shot_start, shot_dur = shot_info
        if ov_start >= 0 and ov_end <= shot_dur:
            corrected_start = ov_start + shot_start
            if _span_intersects(corrected_start, ov_dur, shot_start, shot_dur):
                return shot_info

    fitting_shots: list[tuple[str, int, int]] = []
    for shot_info in shot_candidates:
        _shot_id, shot_start, shot_dur = shot_info
        if ov_start >= 0 and ov_end <= shot_dur:
            corrected_start = ov_start + shot_start
            if _span_intersects(corrected_start, ov_dur, shot_start, shot_dur):
                fitting_shots.append(shot_info)
    if len(fitting_shots) == 1:
        return fitting_shots[0]
    return None


def _correct_overlay_ticks_for_timeline(
    timeline_id: str,
    elements: dict[str, Any],
    base_element_ids: set[str],
) -> list[str]:
    """Process a single timeline and correct overlay ticks.

    Returns receipts for all corrections applied.
    """
    receipts: list[str] = []
    shot_candidates, shot_by_prefix = _collect_shot_candidates(elements)
    if not shot_candidates:
        return receipts

    for elem_id, elem in elements.items():
        if elem_id in base_element_ids:
            continue
        if not _is_overlay_element(elem):
            continue
        overlay_span = _get_element_span(elem)
        if overlay_span is None:
            continue

        target_shot = _find_target_shot_for_overlay(
            elem_id,
            overlay_span,
            shot_candidates,
            shot_by_prefix,
        )
        if target_shot is None:
            continue

        shot_id, shot_start, _shot_dur = target_shot
        elem["span"]["start_tick"] = overlay_span[0] + shot_start
        element_pointer = (
            f"/timelines/items/{_escape_pointer_token(timeline_id)}"
            f"/elements_by_id/{_escape_pointer_token(elem_id)}"
            f"/span/start_tick"
        )
        receipts.append(
            f"{element_pointer} (corrected local→global: "
            f"+{shot_start} via {shot_id})",
        )
    return receipts


def correct_overlay_local_ticks(
    candidate: Any,
    base: Any | None = None,
) -> list[str]:
    """Detect and correct overlay elements with shot-local tick values.

    The AI editing director sometimes writes overlay span.start_tick as a
    shot-relative offset instead of an absolute global timeline tick. This
    function detects such cases and applies the correct offset.

    Detection uses two signals:
    1. Element ID prefix matching (e.g., subtitle:03b:6 → shot:03)
    2. "Fits locally" heuristic (overlay ticks fit within shot duration)

    Correction is applied only when both signals agree on a single target.

    Returns JSON Pointer receipts for all corrections applied.
    """
    receipts: list[str] = []
    if not isinstance(candidate, dict):
        return receipts

    base_elements_by_timeline: dict[str, set[str]] = {}
    if isinstance(base, dict):
        base_timelines = _collection_items(base.get("timelines"))
        for timeline_id, base_timeline in base_timelines.items():
            base_elements = base_timeline.get("elements_by_id")
            if isinstance(base_elements, dict):
                base_elements_by_timeline[timeline_id] = set(
                    base_elements.keys(),
                )

    timelines = _collection_items(candidate.get("timelines"))
    for timeline_id, timeline in timelines.items():
        if not isinstance(timeline, dict):
            continue
        elements = timeline.get("elements_by_id")
        if not isinstance(elements, dict):
            continue

        base_element_ids = base_elements_by_timeline.get(timeline_id, set())
        receipts.extend(
            _correct_overlay_ticks_for_timeline(
                timeline_id,
                elements,
                base_element_ids,
            ),
        )

    return receipts


def normalize_project_candidate(
    candidate: Any,
    base: Any | None = None,
) -> list[str]:
    """Strip redundant identity echoes from a jq output candidate in place.

    Returns the JSON Pointers of every removed field. The candidate is the
    throwaway dict produced by the jq transform; mutation never touches the
    cached base snapshot.
    """

    receipts: list[str] = []
    if not isinstance(candidate, dict):
        return receipts

    visual = candidate.get("visual")
    entities = _collection_items(
        visual.get("entities") if isinstance(visual, dict) else None,
    )
    for entity_id, entity in entities.items():
        entity_pointer = (
            f"/visual/entities/items/{_escape_pointer_token(entity_id)}"
        )
        # ``entity_id`` is a real schema field here; only the camelCase
        # echo is a strippable duplicate.
        _strip_identity_echoes(
            entity,
            {"entityId": entity_id},
            entity_pointer,
            receipts,
        )
        if not isinstance(entity, dict):
            continue
        for variant_id, variant in _collection_items(
            entity.get("variants"),
        ).items():
            _strip_identity_echoes(
                variant,
                {
                    # Observed: models label each variant with its owner.
                    "entityId": entity_id,
                    "entity_id": entity_id,
                    # ``variant_id`` is the real field; only the camelCase
                    # echo of the collection key is redundant.
                    "variantId": variant_id,
                },
                f"{entity_pointer}/variants/items/"
                f"{_escape_pointer_token(variant_id)}",
                receipts,
            )

    timelines = _collection_items(candidate.get("timelines"))
    for timeline_id, timeline in timelines.items():
        timeline_pointer = (
            f"/timelines/items/{_escape_pointer_token(timeline_id)}"
        )
        _strip_identity_echoes(
            timeline,
            {"timelineId": timeline_id},
            timeline_pointer,
            receipts,
        )
        if not isinstance(timeline, dict):
            continue
        elements = timeline.get("elements_by_id")
        if not isinstance(elements, dict):
            continue
        # Observed: models generalize the EntityCollection items/order
        # convention onto Timeline, whose ``elements_by_id`` is a plain
        # dict. When the extra ``order`` is exactly the key set it is a
        # collection-level identity echo — element ordering carries no
        # schema meaning (rendering is decided by start_tick) — so
        # stripping loses nothing. Any other value stays for validation.
        order = timeline.get("order")
        if (
            isinstance(order, list)
            and all(isinstance(item, str) for item in order)
            and set(order) == set(elements)
        ):
            del timeline["order"]
            receipts.append(f"{timeline_pointer}/order")
        for element_id, element in elements.items():
            element_pointer = (
                f"{timeline_pointer}/elements_by_id/"
                f"{_escape_pointer_token(element_id)}"
            )
            _strip_identity_echoes(
                element,
                {"elementId": element_id},
                element_pointer,
                receipts,
            )

    tick_correction_receipts = correct_overlay_local_ticks(candidate, base)
    receipts.extend(tick_correction_receipts)

    return receipts


__all__ = ["normalize_project_candidate", "correct_overlay_local_ticks"]
