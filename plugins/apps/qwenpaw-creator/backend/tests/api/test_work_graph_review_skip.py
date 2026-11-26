# -*- coding: utf-8 -*-
"""Work-graph review status: why an artifact was delivered without a review.

Issue #8592 follow-up: a missing ffmpeg/ffprobe skipped the automatic media
review with only a warning and a trace, which are invisible in the
workbench. The skip note is persisted per slot; these tests pin the graph
projection that carries it to the node of the artifact it describes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api.work_graph_routes import _node_review_skip, _review_skip_notes
from services.file_agent_runtime.work_graph import WorkNode, WorkNodeStatus
from services.project_files.models import ArtifactSlot, Project
from services.run_review import admission

pytestmark = pytest.mark.unit

PROJECT_ID = "project-review-skip"
SLOT_ID = "element:e1:storyboard"
VERSION_ID = "artifact-version-img-1"
HINT = "install ffmpeg on PATH or set CREATOR_FFMPEG_PATH"


def _project_with_slot(
    *,
    kind: str,
    owner_ref: str,
    slot_id: str,
    version_id: str = VERSION_ID,
    variant_id: str | None = None,
) -> Project:
    project = Project.new(project_id=PROJECT_ID, name="Skip Note")
    project.assets.artifact_slots_by_id[slot_id] = ArtifactSlot(
        slot_id=slot_id,
        kind=kind,
        owner_ref=owner_ref,
        version_ids=[version_id],
        selected_version_id=version_id,
        metadata={"variantId": variant_id} if variant_id else {},
    )
    return project


def _node(
    kind: str,
    target_ref: str | None,
    *,
    variant_id: str | None = None,
) -> WorkNode:
    return WorkNode(
        node_id=f"{kind}:{target_ref}:{variant_id}",
        kind=kind,
        label=kind,
        status=WorkNodeStatus.DONE,
        target_ref=target_ref,
        dispatch_arguments=({"variantId": variant_id} if variant_id else {}),
    )


def test_review_skip_note_reaches_the_artifact_node(tmp_path: Path) -> None:
    reports_root = tmp_path / "runtime" / "run-review"
    admission.record_media_skip(
        reports_root,
        slot_id=SLOT_ID,
        version_id=VERSION_ID,
        reason="ffmpeg_unavailable",
        hint=HINT,
    )
    project = _project_with_slot(
        kind="r2v_storyboard_image",
        owner_ref="element:e1",
        slot_id=SLOT_ID,
    )

    notes = _review_skip_notes(project, reports_root)
    assert _node_review_skip(_node("storyboard", "element:e1"), notes) == {
        "reason": "ffmpeg_unavailable",
        "hint": HINT,
    }

    # The note describes the selected output only. A newer version retires
    # it without anyone having to clean up the state file.
    slot = project.assets.artifact_slots_by_id[SLOT_ID]
    slot.selected_version_id = "artifact-version-img-2"
    assert _review_skip_notes(project, reports_root) == {}
    assert _node_review_skip(_node("storyboard", "element:e1"), {}) is None


def test_review_skip_note_stays_with_its_own_artifact(tmp_path: Path) -> None:
    reports_root = tmp_path / "runtime" / "run-review"
    admission.record_media_skip(
        reports_root,
        slot_id="asset:hero:variant:v1:image",
        version_id=VERSION_ID,
        reason="ffmpeg_unavailable",
        hint=HINT,
    )
    project = _project_with_slot(
        kind="visual_asset_image",
        owner_ref="asset:hero",
        slot_id="asset:hero:variant:v1:image",
        variant_id="v1",
    )

    notes = _review_skip_notes(project, reports_root)
    assert (
        _node_review_skip(
            _node("visual", "asset:hero", variant_id="v1"),
            notes,
        )
        is not None
    )
    # Another artifact kind on the same owner must not inherit the note,
    # and a node without a target owns no artifact of its own.
    assert _node_review_skip(_node("lineup", "asset:hero"), notes) is None
    assert _node_review_skip(_node("video", None), notes) is None


def test_review_skip_note_does_not_leak_between_variants(
    tmp_path: Path,
) -> None:
    """One entity's variants share owner_ref and slot kind but not outputs."""

    reports_root = tmp_path / "runtime" / "run-review"
    admission.record_media_skip(
        reports_root,
        slot_id="asset:hero:variant:v1:image",
        version_id="artifact-version-hero-v1",
        reason="ffmpeg_unavailable",
        hint=HINT,
    )
    project = _project_with_slot(
        kind="visual_asset_image",
        owner_ref="asset:hero",
        slot_id="asset:hero:variant:v1:image",
        version_id="artifact-version-hero-v1",
        variant_id="v1",
    )
    v2 = _project_with_slot(
        kind="visual_asset_image",
        owner_ref="asset:hero",
        slot_id="asset:hero:variant:v2:image",
        version_id="artifact-version-hero-v2",
        variant_id="v2",
    ).assets.artifact_slots_by_id["asset:hero:variant:v2:image"]
    project.assets.artifact_slots_by_id[v2.slot_id] = v2

    notes = _review_skip_notes(project, reports_root)
    assert _node_review_skip(
        _node("visual", "asset:hero", variant_id="v1"),
        notes,
    ) == {"reason": "ffmpeg_unavailable", "hint": HINT}
    # v2 produced its own output without a skip: the v1 reason must not
    # surface on it, and a third variant has no note of its own either.
    assert (
        _node_review_skip(
            _node("visual", "asset:hero", variant_id="v2"),
            notes,
        )
        is None
    )
    assert (
        _node_review_skip(
            _node("visual", "asset:hero", variant_id="v3"),
            notes,
        )
        is None
    )
