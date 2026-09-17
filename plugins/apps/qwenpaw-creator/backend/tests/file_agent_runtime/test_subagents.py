# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.file_agent_runtime.subagents import (
    DelegateToAgentInput,
    delegate_tool_manifest,
)
from services.project_files.models import (
    Project,
    VisualCastLineup,
    VisualEntity,
)


pytestmark = pytest.mark.unit


def test_delegate_input_rejects_duplicate_target_refs() -> None:
    with pytest.raises(
        ValidationError,
        match="target_refs must contain unique values",
    ):
        DelegateToAgentInput.model_validate(
            {
                "role": "visual_development_agent",
                "target_refs": ["project:assets", "project:assets"],
                "task": "建立视觉结构",
            },
        )


def test_only_current_element_specialists_are_delegatable() -> None:
    roles = delegate_tool_manifest()["function"]["parameters"]["properties"][
        "role"
    ]["enum"]
    assert roles == [
        "source_intelligence_agent",
        "visual_development_agent",
        "r2v_generation_director",
        "ai_editing_director",
    ]

    with pytest.raises(ValidationError):
        DelegateToAgentInput.model_validate(
            {
                "role": "retired_planning_agent",
                "target_refs": ["project:plan"],
                "task": "这个职责现在属于 Creator 主 Agent",
            },
        )


def test_r2v_and_edit_use_element_domain_targets() -> None:
    r2v = DelegateToAgentInput.model_validate(
        {
            "role": "r2v_generation_director",
            "target_refs": ["element:r2v-1"],
            "task": "生成目标 Element",
        },
    )
    r2v.validate_contract(project_id="project-1")

    edit = DelegateToAgentInput.model_validate(
        {
            "role": "ai_editing_director",
            "target_refs": ["timeline:timeline:main"],
            "task": "选择并执行 Edit Elements",
        },
    )
    edit.validate_contract(project_id="project-1")


def test_visual_entity_target_aliases_normalize_to_asset_refs() -> None:
    """Both spellings observed in production map onto asset:<id>.

    project.json keys entities as char:/scene:/prop:<x> and the UI shows
    visual-entity:<id>, so models keep guessing those forms; the contract
    accepts and maps them instead of failing a recoverable delegation.
    """

    delegated = DelegateToAgentInput.model_validate(
        {
            "role": "visual_development_agent",
            "target_refs": [
                "char:haaland",
                "visual-entity:char:haaland",
                "scene:idol-stage",
                "prop:trophy",
                "asset:char:depaul",
            ],
            "task": "为角色和场景生成设计图",
        },
    )
    delegated.validate_contract(project_id="project-1")
    # char:haaland and its visual-entity spelling collapse into one ref.
    assert delegated.target_refs == [
        "asset:char:haaland",
        "asset:scene:idol-stage",
        "asset:prop:trophy",
        "asset:char:depaul",
    ]

    source = DelegateToAgentInput.model_validate(
        {
            "role": "source_intelligence_agent",
            "target_refs": ["char:haaland"],
            "task": "理解角色参考素材",
        },
    )
    source.validate_contract(project_id="project-1")
    assert source.target_refs == ["asset:char:haaland"]


def test_visual_entity_aliases_stay_rejected_for_element_domain_roles() -> (
    None
):
    delegated = DelegateToAgentInput.model_validate(
        {
            "role": "r2v_generation_director",
            "target_refs": ["char:haaland"],
            "task": "生成视频",
        },
    )
    with pytest.raises(ValueError, match="does not allow targetRef"):
        delegated.validate_contract(project_id="project-1")


def test_unknown_target_kinds_still_fail_the_contract() -> None:
    delegated = DelegateToAgentInput.model_validate(
        {
            "role": "visual_development_agent",
            "target_refs": ["storyline:act-1"],
            "task": "非法目标",
        },
    )
    with pytest.raises(ValueError, match="does not allow targetRef"):
        delegated.validate_contract(project_id="project-1")


def test_visual_target_must_resolve_to_visual_entity() -> None:
    project = Project.new(project_id="project-1", name="Test")
    project.visual.entities.items["char:wembanyama"] = VisualEntity(
        entity_id="char:wembanyama",
        kind="character",
        name="Victor Wembanyama",
        required_variant_ids=[],
    )
    project.visual.entities.order.append("char:wembanyama")

    valid = DelegateToAgentInput.model_validate(
        {
            "role": "visual_development_agent",
            "target_refs": ["asset:char:wembanyama"],
            "task": "生成定妆图",
        },
    )
    valid.validate_contract(project_id="project-1")
    valid.validate_project_targets(project=project)

    wrong_source_asset = DelegateToAgentInput.model_validate(
        {
            "role": "visual_development_agent",
            "target_refs": ["asset:asset-84e7f53cb"],
            "task": "生成定妆图",
        },
    )
    wrong_source_asset.validate_contract(project_id="project-1")
    with pytest.raises(
        ValueError,
        match=r"Source logical Asset ids belong in referenceVersionIds",
    ):
        wrong_source_asset.validate_project_targets(project=project)


def test_project_assets_visual_target_does_not_require_one_entity() -> None:
    delegated = DelegateToAgentInput.model_validate(
        {
            "role": "visual_development_agent",
            "target_refs": ["project:assets"],
            "task": "建立整体视觉设定",
        },
    )
    delegated.validate_contract(project_id="project-1")
    delegated.validate_project_targets(
        project=Project.new(project_id="project-1", name="Test"),
    )


def test_lineup_targets_delegate_to_visual_development() -> None:
    """lineup:<id> mirrors the image_generation tool surface.

    Observed live (project-bb49): the mainline delegated the cast lineup
    it had just planned and the contract rejected the ref even though the
    specialist's own image_generation tool accepts lineup targets.
    """

    project = Project.new(project_id="project-1", name="Test")
    project.visual.cast_lineups.items["argentina-trio"] = VisualCastLineup(
        lineup_id="argentina-trio",
        name="Argentina trio",
        character_refs=["char:messi", "char:depaul"],
    )
    project.visual.cast_lineups.order.append("argentina-trio")

    delegated = DelegateToAgentInput.model_validate(
        {
            "role": "visual_development_agent",
            "target_refs": ["lineup:argentina-trio"],
            "task": "生成阵容图",
        },
    )
    delegated.validate_contract(project_id="project-1")
    delegated.validate_project_targets(project=project)


def test_unknown_lineup_target_names_the_valid_lineups() -> None:
    project = Project.new(project_id="project-1", name="Test")
    project.visual.cast_lineups.items["argentina-trio"] = VisualCastLineup(
        lineup_id="argentina-trio",
        name="Argentina trio",
        character_refs=["char:messi", "char:depaul"],
    )
    project.visual.cast_lineups.order.append("argentina-trio")

    delegated = DelegateToAgentInput.model_validate(
        {
            "role": "visual_development_agent",
            "target_refs": ["lineup:missing"],
            "task": "生成阵容图",
        },
    )
    delegated.validate_contract(project_id="project-1")
    with pytest.raises(ValueError, match=r"lineup:argentina-trio"):
        delegated.validate_project_targets(project=project)


def test_lineup_targets_stay_rejected_for_other_roles() -> None:
    delegated = DelegateToAgentInput.model_validate(
        {
            "role": "r2v_generation_director",
            "target_refs": ["lineup:argentina-trio"],
            "task": "生成分镜",
        },
    )
    with pytest.raises(ValueError, match=r"does not allow targetRef"):
        delegated.validate_contract(project_id="project-1")
