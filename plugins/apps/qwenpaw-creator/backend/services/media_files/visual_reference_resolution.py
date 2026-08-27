# -*- coding: utf-8 -*-
"""Resolve R2V visual references through Element-to-Variant bindings."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from domain.errors import ValidationError
from services.project_files.models import (
    Project,
    R2VCreation,
    VisualEntity,
)


def _owner_entity_id(owner_ref: str | None) -> str | None:
    if owner_ref is None:
        return None
    for prefix in ("visual-entity:", "asset:"):
        if owner_ref.startswith(prefix):
            return owner_ref.removeprefix(prefix)
    return owner_ref


def _entity_ids(creation: R2VCreation) -> list[str]:
    return list(
        dict.fromkeys(
            [
                *creation.character_refs,
                *(
                    [creation.scene_ref]
                    if creation.scene_ref is not None
                    else []
                ),
                *creation.prop_refs,
            ],
        ),
    )


def _artifact_variant_id(
    project: Project,
    entity: VisualEntity,
    version_id: str,
) -> str | None:
    artifact = project.assets.artifact_versions_by_id.get(version_id)
    if artifact is None:
        return None
    generated_matches = [
        variant_id
        for variant_id in entity.variants.order
        if version_id
        in entity.variants.items[variant_id].generated_artifact_version_ids
    ]
    if (
        _owner_entity_id(artifact.owner_ref) != entity.entity_id
        and not generated_matches
    ):
        return None
    metadata_variant = artifact.metadata.get("variantId")
    if isinstance(metadata_variant, str) and (
        metadata_variant in generated_matches
        or (
            _owner_entity_id(artifact.owner_ref) == entity.entity_id
            and metadata_variant in entity.variants.items
        )
    ):
        return metadata_variant
    return generated_matches[0] if len(generated_matches) == 1 else None


def _resolved_variant_id(
    project: Project,
    creation: R2VCreation,
    entity: VisualEntity,
    explicit_version_ids: Iterable[str],
) -> str | None:
    bound = creation.visual_variant_refs.get(entity.entity_id)
    if bound is not None:
        return bound
    if len(entity.variants.order) == 1:
        return entity.variants.order[0]
    candidates = list(
        dict.fromkeys(
            candidate
            for version_id in explicit_version_ids
            if (
                candidate := _artifact_variant_id(
                    project,
                    entity,
                    version_id,
                )
            )
        ),
    )
    return candidates[0] if len(candidates) == 1 else None


def _lineup_anchor_version_ids(
    project: Project,
    creation: R2VCreation,
) -> list[str]:
    """Selected cast-lineup images referenced by this element.

    The lineup is the group anchor for relative consistency (scale
    ratios, shared style baseline, spatial order), so it must lead the
    reference chain ahead of individual identity anchors. A referenced
    lineup without a generated image contributes nothing yet — the
    element keeps working while visual development catches up.
    """

    anchors: list[str] = []
    for ref in creation.cast_lineup_refs:
        lineup = project.visual.cast_lineups.items.get(ref)
        if lineup is None:
            # Mirrors the entity invariant below: a validated Project
            # cannot reach here, so fail loudly for mutated models.
            raise ValidationError(f"R2V 引用的阵容图不存在: {ref}")
        if lineup.selected_artifact_version_id:
            anchors.append(lineup.selected_artifact_version_id)
    return anchors


def resolve_r2v_visual_reference_version_ids(
    project: Project,
    creation: R2VCreation,
    explicit_version_ids: Iterable[str],
) -> tuple[str, ...]:
    """Return exact references with bound Variant selections first.

    Agent-specified references are authoritative: a non-empty explicit
    list is used exactly as written (deduplicated, order preserved) so
    the planning agent — not a default chain — decides which images
    constrain generation and owns the provider's reference budget. Only
    an element with no explicit references falls back to the automatic
    chain: cast-lineup group anchors lead, then per-entity identity
    anchors. A bound entity never consumes an ArtifactVersion owned by
    another Variant. Ambiguous legacy Elements are left unchanged rather
    than guessed; the Plan coverage checkpoint exposes those missing
    bindings to the user.
    """

    explicit = list(dict.fromkeys(explicit_version_ids))
    if explicit:
        for version_id in explicit:
            for entity_id in _entity_ids(creation):
                entity = project.visual.entities.items.get(entity_id)
                if entity is None:
                    raise ValidationError(
                        f"R2V 视觉引用实体不存在: {entity_id}",
                    )
                bound = creation.visual_variant_refs.get(entity_id)
                if bound is None:
                    continue
                owned_variant = _artifact_variant_id(
                    project,
                    entity,
                    version_id,
                )
                if owned_variant is not None and owned_variant != bound:
                    raise ValidationError(
                        f"显式参考 {version_id} 属于实体 {entity_id} 的 "
                        f"Variant {owned_variant}，与该 Element 绑定的 "
                        f"Variant {bound} 冲突；请改用绑定 Variant 的版本"
                        "或调整 visual_variant_refs",
                    )
        return tuple(explicit)
    selected: list[str] = []
    for entity_id in _entity_ids(creation):
        entity = project.visual.entities.items.get(entity_id)
        if entity is None:
            # A validated Project guarantees this invariant. Keep a controlled
            # failure for callers holding a manually mutated in-memory model;
            # silently skipping would generate without a required identity.
            raise ValidationError(
                f"R2V 视觉引用实体不存在: {entity_id}",
            )
        variant_id = _resolved_variant_id(
            project,
            creation,
            entity,
            (),
        )
        if variant_id is not None:
            version_id = entity.variants.items[
                variant_id
            ].selected_artifact_version_id
        else:
            version_id = (
                entity.selected_artifact_version_id
                if not entity.variants.order
                else None
            )
        if version_id is not None:
            selected.append(version_id)

    lineup_anchors = _lineup_anchor_version_ids(project, creation)
    return tuple(dict.fromkeys([*lineup_anchors, *selected]))


def preview_r2v_reference_order(
    project: Project,
    element_id: str,
) -> dict[str, Any]:
    """Authoritative ``[Image N]`` order preview for one r2v Element.

    Mirrors the submit path exactly (storyboard first, then the resolved
    visual reference chain, deduplicated in order) so the frontend can label
    each reference with the index the video prompt will cite.  Entity
    binding and deduplication reorder references, which makes the order
    impossible to reconstruct client-side from the raw creation fields.
    """

    from services.media_files.element_adapter import (
        find_timeline_element,
        selected_element_output,
    )

    _, element = find_timeline_element(project, element_id)
    creation = element.creation
    if not isinstance(creation, R2VCreation):
        raise ValidationError(
            f"Element creation.type={creation.type} 不使用 [Image N] 参考序列",
        )
    selected_storyboard = selected_element_output(
        project,
        element,
        "storyboard",
    )
    storyboard_id = (
        selected_storyboard[1] if selected_storyboard is not None else None
    )
    version_ids = list(
        dict.fromkeys(
            [
                *([storyboard_id] if storyboard_id else []),
                *resolve_r2v_visual_reference_version_ids(
                    project,
                    creation,
                    creation.video_reference_version_ids,
                ),
            ],
        ),
    )
    references: list[dict[str, Any]] = []
    for index, version_id in enumerate(version_ids, start=1):
        source = project.assets.source_versions_by_id.get(version_id)
        artifact = project.assets.artifact_versions_by_id.get(version_id)
        version = source if source is not None else artifact
        if version_id == storyboard_id:
            kind = "storyboard"
        elif source is not None:
            kind = "source"
        else:
            kind = "artifact"
        references.append(
            {
                "index": index,
                "versionId": version_id,
                "kind": kind,
                "name": (
                    version.name
                    if version is not None and version.name
                    else version_id
                ),
            },
        )
    return {
        "elementId": element_id,
        "storyboardSelected": storyboard_id is not None,
        "references": references,
    }


__all__ = [
    "preview_r2v_reference_order",
    "resolve_r2v_visual_reference_version_ids",
]
