# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Narration guidance must describe exactly the configured model's abilities.

The injected text is the agent's only source of truth about speech: promising a
system voice a model does not have makes it retry synthesis that can never
succeed, and hiding the "design a voice first" prerequisite has the same
effect. So each configuration state is asserted separately.
"""

from __future__ import annotations

from domain.enums import SpecialistRole
from services.file_agent_runtime.prompts import (
    render_creator_system_prompt,
    tts_guidance,
)
from services.file_agent_runtime.subagents import specialist_system_prompt
from services.project_files.models import Project


def _render(role: SpecialistRole, project=None) -> str:
    return specialist_system_prompt(
        role,
        project_id="project-voice-guidance-check",
        project=project,
        workspace_schema="SCHEMA",
    )


def _configure(monkeypatch, *, model: str, configured: bool = True) -> None:
    monkeypatch.setattr(
        tts_guidance.model_config,
        "is_tts_configured",
        lambda: configured,
    )
    monkeypatch.setattr(
        tts_guidance.model_config,
        "get_tts_model_name",
        lambda: model,
    )


def test_unconfigured_tts_leaves_no_trace(monkeypatch) -> None:
    _configure(monkeypatch, model="qwen3-tts-flash", configured=False)
    for role in (
        SpecialistRole.VISUAL_DEVELOPMENT,
        SpecialistRole.AI_EDITING_DIRECTOR,
    ):
        prompt = _render(role)
        assert "tts" not in prompt.lower()
        assert "音色" not in prompt
        assert "旁白" not in prompt
        assert "{{tts_guidance}}" not in prompt
    delegator = render_creator_system_prompt(
        project_id="project-voice-guidance-check",
        workspace_schema="SCHEMA",
    )
    # The base delegator prompt legitimately says "旁白" when planning
    # dialogue, so only TTS-specific markers prove the section leaked.
    assert "旁白与配音能力" not in delegator
    assert "音色" not in delegator
    assert "tts" not in delegator.lower()
    assert "{{tts_guidance}}" not in delegator


def test_model_with_system_voices_presents_design_as_optional(
    monkeypatch,
) -> None:
    _configure(monkeypatch, model="qwen3-tts-flash")

    visual = _render(SpecialistRole.VISUAL_DEVELOPMENT)
    assert "create_character_voice" in visual
    assert "voicePrompt" in visual
    assert "可选" in visual
    assert "没有系统音色" not in visual

    editing = _render(SpecialistRole.AI_EDITING_DIRECTOR)
    assert "tts_generation" in editing
    assert "默认音色" in editing
    assert "没有系统音色" not in editing
    # The guidance must enumerate the real voice names so the agent cannot
    # invent one from another provider's namespace.
    assert "Cherry" in editing
    assert "Serena" in editing

    delegator = render_creator_system_prompt(
        project_id="project-voice-guidance-check",
        workspace_schema="SCHEMA",
    )
    assert "ai_editing_director" in delegator
    assert "没有系统音色" not in delegator


def test_model_without_system_voices_makes_design_a_prerequisite(
    monkeypatch,
) -> None:
    """cosyvoice-v3.5-plus can only speak through a created voice."""

    _configure(monkeypatch, model="cosyvoice-v3.5-plus")

    visual = _render(SpecialistRole.VISUAL_DEVELOPMENT)
    assert "没有系统音色" in visual
    assert "必须先创建专属音色" in visual
    assert "voicePrompt" in visual
    # The audition path needs a system voice, so it must not be advertised.
    assert "sampleText 不可用" in visual

    editing = _render(SpecialistRole.AI_EDITING_DIRECTOR)
    assert "没有系统音色" in editing
    assert "必须传已绑定音色的 characterRef" in editing

    delegator = render_creator_system_prompt(
        project_id="project-voice-guidance-check",
        workspace_schema="SCHEMA",
    )
    assert "没有系统音色" in delegator
    assert "先委派 visual_development_agent" in delegator


def test_scenario_steers_how_the_voice_is_used(monkeypatch) -> None:
    _configure(monkeypatch, model="qwen3-tts-flash")

    def _project(scenario: str) -> Project:
        return Project.new(
            project_id="project-voice-guidance-check",
            name="scenario probe",
            scenario=scenario,
        )

    drama = _render(
        SpecialistRole.AI_EDITING_DIRECTOR,
        _project("short_drama"),
    )
    assert "短剧" in drama
    assert "角色台词" in drama

    edit = _render(SpecialistRole.AI_EDITING_DIRECTOR, _project("video_edit"))
    assert "剪辑" in edit
    assert "旁白" in edit


def test_other_roles_never_reference_tts(monkeypatch) -> None:
    _configure(monkeypatch, model="qwen3-tts-flash")
    prompt = _render(SpecialistRole.SOURCE_INTELLIGENCE)
    assert "tts_generation" not in prompt
