# -*- coding: utf-8 -*-
# flake8: noqa: E501
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


def _hero(variants: dict[str, str | None]) -> VisualEntity:
    """char:hero requiring peak+fallen, with the given variant selections."""

    return VisualEntity(
        entity_id="char:hero",
        kind="character",
        name="Hero",
        required_variant_ids=["variant:peak", "variant:fallen"],
        variants=EntityCollection(
            items={
                variant_id: VisualVariant(
                    variant_id=variant_id,
                    selected_artifact_version_id=selected,
                )
                for variant_id, selected in variants.items()
            },
            order=list(variants),
        ),
    )


def _scene() -> VisualEntity:
    return VisualEntity(
        entity_id="scene:street",
        kind="scene",
        name="Street",
        required_variant_ids=[],
    )


def test_reports_missing_required_variant_before_storyboarding() -> None:
    project = _project_with_visual(
        _hero({"variant:peak": None}),
        visual_variant_refs={"char:hero": "variant:peak"},
    )

    issues = visual_design_readiness_issues(project)

    assert [issue.code for issue in issues] == [
        "MISSING_SELECTED_ARTIFACT",
        "MISSING_REQUIRED_VARIANT",
    ]
    with pytest.raises(ValidationError, match="视觉设定尚未完成，分镜图未开始"):
        assert_visual_design_ready_for_storyboards(project)


def test_complete_contract_passes_and_binding_is_required() -> None:
    variants = {
        "variant:peak": "artifact:peak",
        "variant:fallen": "artifact:fallen",
    }
    ready = _project_with_visual(
        _hero(variants),
        visual_variant_refs={"char:hero": "variant:peak"},
    )
    assert not visual_design_readiness_issues(ready)
    assert_visual_design_ready_for_storyboards(ready)

    # The same finished variants without an element binding still block.
    unbound = _project_with_visual(_hero(variants))
    issues = visual_design_readiness_issues(unbound)
    assert [issue.code for issue in issues] == ["MISSING_VARIANT_BINDING"]


def test_storyboard_request_enforces_visual_design_gate(tmp_path) -> None:
    project = _project_with_visual(_scene())
    snapshot = ProjectSnapshot(project=project, etag="etag-1", generation=1)

    with pytest.raises(ValidationError, match="scene:street 尚无使用中视觉产物"):
        _resolve_request(
            snapshot=snapshot,
            project_root=tmp_path,
            command=CreatorCommandType.GENERATE_STORYBOARD_IMAGE,
            target_ref="element:element:01",
            arguments={"prompt": "street storyboard"},
        )
