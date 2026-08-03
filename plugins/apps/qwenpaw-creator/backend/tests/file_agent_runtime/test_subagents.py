# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.file_agent_runtime.subagents import (
    DelegateToAgentInput,
    delegate_tool_manifest,
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
