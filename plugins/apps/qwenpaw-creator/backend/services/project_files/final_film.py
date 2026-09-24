# -*- coding: utf-8 -*-
"""Canonical whole-film selection shared by Creator backend consumers."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    ArtifactSlot,
    ArtifactVersion,
    IndexedFile,
    Project,
    narrative_timeline_ids,
)


@dataclass(frozen=True, slots=True)
class CanonicalFinalFilm:
    timeline_id: str
    slot: ArtifactSlot
    version: ArtifactVersion
    file: IndexedFile


def resolve_canonical_final_film(
    project: Project,
) -> CanonicalFinalFilm | None:
    timeline_ids = narrative_timeline_ids(project)
    if len(timeline_ids) != 1:
        return None
    timeline_id = timeline_ids[0]
    slot = project.assets.artifact_slots_by_id.get(
        f"timeline:{timeline_id}:render",
    )
    if slot is None:
        slot = next(
            (
                candidate
                for candidate in project.assets.artifact_slots_by_id.values()
                if candidate.kind in {"timeline_render", "final_video"}
                and candidate.owner_ref == f"timeline:{timeline_id}"
            ),
            None,
        )
    if slot is None or slot.selected_version_id is None:
        return None
    version = project.assets.artifact_versions_by_id.get(
        slot.selected_version_id,
    )
    if (
        version is None
        or version.kind != "final_video"
        or version.stale
        or version.slot_id != slot.slot_id
        or version.owner_ref != f"timeline:{timeline_id}"
    ):
        return None
    indexed_file = project.assets.files_by_id.get(version.file_id)
    if indexed_file is None or not indexed_file.media_type.startswith(
        "video/",
    ):
        return None
    return CanonicalFinalFilm(
        timeline_id=timeline_id,
        slot=slot,
        version=version,
        file=indexed_file,
    )


__all__ = ["CanonicalFinalFilm", "resolve_canonical_final_film"]
