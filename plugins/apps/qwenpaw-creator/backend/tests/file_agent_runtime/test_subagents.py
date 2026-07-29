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
