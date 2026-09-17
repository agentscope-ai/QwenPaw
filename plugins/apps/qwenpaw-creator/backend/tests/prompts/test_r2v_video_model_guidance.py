# -*- coding: utf-8 -*-
# flake8: noqa: E501

from __future__ import annotations

from domain.enums import SpecialistRole
from models import config as model_config
from services.file_agent_runtime.subagents import specialist_system_prompt


def _render_r2v_prompt() -> str:
    return specialist_system_prompt(
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        project_id="project-guidance-test",
        workspace_schema="SCHEMA",
    )


def test_happyhorse_model_injects_image_n_citation_rules(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1-r2v",
    )
    prompt = _render_r2v_prompt()
    assert "# 当前视频模型要求" in prompt
    assert "happyhorse-1.1-r2v" in prompt
    assert "[Image N]" in prompt
    assert "storyboard 是第一参考，即 `[Image 1]`" in prompt
    assert "不支持参考视频" in prompt
    assert "{{video_model_guidance}}" not in prompt


def test_wan_model_keeps_generic_guidance(monkeypatch) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v",
    )
    prompt = _render_r2v_prompt()
    assert "# 当前视频模型要求" in prompt
    assert "wan2.7-r2v" in prompt
    assert "[Image N]" not in prompt
    assert "{{video_model_guidance}}" not in prompt
