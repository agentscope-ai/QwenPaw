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


def normalize_project_candidate(candidate: Any) -> list[str]:
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
            if not isinstance(element, dict):
                continue
            creation = element.get("creation")
            if not isinstance(creation, dict):
                continue
            for shot_id, shot in _collection_items(
                creation.get("shots"),
            ).items():
                _strip_identity_echoes(
                    shot,
                    {"shotId": shot_id},
                    f"{element_pointer}/creation/shots/items/"
                    f"{_escape_pointer_token(shot_id)}",
                    receipts,
                )

    return receipts


__all__ = ["normalize_project_candidate"]
