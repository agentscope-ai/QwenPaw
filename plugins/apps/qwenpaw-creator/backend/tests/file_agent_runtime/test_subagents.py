# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.file_agent_runtime.subagents import (
    DelegateToAgentInput,
    delegate_tool_manifest,
)


pytestmark = pytest.mark.unit


def test_only_current_element_specialists_are_delegatable() -> None:
    roles = delegate_tool_manifest()["function"]["parameters"]["properties"][
        "role"
    ]["enum"]
    assert roles == [
        "source_intelligence_agent",
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


def test_r2v_is_not_delegatable_and_edit_uses_timeline_targets() -> None:
    r2v = DelegateToAgentInput.model_validate(
        {
            "role": "r2v_generation_director",
            "target_refs": ["element:r2v-1"],
            "task": "生成目标 Element",
        },
    )
    with pytest.raises(ValueError, match="not delegatable"):
        r2v.validate_contract(project_id="project-1")

    edit = DelegateToAgentInput.model_validate(
        {
            "role": "ai_editing_director",
            "target_refs": ["timeline:timeline:main"],
            "task": "选择并执行 Edit Elements",
        },
    )
    edit.validate_contract(project_id="project-1")


def test_visual_development_is_not_delegatable() -> None:
    """Visual asset prompts are authored by the main Agent directly; the
    retired visual development surface rejects new delegations."""

    for target_ref in ("asset:char:haaland", "lineup:argentina-trio"):
        delegated = DelegateToAgentInput.model_validate(
            {
                "role": "visual_development_agent",
                "target_refs": [target_ref],
                "task": "为角色和场景生成设计图",
            },
        )
        with pytest.raises(ValueError, match="not delegatable"):
            delegated.validate_contract(project_id="project-1")


def test_unknown_target_kinds_still_fail_the_contract() -> None:
    delegated = DelegateToAgentInput.model_validate(
        {
            "role": "source_intelligence_agent",
            "target_refs": ["storyline:act-1"],
            "task": "非法目标",
        },
    )
    with pytest.raises(ValueError, match="does not allow targetRef"):
        delegated.validate_contract(project_id="project-1")
