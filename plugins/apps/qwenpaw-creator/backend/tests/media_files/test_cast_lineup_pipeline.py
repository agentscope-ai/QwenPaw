# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Cast lineup pipeline: group anchor generation and reference-chain lead.

The lineup locks relative consistency (scale ratios, shared style
baseline, spatial order) that per-entity continuity cannot express, so
its selected image must lead every storyboard/video reference chain and
its own generation must anchor on each character's canonical variant.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.enums import CreatorCommandType
from domain.errors import ValidationError
from services.media_files.image_execution import (
    FileImageExecutionService,
    _lineup_character_reference_ids,
    _resolve_request,
)
from services.media_files.visual_design_readiness import (
    assert_visual_design_ready_for_storyboards,
    visual_design_readiness_issues,
)
from services.media_files.visual_reference_resolution import (
    resolve_r2v_visual_reference_version_ids,
)
from services.project_files.models import (
    ElementLocation,
    Project,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
    VisualCastLineup,
    VisualEntity,
    VisualVariant,
)
from services.specialist_tools import SpecialistRole


pytestmark = pytest.mark.unit


def _entity(
    entity_id: str,
    *,
    canonical: str | None = None,
    variants: dict[str, str | None] | None = None,
) -> VisualEntity:
    items = {}
    order = []
    for variant_id, selected in (variants or {}).items():
        items[variant_id] = VisualVariant(
            variant_id=variant_id,
            selected_artifact_version_id=selected,
        )
        order.append(variant_id)
    return VisualEntity(
        entity_id=entity_id,
        kind="character",
        name=entity_id.removeprefix("char:"),
        required_variant_ids=order,
        canonical_variant_id=canonical,
        variants={"items": items, "order": order},
    )


def _project(*entities: VisualEntity) -> Project:
    project = Project.new(project_id="p-lineup", name="Lineup")
    for entity in entities:
        project.visual.entities.items[entity.entity_id] = entity
        project.visual.entities.order.append(entity.entity_id)
    return project


def _lineup(*character_refs: str, selected: str | None = None):
    return VisualCastLineup(
        lineup_id="lineup:main",
        name="主阵容",
        character_refs=list(character_refs),
        generated_artifact_version_ids=[selected] if selected else [],
        selected_artifact_version_id=selected,
        relative_notes="A:B ≈ 195:170cm",
    )


def test_lineup_anchors_prefer_the_canonical_variant() -> None:
    project = _project(
        _entity(
            "char:a",
            canonical="var:master",
            variants={"var:other": "art:a-other", "var:master": "art:a-main"},
        ),
        _entity("char:b", variants={"var:solo": "art:b-main"}),
    )
    lineup = _lineup("char:a", "char:b")

    anchors, missing = _lineup_character_reference_ids(project, lineup)

    # char:a resolves through its canonical variant, not the first variant;
    # char:b falls back to the only variant carrying a selection.
    assert anchors == ["art:a-main", "art:b-main"]
    assert not missing


def test_lineup_anchors_report_characters_without_artwork() -> None:
    project = _project(
        _entity("char:a", variants={"var:x": None}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    lineup = _lineup("char:a", "char:b")

    anchors, missing = _lineup_character_reference_ids(project, lineup)

    assert anchors == ["art:b-main"]
    assert missing == ["char:a"]


def test_resolve_rejects_lineup_generation_with_unfinished_characters(
    tmp_path,
) -> None:
    project = _project(
        _entity("char:a", variants={"var:x": None}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
    )
    project.visual.cast_lineups.order.append("lineup:main")

    with pytest.raises(ValidationError, match="char:a"):
        _resolve_request(
            # type-checked as ProjectSnapshot; only .project is consumed
            snapshot=SimpleNamespace(project=project),  # type: ignore
            project_root=tmp_path,
            command=CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE,
            target_ref="lineup:lineup:main",
            arguments={},
        )


def test_reference_chain_leads_with_the_lineup_anchor() -> None:
    project = _project(
        _entity("char:a", variants={"var:x": "art:a-main"}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
        selected="art:lineup-main",
    )
    project.visual.cast_lineups.order.append("lineup:main")
    creation = R2VCreation(
        character_refs=["char:a"],
        visual_variant_refs={"char:a": "var:x"},
        cast_lineup_refs=["lineup:main"],
    )

    resolved = resolve_r2v_visual_reference_version_ids(project, creation, [])

    assert resolved[0] == "art:lineup-main"
    assert "art:a-main" in resolved


def test_reference_chain_skips_lineups_without_a_selected_image() -> None:
    project = _project(
        _entity("char:a", variants={"var:x": "art:a-main"}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
    )
    project.visual.cast_lineups.order.append("lineup:main")
    creation = R2VCreation(
        character_refs=["char:a"],
        visual_variant_refs={"char:a": "var:x"},
        cast_lineup_refs=["lineup:main"],
    )

    resolved = resolve_r2v_visual_reference_version_ids(project, creation, [])

    assert resolved == ("art:a-main",)


def test_apply_result_records_the_lineup_artifact() -> None:
    project = _project(
        _entity("char:a", variants={"var:x": "art:a-main"}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
    )
    project.visual.cast_lineups.order.append("lineup:main")
    candidate = project.model_dump(mode="json")
    result = {
        "commandType": "GENERATE_CAST_LINEUP_IMAGE",
        "targetRef": "lineup:lineup:main",
        "indexedFile": {
            "file_id": "file-lineup-1",
            "kind": "artifact_payload",
            "media_type": "image/png",
            "relative_uri": "assets/artifacts/file-lineup-1.png",
            "sha256": "0" * 64,
            "size_bytes": 128,
            "created_at": "2026-08-05T00:00:00Z",
        },
        "artifactVersion": {
            "version_id": "artifact-lineup-1",
            "slot_id": "lineup:lineup:main:image",
            "kind": "cast_lineup_image",
            "owner_ref": "lineup:lineup:main",
            "file_id": "file-lineup-1",
            "checksum": "0" * 64,
            "created_at": "2026-08-05T00:00:00Z",
            "input_fingerprint": "sha256:" + "1" * 64,
            "based_on_generation": 1,
            "name": "主阵容 阵容图",
        },
    }

    FileImageExecutionService._apply_result(
        candidate,
        result,
    )

    lineup = candidate["visual"]["cast_lineups"]["items"]["lineup:main"]
    assert "artifact-lineup-1" in lineup["generated_artifact_version_ids"]
    assert lineup["selected_artifact_version_id"] == "artifact-lineup-1"
    slot = candidate["assets"]["artifact_slots_by_id"][
        "lineup:lineup:main:image"
    ]
    assert slot["kind"] == "cast_lineup_image"


def test_project_assets_scope_admits_lineup_targets() -> None:
    # pylint: disable=import-outside-toplevel
    from services.specialist_tools import _SPECS_BY_NAME

    spec = _SPECS_BY_NAME["image_generation"]
    assert spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="lineup:lineup:main",
        admitted_target_refs=["project:assets"],
    )
    assert not spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="lineup:",
        admitted_target_refs=["project:assets"],
    )


def _element_with_lineup_ref(*, lineup_refs: list[str]) -> TimelineElement:
    return TimelineElement(
        element_id="elem:duo",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            character_refs=["char:a", "char:b"],
            visual_variant_refs={"char:a": "var:x", "char:b": "var:y"},
            cast_lineup_refs=lineup_refs,
        ),
    )


def test_storyboard_gate_blocks_declared_lineups_without_artwork() -> None:
    """Field run 2026-08-05: the specialist finished individual artwork
    and skipped the lineup entirely, so storyboards shipped without the
    group anchor. A declared cast_lineup_refs is the model's own contract
    and must hold the storyboard gate until the image exists."""
    project = _project(
        _entity("char:a", variants={"var:x": "art:a-main"}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
    )
    project.visual.cast_lineups.order.append("lineup:main")
    project.timelines.items["timeline:main"].elements_by_id[
        "elem:duo"
    ] = _element_with_lineup_ref(lineup_refs=["lineup:main"])

    issues = visual_design_readiness_issues(project)
    assert [issue.code for issue in issues] == ["MISSING_CAST_LINEUP_IMAGE"]
    with pytest.raises(ValidationError, match="阵容图 lineup:main 尚未生成"):
        assert_visual_design_ready_for_storyboards(project)


def test_storyboard_gate_opens_once_the_lineup_is_drawn() -> None:
    project = _project(
        _entity("char:a", variants={"var:x": "art:a-main"}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
        selected="art:lineup-main",
    )
    project.visual.cast_lineups.order.append("lineup:main")
    project.timelines.items["timeline:main"].elements_by_id[
        "elem:duo"
    ] = _element_with_lineup_ref(lineup_refs=["lineup:main"])

    assert not visual_design_readiness_issues(project)


def test_storyboard_gate_ignores_elements_without_lineup_refs() -> None:
    # The chain-level skip stays available for elements that never
    # declared a lineup — only declared references hold the gate.
    project = _project(
        _entity("char:a", variants={"var:x": "art:a-main"}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
    )
    project.visual.cast_lineups.order.append("lineup:main")
    project.timelines.items["timeline:main"].elements_by_id[
        "elem:duo"
    ] = _element_with_lineup_ref(lineup_refs=[])

    assert not visual_design_readiness_issues(project)
