# -*- coding: utf-8 -*-
# flake8: noqa: E501

from __future__ import annotations

import pytest

from domain.enums import SpecialistRole
from models import config as model_config
from services.file_agent_runtime.subagents import specialist_system_prompt

_IMAGE_ROLES = (
    SpecialistRole.VISUAL_DEVELOPMENT,
    SpecialistRole.R2V_GENERATION_DIRECTOR,
)


def _render(role: SpecialistRole) -> str:
    return specialist_system_prompt(
        role,
        project_id="project-guidance-test",
        workspace_schema="SCHEMA",
    )


@pytest.mark.parametrize("role", _IMAGE_ROLES)
def test_qwen_image_model_injects_three_reference_budget(
    monkeypatch,
    role,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_image_model_name",
        lambda: "qwen-image-3.0",
    )
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v",
    )
    prompt = _render(role)
    assert "qwen-image-3.0" in prompt
    assert "总数必须不超过 3" in prompt
    assert "400 拒绝" in prompt
    assert "总数不超过 5" not in prompt
    assert "{{image_model_guidance}}" not in prompt


@pytest.mark.parametrize("role", _IMAGE_ROLES)
def test_openai_image_model_uses_official_budget(monkeypatch, role) -> None:
    monkeypatch.setattr(
        model_config,
        "get_image_model_name",
        lambda: "gpt-image-2",
    )
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v",
    )
    prompt = _render(role)
    assert "gpt-image-2" in prompt
    assert "最多 16 张" in prompt
    assert "{{image_model_guidance}}" not in prompt
