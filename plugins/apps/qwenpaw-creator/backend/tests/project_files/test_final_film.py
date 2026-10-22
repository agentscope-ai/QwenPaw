# -*- coding: utf-8 -*-

from datetime import UTC, datetime

import pytest

from services.project_files.final_film import resolve_canonical_final_film
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    IndexedFile,
    Project,
    Timeline,
)

NOW = datetime(2026, 7, 20, tzinfo=UTC)
CHECKSUM = "0" * 64
TIMELINE_ID = "timeline:main"
SLOT_ID = f"timeline:{TIMELINE_ID}:render"
VERSION_ID = "final-v1"
FILE_ID = "file:final"


def canonical_project() -> Project:
    project = Project.new(project_id="project-1", name="Test", now=NOW)
    project.assets.files_by_id[FILE_ID] = IndexedFile(
        file_id=FILE_ID,
        kind="artifact_payload",
        relative_uri="assets/final.mp4",
        sha256=CHECKSUM,
        size_bytes=42,
        media_type="video/mp4",
        created_at=NOW,
    )
    project.assets.artifact_slots_by_id[SLOT_ID] = ArtifactSlot(
        slot_id=SLOT_ID,
        kind="final_video",
        owner_ref=f"timeline:{TIMELINE_ID}",
        version_ids=[VERSION_ID],
        selected_version_id=VERSION_ID,
    )
    project.assets.artifact_versions_by_id[VERSION_ID] = ArtifactVersion(
        version_id=VERSION_ID,
        slot_id=SLOT_ID,
        kind="final_video",
        owner_ref=f"timeline:{TIMELINE_ID}",
        name="Final",
        file_id=FILE_ID,
        checksum=CHECKSUM,
        based_on_generation=0,
        created_at=NOW,
    )
    return Project.model_validate(project.model_dump(mode="json"))


def selected_version_id(project: Project) -> str | None:
    resolved = resolve_canonical_final_film(project)
    return resolved.version.version_id if resolved else None


def test_valid_selected_final_video_is_canonical() -> None:
    assert selected_version_id(canonical_project()) == VERSION_ID


def test_zero_live_timelines_have_no_canonical_film() -> None:
    project = canonical_project()
    project.timelines.items.clear()
    project.timelines.order.clear()

    assert selected_version_id(project) is None


def test_multiple_live_timelines_have_no_canonical_film() -> None:
    project = canonical_project()
    project.timelines.items["timeline:episode-2"] = Timeline(
        timeline_id="timeline:episode-2",
    )
    project.timelines.order.append("timeline:episode-2")

    assert selected_version_id(project) is None


def test_snapshot_timeline_does_not_hide_canonical_film() -> None:
    project = canonical_project()
    snapshot_id = "snapshot:timeline:main:1"
    project.timelines.items[snapshot_id] = Timeline(timeline_id=snapshot_id)
    project.timelines.order.append(snapshot_id)

    assert selected_version_id(project) == VERSION_ID


@pytest.mark.parametrize(
    "mutate",
    [
        lambda project: setattr(
            project.assets.artifact_slots_by_id[SLOT_ID],
            "selected_version_id",
            None,
        ),
        lambda project: setattr(
            project.assets.artifact_slots_by_id[SLOT_ID],
            "selected_version_id",
            "missing-version",
        ),
        lambda project: project.assets.files_by_id.pop(FILE_ID),
        lambda project: setattr(
            project.assets.artifact_versions_by_id[VERSION_ID],
            "stale",
            True,
        ),
        lambda project: setattr(
            project.assets.artifact_versions_by_id[VERSION_ID],
            "kind",
            "element_video",
        ),
        lambda project: setattr(
            project.assets.artifact_versions_by_id[VERSION_ID],
            "owner_ref",
            "timeline:other",
        ),
        lambda project: setattr(
            project.assets.artifact_versions_by_id[VERSION_ID],
            "slot_id",
            "timeline:other:render",
        ),
        lambda project: setattr(
            project.assets.files_by_id[FILE_ID],
            "media_type",
            "image/png",
        ),
    ],
    ids=[
        "missing-selection",
        "missing-version",
        "missing-file",
        "stale-version",
        "wrong-kind",
        "wrong-owner",
        "wrong-slot",
        "non-video-file",
    ],
)
def test_invalid_selected_output_is_not_canonical(mutate) -> None:
    project = canonical_project()
    mutate(project)

    assert selected_version_id(project) is None


def test_newer_unselected_version_does_not_replace_selection() -> None:
    project = canonical_project()
    newer = project.assets.artifact_versions_by_id[VERSION_ID].model_copy(
        update={
            "version_id": "final-v2",
            "created_at": datetime(2026, 7, 21, tzinfo=UTC),
        },
    )
    project.assets.artifact_versions_by_id[newer.version_id] = newer
    project.assets.artifact_slots_by_id[SLOT_ID].version_ids.append(
        newer.version_id,
    )

    assert selected_version_id(project) == VERSION_ID
