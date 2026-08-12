# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Deterministic, in-memory migrations for ``project.json`` documents.

Schema migrations are intentionally separate from Project content commits.
They upgrade an older raw document before Pydantic validation; persisting the
upgraded form still has to go through the normal Project commit boundary.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from utils.logger import setup_logger

from .models import CURRENT_PROJECT_SCHEMA_VERSION


class ProjectMigrationError(ValueError):
    """The raw Project cannot be upgraded without losing authority."""


ProjectMigration = Callable[[dict[str, Any]], dict[str, Any]]


# A migration registered under N must return exactly schema_version N + 1.
logger = setup_logger("creator.project_files.migrations")

PROJECT_MIGRATIONS: dict[int, ProjectMigration] = {}


def _visual_entity_refs(creation: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for value in creation.get("character_refs", []):
        if isinstance(value, str) and value not in refs:
            refs.append(value)
    scene_ref = creation.get("scene_ref")
    if isinstance(scene_ref, str) and scene_ref not in refs:
        refs.append(scene_ref)
    for value in creation.get("prop_refs", []):
        if isinstance(value, str) and value not in refs:
            refs.append(value)
    return refs


def _artifact_variant_id(
    artifact: Mapping[str, Any] | None,
) -> str | None:
    if not isinstance(artifact, Mapping):
        return None
    metadata = artifact.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    variant_id = metadata.get("variantId")
    return variant_id if isinstance(variant_id, str) and variant_id else None


def _artifact_belongs_to_entity(
    artifact: object,
    entity_id: str,
) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    owner_ref = artifact.get("owner_ref")
    if owner_ref is None:
        return True
    if not isinstance(owner_ref, str):
        return False
    for prefix in ("visual-entity:", "asset:"):
        if owner_ref.startswith(prefix):
            owner_ref = owner_ref.removeprefix(prefix)
            break
    return owner_ref == entity_id


def _dict_field(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    candidate = value.get(field)
    return candidate if isinstance(candidate, dict) else {}


def _visual_entities(document: Mapping[str, Any]) -> dict[str, Any]:
    visual = _dict_field(document, "visual")
    return _dict_field(_dict_field(visual, "entities"), "items")


def _artifact_versions(document: Mapping[str, Any]) -> dict[str, Any]:
    return _dict_field(
        _dict_field(document, "assets"),
        "artifact_versions_by_id",
    )


def _generated_ids(variant: object) -> list[str]:
    if not isinstance(variant, Mapping):
        return []
    generated = variant.get("generated_artifact_version_ids")
    if not isinstance(generated, list):
        return []
    return [item for item in generated if isinstance(item, str)]


def _version_belongs_to_variant(
    version_id: str,
    entity_id: str,
    variant_id: str,
    artifacts: Mapping[str, Any],
    memberships: Mapping[str, int],
) -> bool:
    artifact = artifacts.get(version_id)
    if not _artifact_belongs_to_entity(artifact, entity_id):
        return False
    recorded_variant = _artifact_variant_id(artifact)
    return recorded_variant == variant_id or (
        recorded_variant is None and memberships.get(version_id) == 1
    )


def _migrate_variant_selections(
    entities: Mapping[str, Any],
    artifacts: Mapping[str, Any],
) -> None:
    for entity_id, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        variants = _dict_field(_dict_field(entity, "variants"), "items")
        memberships: dict[str, int] = {}
        for variant in variants.values():
            for version_id in _generated_ids(variant):
                memberships[version_id] = memberships.get(version_id, 0) + 1
        entity_selected = entity.get("selected_artifact_version_id")
        for variant_id, variant in variants.items():
            if not isinstance(variant, dict):
                continue
            generated_ids = [
                version_id
                for version_id in _generated_ids(variant)
                if _version_belongs_to_variant(
                    version_id,
                    entity_id,
                    variant_id,
                    artifacts,
                    memberships,
                )
            ]
            selected: str | None = None
            if (
                isinstance(entity_selected, str)
                and entity_selected in generated_ids
            ):
                selected = entity_selected
            elif generated_ids:
                selected = generated_ids[-1]
            variant["selected_artifact_version_id"] = selected
        if len(variants) > 1:
            # Schema v3 resolves multi-Variant entities only through an
            # Element binding and the Variant-level selected pointer.
            entity["selected_artifact_version_id"] = None


def _r2v_creations(document: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    timelines = _dict_field(_dict_field(document, "timelines"), "items")
    for timeline in timelines.values():
        elements = _dict_field(timeline, "elements_by_id")
        for element in elements.values():
            creation = _dict_field(element, "creation")
            if creation.get("type") == "r2v":
                yield creation


def _exact_visual_reference_ids(creation: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for field in (
        "storyboard_reference_version_ids",
        "video_reference_version_ids",
    ):
        values = creation.get(field)
        if not isinstance(values, list):
            continue
        refs.extend(value for value in values if isinstance(value, str))
    return list(dict.fromkeys(refs))


def _ordered_variants(
    entity: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    collection = _dict_field(entity, "variants")
    variants = _dict_field(collection, "items")
    order = collection.get("order")
    if not isinstance(order, list):
        return variants, []
    return variants, [
        item for item in order if isinstance(item, str) and item in variants
    ]


def _infer_variant_id(
    entity_id: str,
    entity: object,
    exact_refs: list[str],
    artifacts: Mapping[str, Any],
) -> str | None:
    if not isinstance(entity, Mapping):
        return None
    variants, ordered_ids = _ordered_variants(entity)
    if len(ordered_ids) == 1:
        return ordered_ids[0]
    artifact_variants = {
        version_id: _artifact_variant_id(artifacts.get(version_id))
        for version_id in exact_refs
    }
    candidates = [
        variant_id
        for variant_id in ordered_ids
        if any(
            _artifact_belongs_to_entity(
                artifacts.get(version_id),
                entity_id,
            )
            and (
                version_id in _generated_ids(variants[variant_id])
                or artifact_variants[version_id] == variant_id
            )
            for version_id in exact_refs
        )
    ]
    return candidates[0] if len(candidates) == 1 else None


def _infer_element_bindings(
    creation: Mapping[str, Any],
    entities: Mapping[str, Any],
    artifacts: Mapping[str, Any],
) -> dict[str, str]:
    exact_refs = _exact_visual_reference_ids(creation)
    bindings: dict[str, str] = {}
    for entity_id in _visual_entity_refs(creation):
        variant_id = _infer_variant_id(
            entity_id,
            entities.get(entity_id),
            exact_refs,
            artifacts,
        )
        if variant_id is not None:
            bindings[entity_id] = variant_id
    return bindings


def _migrate_v2_to_v3(document: dict[str, Any]) -> dict[str, Any]:
    """Give every visual Variant its own selection and bind R2V Elements.

    Existing ArtifactVersions remain immutable in their original slots.  A
    Variant selects the entity's former default when it owns that version,
    otherwise its newest unambiguous generated version. Mislabeled or
    multiply assigned legacy versions remain unselected. Element bindings are
    inferred only when exact references identify one Variant (or the entity
    has a single Variant); ambiguous multi-Variant Elements remain unbound so
    the coverage checkpoint can expose them instead of guessing.
    """

    entities = _visual_entities(document)
    artifacts = _artifact_versions(document)
    _migrate_variant_selections(entities, artifacts)

    for creation in _r2v_creations(document):
        creation["visual_variant_refs"] = _infer_element_bindings(
            creation,
            entities,
            artifacts,
        )

    document["schema_version"] = 3
    return document


PROJECT_MIGRATIONS[2] = _migrate_v2_to_v3


def _migrate_v3_to_v4(document: dict[str, Any]) -> dict[str, Any]:
    """Record existing visual Variants as the entity's required set.

    Schema v3 had no separate statement of intended Variant coverage, so the
    migration preserves exactly what is known instead of guessing additional
    states from free text. New plans can declare required IDs before all
    corresponding Variant records have been materialized.
    """

    for entity in _visual_entities(document).values():
        if not isinstance(entity, dict):
            continue
        variants = _dict_field(entity, "variants")
        order = variants.get("order")
        entity["required_variant_ids"] = (
            list(order) if isinstance(order, list) else []
        )
    document["schema_version"] = 4
    return document


PROJECT_MIGRATIONS[3] = _migrate_v3_to_v4


def _migrate_v4_drop_overlay_kind(document: dict[str, Any]) -> dict[str, Any]:
    """v4 -> v5: overlay roles derive from data, not an overlay_kind tag.

    ``pet_os``/``interview_summary`` overlays already carry authoritative
    ``text``; ``motion``/``media`` overlays are text-free.  The interview
    presentation choice is the one fact only the tag carried, so it is
    preserved as ``vibe="summary"`` (the renderer and frontend both key
    interview styling off that value) before the tag is dropped.
    """

    timelines = document.get("timelines")
    items = timelines.get("items") if isinstance(timelines, dict) else None
    if isinstance(items, dict):
        for timeline in items.values():
            if not isinstance(timeline, dict):
                continue
            elements = timeline.get("elements_by_id")
            if not isinstance(elements, dict):
                continue
            for element in elements.values():
                if not isinstance(element, dict):
                    continue
                creation = element.get("creation")
                if (
                    isinstance(creation, dict)
                    and creation.get("type") == "overlay"
                ):
                    kind = creation.pop("overlay_kind", None)
                    if kind == "interview_summary":
                        creation["vibe"] = "summary"
    document["schema_version"] = 5
    return document


PROJECT_MIGRATIONS[4] = _migrate_v4_drop_overlay_kind


def _timeline_elements(
    document: Mapping[str, Any],
) -> Iterator[dict[str, Any]]:
    timelines = _dict_field(_dict_field(document, "timelines"), "items")
    for timeline in timelines.values():
        elements = _dict_field(timeline, "elements_by_id")
        for element in elements.values():
            if isinstance(element, dict):
                yield element


def _selected_slot_version(
    document: Mapping[str, Any],
    element: Mapping[str, Any],
    output_name: str,
) -> str | None:
    outputs = element.get("outputs")
    if not isinstance(outputs, dict):
        return None
    slot_ref = outputs.get(output_name)
    if not isinstance(slot_ref, dict):
        return None
    slot_id = slot_ref.get("slot_id")
    slots = _dict_field(
        _dict_field(document, "assets"),
        "artifact_slots_by_id",
    )
    slot = slots.get(slot_id)
    if not isinstance(slot, dict):
        return None
    selected = slot.get("selected_version_id")
    return selected if isinstance(selected, str) and selected else None


def _migrate_v5_to_v6(document: dict[str, Any]) -> dict[str, Any]:
    """Split mode-tagged r2v creations into their own creation types.

    Schema v4 expressed t2v/i2v/s2v as ``creation.type=r2v`` plus a
    ``generation_mode`` tag, dragging the whole shot/storyboard/reference
    stack along even though those providers never consume it. v5 gives each
    mode a model of exactly what its provider uses; an s2v element's
    selected "storyboard" (its portrait frame) becomes the declared
    portrait reference and the slot mapping is dropped as a non-product.
    """

    for element in _timeline_elements(document):
        creation = _dict_field(element, "creation")
        if creation.get("type") != "r2v":
            continue
        mode = creation.pop("generation_mode", "r2v") or "r2v"
        if mode == "r2v":
            continue
        base = {
            "intent": creation.get("intent") or "",
            "narrative": creation.get("narrative") or "",
            "continuity": creation.get("continuity") or "",
            "video_prompt": creation.get("video_prompt") or "",
            "recipe": creation.get("recipe"),
        }
        if mode == "t2v":
            element["creation"] = {"type": "t2v", **base}
        elif mode == "i2v":
            element["creation"] = {
                "type": "i2v",
                **base,
                "first_frame_version_id": _selected_slot_version(
                    document,
                    element,
                    "storyboard",
                ),
            }
        elif mode == "s2v":
            characters = creation.get("character_refs")
            element["creation"] = {
                "type": "s2v",
                "intent": base["intent"],
                "character_ref": (
                    characters[0]
                    if isinstance(characters, list) and characters
                    else None
                ),
                "portrait_version_id": _selected_slot_version(
                    document,
                    element,
                    "storyboard",
                ),
                "script": "",
                "audio_version_id": None,
                "recipe": creation.get("recipe"),
            }
        if mode in ("t2v", "s2v"):
            # These providers take no storyboard: drop the output mapping
            # (the artifact itself stays addressable in the asset layer).
            outputs = element.get("outputs")
            if isinstance(outputs, dict):
                outputs.pop("storyboard", None)
    document["schema_version"] = 6
    return document


PROJECT_MIGRATIONS[5] = _migrate_v5_to_v6


def _migrate_v6_to_v7(document: dict[str, Any]) -> dict[str, Any]:
    """Introduce the Timeline taste contract (``edit_plan``).

    Existing timelines carry no recorded creative contract, so the
    migration sets an explicit ``null`` instead of inventing one; the
    first editing delegation after the upgrade receives the plan
    advisory and fills it in.
    """

    timelines = document.get("timelines")
    items = timelines.get("items") if isinstance(timelines, dict) else None
    if isinstance(items, dict):
        for timeline in items.values():
            if isinstance(timeline, dict):
                timeline.setdefault("edit_plan", None)
    document["schema_version"] = 7
    return document


PROJECT_MIGRATIONS[6] = _migrate_v6_to_v7


def _migrate_v7_to_v8(document: dict[str, Any]) -> dict[str, Any]:
    """Constrain ``color_grade`` to the named preset vocabulary.

    Earlier schemas accepted any string and the renderer silently skipped
    unknown names, so a free-form colour description meant "no grading".
    The migration makes that outcome explicit by clearing values outside
    the preset list; grading intent must be re-expressed as a preset.
    """

    from .models import COLOR_GRADE_PRESETS

    migrated = dict(document)
    timelines = dict(migrated.get("timelines") or {})
    items = dict(timelines.get("items") or {})
    for timeline_id, timeline in list(items.items()):
        if not isinstance(timeline, Mapping):
            continue
        grade = timeline.get("color_grade")
        if grade and grade not in COLOR_GRADE_PRESETS:
            logger.warning(
                "v7->v8: timeline %s color_grade %r is not a named preset; "
                "cleared (was silently skipped by the renderer anyway)",
                timeline_id,
                str(grade)[:80],
            )
            updated = dict(timeline)
            updated["color_grade"] = ""
            items[timeline_id] = updated
    timelines["items"] = items
    migrated["timelines"] = timelines
    migrated["schema_version"] = 8
    return migrated


PROJECT_MIGRATIONS[7] = _migrate_v7_to_v8


def migrate_project_document(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached document at the current Project schema version.

    Each step is applied to a deep copy and must preserve ``project_id``.  A
    future schema or a missing migration fails closed; unknown fields are left
    for the current strict Pydantic model to reject after migration.
    """

    if not isinstance(raw, Mapping):
        raise ProjectMigrationError("project.json root must be an object")
    document = copy.deepcopy(dict(raw))
    version = document.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProjectMigrationError(
            "project.json schema_version must be an integer",
        )
    if version < 1:
        # Schemas predating the first file-native Project document require an
        # out-of-band one-time conversion. Accepting an unregistered v0
        # document in the Runtime would silently guess at its meaning.
        if version not in PROJECT_MIGRATIONS:
            raise ProjectMigrationError(
                f"no Project migration is registered for schema_version {version}",
            )
    if version > CURRENT_PROJECT_SCHEMA_VERSION:
        raise ProjectMigrationError(
            "project.json was written by a newer schema: "
            f"{version} > {CURRENT_PROJECT_SCHEMA_VERSION}",
        )

    original_project_id = document.get("project_id")
    while version < CURRENT_PROJECT_SCHEMA_VERSION:
        migration = PROJECT_MIGRATIONS.get(version)
        if migration is None:
            raise ProjectMigrationError(
                f"no Project migration is registered for schema_version {version}",
            )
        candidate = migration(copy.deepcopy(document))
        if not isinstance(candidate, dict):
            raise ProjectMigrationError(
                f"Project migration {version} must return one JSON object",
            )
        next_version = candidate.get("schema_version")
        if next_version != version + 1:
            raise ProjectMigrationError(
                f"Project migration {version} must produce schema_version {version + 1}",
            )
        if candidate.get("project_id") != original_project_id:
            raise ProjectMigrationError(
                f"Project migration {version} cannot change project_id",
            )
        document = candidate
        version = next_version
    return document


__all__ = [
    "PROJECT_MIGRATIONS",
    "ProjectMigration",
    "ProjectMigrationError",
    "migrate_project_document",
]
