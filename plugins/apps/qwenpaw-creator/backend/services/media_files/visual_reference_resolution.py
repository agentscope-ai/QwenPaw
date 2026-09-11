# -*- coding: utf-8 -*-
"""Resolve R2V visual references through Element-to-Variant bindings."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from domain.errors import ValidationError
from services.project_files.models import (
    Project,
    R2VCreation,
    TimelineElement,
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
    """Return the stable semantic order used by prompt reference mappings.

    Preserve the long-lived provider-facing order: characters establish
    identity first, the scene anchors the world, and props follow. This order
    is part of the authored ``[Image N]`` contract; changing it for aesthetic
    preference would silently swap responsibilities in stored video prompts.
    """

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


def video_reference_plan(
    project: Project,
    element: TimelineElement,
) -> tuple[str, ...]:
    """Reserve Image 1 for this element's current storyboard selection.

    Older projects may also list that storyboard explicitly among video
    references. A new selection replaces this semantic slot; it must not
    leave an older version in Image 2 and shift every identity reference.
    Only this output slot is excluded. Storyboards from other elements and
    unknown references retain their authored positions and validation.
    """
    from services.media_files.element_adapter import (
        element_output_slot_id,
        selected_element_output,
    )

    creation = element.creation
    if not isinstance(creation, R2VCreation):
        raise ValidationError("视频参考序列仅适用于 R2V Element")
    output = element.outputs.get("storyboard")
    slot_id = (
        output.slot_id
        if output is not None
        else element_output_slot_id(element.element_id, "storyboard")
    )
    slot = project.assets.artifact_slots_by_id.get(slot_id)
    own_versions = set(slot.version_ids if slot is not None else ())
    artifact_versions = project.assets.artifact_versions_by_id
    own_versions.update(
        version_id
        for version_id, artifact in artifact_versions.items()
        if artifact.slot_id == slot_id
    )
    selected = selected_element_output(project, element, "storyboard")
    storyboard_id = selected[1] if selected is not None else None
    if storyboard_id:
        own_versions.add(storyboard_id)
    # Resolve before filtering: an explicitly storyboard-only plan must not
    # accidentally become an empty list that activates automatic references.
    additional = resolve_r2v_visual_reference_version_ids(
        project,
        creation,
        creation.video_reference_version_ids,
    )
    return (
        *([storyboard_id] if storyboard_id else []),
        *(
            version_id
            for version_id in additional
            if version_id not in own_versions
        ),
    )


def preview_r2v_reference_order(
    project: Project,
    element_id: str,
    *,
    stage: str = "video",
    image_model_name: str = "",
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Authoritative ``[Image N]`` order preview for one r2v Element.

    Video mirrors the submit path (storyboard first, then the resolved
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
    if stage not in {"storyboard", "video"}:
        raise ValidationError("参考图阶段必须为 storyboard 或 video")
    selected_storyboard = selected_element_output(
        project,
        element,
        "storyboard",
    )
    storyboard_id = (
        selected_storyboard[1] if selected_storyboard is not None else None
    )
    dropped: tuple[str, ...] = ()
    if stage == "storyboard":
        version_ids, dropped = storyboard_reference_plan(
            project,
            creation,
            image_model_name=image_model_name,
        )
    else:
        version_ids = video_reference_plan(project, element)
    references: list[dict[str, Any]] = []
    if stage == "video" and storyboard_id is None:
        # Video execution requires this element's selected storyboard. Keep
        # its semantic position while authoring, without inventing a version
        # ID or allowing an identity reference to impersonate [Image 1].
        references.append(
            {
                "index": 1,
                "versionId": "",
                "kind": "storyboard",
                "available": False,
                "name": "分镜图（待生成）",
            },
        )
    for index, version_id in enumerate(version_ids, start=len(references) + 1):
        source = project.assets.source_versions_by_id.get(version_id)
        artifact = project.assets.artifact_versions_by_id.get(version_id)
        version = source if source is not None else artifact
        if stage == "video" and version_id == storyboard_id:
            kind = "storyboard"
        elif source is not None:
            kind = "source"
        else:
            kind = "artifact"
        available = version is not None
        if stage == "storyboard" and available and project_root is not None:
            # Use the actual submit resolver, one position at a time. A
            # missing middle image remains an unavailable slot, never a
            # filtered list that silently changes later [Image N] values.
            from services.media_files.image_execution import (
                _resolve_version_references,
            )
            from domain.errors import CreatorError

            try:
                _resolve_version_references(
                    project=project,
                    project_root=project_root,
                    version_ids=(version_id,),
                )
            except (CreatorError, KeyError):
                available = False
        references.append(
            {
                "index": index,
                "versionId": version_id,
                "kind": kind,
                "available": available,
                "name": (
                    version.name
                    if version is not None and version.name
                    else "参考图片"
                ),
            },
        )
    from models.image.base import image_reference_limit
    from models.reference_markers import canonical_marker_indices

    limit = (
        image_reference_limit(image_model_name)
        if stage == "storyboard"
        else None
    )
    indices = (
        canonical_marker_indices(creation.storyboard_prompt)
        if stage == "storyboard"
        else ()
    )
    invalid_indices = sorted(
        {index for index in indices if not 1 <= index <= len(references)},
    )
    return {
        "elementId": element_id,
        "stage": stage,
        "storyboardSelected": storyboard_id is not None,
        "references": references,
        "referenceLimit": limit,
        "budgetDroppedVersionIds": list(dropped),
        "invalidMarkerIndices": invalid_indices,
        "ready": (
            all(item["available"] for item in references)
            and not invalid_indices
            and (
                stage != "storyboard"
                or not references
                or (limit is not None and len(references) <= limit)
            )
        ),
    }


def storyboard_reference_plan(
    project: Project,
    creation: R2VCreation,
    *,
    additional_version_ids: Iterable[str] = (),
    image_model_name: str = "",
    max_reference_images: int | None = None,
    prompt: str | None = None,
    has_explicit_urls: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The same ordered image inputs for editor preview and new submission.

    Authored version lists and canonical markers pin reference identity. Only
    the legacy, unnumbered automatic chain retains its recorded budget trim.
    An oversized authored plan stays intact so admission can reject it.
    """
    from models.image.base import image_reference_limit
    from models.reference_markers import canonical_marker_indices

    explicit = (
        *creation.storyboard_reference_version_ids,
        *additional_version_ids,
    )
    ids = resolve_r2v_visual_reference_version_ids(project, creation, explicit)
    limit = (
        image_reference_limit(image_model_name)
        if max_reference_images is None
        else max_reference_images
    )
    if (
        limit is not None
        and 0 <= limit < len(ids)
        and not explicit
        and not has_explicit_urls
        and not canonical_marker_indices(
            creation.storyboard_prompt if prompt is None else prompt,
        )
    ):
        return ids[:limit], ids[limit:]
    return ids, ()


__all__ = [
    "preview_r2v_reference_order",
    "resolve_r2v_visual_reference_version_ids",
    "storyboard_reference_plan",
    "video_reference_plan",
]
