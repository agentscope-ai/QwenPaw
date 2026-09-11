# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Cast lineup pipeline: the lineup locks relative consistency, so its
selected image must lead every reference chain and its generation must
anchor on each character's canonical variant."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.enums import CreatorCommandType
from domain.errors import ValidationError
from services.media_files.image_execution import (
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


def _ab_project(*, selected: str | None = None) -> Project:
    """Two finished characters plus a registered lineup:main."""

    project = _project(
        _entity("char:a", variants={"var:x": "art:a-main"}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
        selected=selected,
    )
    project.visual.cast_lineups.order.append("lineup:main")
    return project


def test_lineup_anchors_prefer_the_canonical_variant() -> None:
    project = _project(
        _entity(
            "char:a",
            canonical="var:master",
            variants={"var:other": "art:a-other", "var:master": "art:a-main"},
        ),
        _entity("char:b", variants={"var:solo": "art:b-main"}),
    )
    anchors, missing = _lineup_character_reference_ids(
        project,
        _lineup("char:a", "char:b"),
    )

    # char:a resolves through its canonical variant, not the first variant.
    assert anchors == ["art:a-main", "art:b-main"]
    assert not missing


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


def _duo_creation() -> R2VCreation:
    return R2VCreation(
        character_refs=["char:a"],
        visual_variant_refs={"char:a": "var:x"},
        cast_lineup_refs=["lineup:main"],
    )


def test_reference_chain_leads_with_the_lineup_anchor() -> None:
    project = _ab_project(selected="art:lineup-main")

    resolved = resolve_r2v_visual_reference_version_ids(
        project,
        _duo_creation(),
        [],
    )

    assert resolved[0] == "art:lineup-main"
    assert "art:a-main" in resolved


def _add_duo_element(project: Project, *, lineup_refs: list[str]) -> None:
    project.timelines.items["timeline:main"].elements_by_id[
        "elem:duo"
    ] = TimelineElement(
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
    project = _ab_project()
    _add_duo_element(project, lineup_refs=["lineup:main"])

    issues = visual_design_readiness_issues(project)
    assert [issue.code for issue in issues] == ["MISSING_CAST_LINEUP_IMAGE"]
    with pytest.raises(ValidationError, match="阵容图 lineup:main 尚未生成"):
        assert_visual_design_ready_for_storyboards(project)

    # Once the lineup image exists the same declared refs open the gate.
    drawn = _ab_project(selected="art:lineup-main")
    _add_duo_element(drawn, lineup_refs=["lineup:main"])
    assert not visual_design_readiness_issues(drawn)
