# -*- coding: utf-8 -*-
"""Prompt contracts for explicit paid-media call ceilings."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from services.file_agent_runtime.prompts import load_file_agent_prompt
from services.file_agent_runtime.prompts import live_operation_guidance

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("prompt_name", "required_contracts"),
    (
        (
            "creator_agent.system",
            (
                "显式媒体预算覆盖默认资产拆分",
                "共享设计图数 + R2V Element 数",
                "不能用共享设计 Artifact 冒充",
            ),
        ),
        (
            "visual_development_agent.system",
            (
                "单张共享设计图预算例外",
                "不得在视觉开发范围调用第二次",
                "全部图片调用上限”不足以覆盖这些 storyboard",
            ),
        ),
    ),
)
def test_prompts_preserve_explicit_paid_image_ceiling(
    prompt_name: str,
    required_contracts: tuple[str, ...],
) -> None:
    prompt = load_file_agent_prompt(prompt_name)
    assert all(contract in prompt for contract in required_contracts)


def test_computer_use_manual_follows_the_loaded_plugin(tmp_path, monkeypatch):
    bundle = tmp_path / "computer-use"
    package = bundle / "computer_use"
    skill = bundle / "skills" / "computer_use" / "SKILL.md"
    package.mkdir(parents=True)
    skill.parent.mkdir(parents=True)
    module_file = package / "__init__.py"
    module_file.write_text("", encoding="utf-8")
    skill.write_text(
        "---\nname: computer_use\n---\nNative manual",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules,
        "computer_use",
        SimpleNamespace(__file__=str(module_file)),
    )
    monkeypatch.setattr(live_operation_guidance, "_skill_root", lambda: None)

    manual = live_operation_guidance.load_host_computer_use_manual()
    assert manual == "Native manual"
