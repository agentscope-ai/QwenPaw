# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from domain.enums import CreatorCommandType
from domain.errors import ValidationError
from services.media_files.image_execution import _resolve_request
from services.media_files.visual_design_readiness import (
    assert_visual_design_ready_for_storyboards,
    visual_design_readiness_issues,
)
from services.project_files.models import (
    ElementLocation,
    EntityCollection,
    Project,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
    VisualEntity,
    VisualVariant,
)
from services.project_files.store import ProjectSnapshot


pytestmark = pytest.mark.unit


def _project_with_visual(
    entity: VisualEntity,
    *,
    visual_variant_refs: dict[str, str] | None = None,
) -> Project:
    project = Project.new(project_id="project-visual-gate", name="Visual")
    project.visual.entities.items[entity.entity_id] = entity
    project.visual.entities.order.append(entity.entity_id)
    project.timelines.items["timeline:main"].elements_by_id[
        "element:01"
    ] = TimelineElement(
        element_id="element:01",
        span=TimelineSpan(start_tick=0, duration_tick=6_000),
        location=ElementLocation(),
        creation=R2VCreation(
            character_refs=(
                [entity.entity_id] if entity.kind == "character" else []
            ),
            scene_ref=(entity.entity_id if entity.kind == "scene" else None),
            prop_refs=([entity.entity_id] if entity.kind == "prop" else []),
            visual_variant_refs=visual_variant_refs or {},
        ),
    )
    return project


def test_reports_missing_required_variant_before_storyboarding() -> None:
    project = _project_with_visual(
        VisualEntity(
            entity_id="char:hero",
            kind="character",
            name="Hero",
            required_variant_ids=["variant:peak", "variant:fallen"],
            variants=EntityCollection(
                items={
                    "variant:peak": VisualVariant(
                        variant_id="variant:peak",
                    ),
                },
                order=["variant:peak"],
            ),
        ),
        visual_variant_refs={"char:hero": "variant:peak"},
    )

    issues = visual_design_readiness_issues(project)

    assert [issue.code for issue in issues] == [
        "MISSING_SELECTED_ARTIFACT",
        "MISSING_REQUIRED_VARIANT",
    ]
    with pytest.raises(
        ValidationError,
        match="视觉设定尚未完成，分镜图未开始",
    ):
        assert_visual_design_ready_for_storyboards(project)


def test_reports_missing_multi_variant_binding() -> None:
    project = _project_with_visual(
        VisualEntity(
            entity_id="char:hero",
            kind="character",
            name="Hero",
            required_variant_ids=["variant:peak", "variant:fallen"],
            variants=EntityCollection(
                items={
                    "variant:peak": VisualVariant(
                        variant_id="variant:peak",
                        selected_artifact_version_id="artifact:peak",
                    ),
                    "variant:fallen": VisualVariant(
                        variant_id="variant:fallen",
                        selected_artifact_version_id="artifact:fallen",
                    ),
                },
                order=["variant:peak", "variant:fallen"],
            ),
        ),
    )

    issues = visual_design_readiness_issues(project)

    assert [issue.code for issue in issues] == ["MISSING_VARIANT_BINDING"]


def test_reports_ungenerated_scene_without_variants() -> None:
    project = _project_with_visual(
        VisualEntity(
            entity_id="scene:street",
            kind="scene",
            name="Street",
            required_variant_ids=[],
        ),
    )

    issues = visual_design_readiness_issues(project)

    assert len(issues) == 1
    assert issues[0].code == "MISSING_SELECTED_ARTIFACT"
    assert issues[0].variant_id is None


def test_complete_visual_contract_passes_storyboard_gate() -> None:
    project = _project_with_visual(
        VisualEntity(
            entity_id="char:hero",
            kind="character",
            name="Hero",
            required_variant_ids=["variant:peak", "variant:fallen"],
            variants=EntityCollection(
                items={
                    "variant:peak": VisualVariant(
                        variant_id="variant:peak",
                        selected_artifact_version_id="artifact:peak",
                    ),
                    "variant:fallen": VisualVariant(
                        variant_id="variant:fallen",
                        selected_artifact_version_id="artifact:fallen",
                    ),
                },
                order=["variant:peak", "variant:fallen"],
            ),
        ),
        visual_variant_refs={"char:hero": "variant:peak"},
    )

    assert not visual_design_readiness_issues(project)
    assert_visual_design_ready_for_storyboards(project)


def test_storyboard_request_enforces_visual_design_gate(tmp_path) -> None:
    project = _project_with_visual(
        VisualEntity(
            entity_id="scene:street",
            kind="scene",
            name="Street",
            required_variant_ids=[],
        ),
    )
    snapshot = ProjectSnapshot(project=project, etag="etag-1", generation=1)

    with pytest.raises(
        ValidationError,
        match="scene:street 尚无使用中视觉产物",
    ):
        _resolve_request(
            snapshot=snapshot,
            project_root=tmp_path,
            command=CreatorCommandType.GENERATE_STORYBOARD_IMAGE,
            target_ref="element:element:01",
            arguments={"prompt": "street storyboard"},
        )
