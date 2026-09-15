# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import json

import pytest

from domain.enums import SpecialistRole
from models import config as model_config
from services.file_agent_runtime.prompts import (
    FILE_AGENT_PROMPT_SPECS,
    load_file_agent_prompt,
    render_creator_system_prompt,
    tts_guidance,
)
from services.file_agent_runtime.subagents import (
    delegate_tool_manifest,
    specialist_system_prompt,
)
from services.project_files.models import Project

_INACTIVE_STATE_WORDS = {"已取消", "已禁用", "已删除", "review-disabled"}


def _active_prompt_texts() -> list[str]:
    from services.file_agent_runtime.workgraph_execution import (
        request_workgraph_tool_manifest,
    )

    project = Project.new(project_id="project-prompt-test", name="Prompt Test")
    texts = [
        render_creator_system_prompt(project_id=project.project_id),
        json.dumps(delegate_tool_manifest(), ensure_ascii=False),
        json.dumps(request_workgraph_tool_manifest(), ensure_ascii=False),
    ]
    texts.extend(
        specialist_system_prompt(
            role,
            project_id=project.project_id,
            project=project,
        )
        for role in (
            SpecialistRole.SOURCE_INTELLIGENCE,
            SpecialistRole.AI_EDITING_DIRECTOR,
        )
    )
    return texts


def test_active_prompts_do_not_describe_inactive_states() -> None:
    combined = "\n".join(_active_prompt_texts())
    for token in _INACTIVE_STATE_WORDS:
        assert token not in combined


def test_file_runtime_prompts_are_structured_files_with_workspace_schema() -> (
    None
):
    assert set(FILE_AGENT_PROMPT_SPECS) == {
        "creator_agent.system",
        "source_intelligence_agent.system",
        "ai_editing_director.system",
    }
    for prompt_id in FILE_AGENT_PROMPT_SPECS:
        raw = load_file_agent_prompt(prompt_id)
        assert raw.startswith("# 定位")
        assert "# 核心职责" in raw
        assert "# Workspace 基础 Schema" in raw
        assert "{{workspace_schema}}" in raw
        assert "# 限制" in raw
    for rendered in _active_prompt_texts():
        if rendered.startswith("# 定位"):
            assert "./project.json" in rendered
            if "你是 Creator 的素材理解 Agent" in rendered:
                assert "commit_source_intelligence 的工具 Schema" in rendered
                assert "PROJECT_JSON_SCHEMA=" not in rendered
            else:
                assert "PROJECT_JSON_SCHEMA=" in rendered


def test_visual_design_rules_are_reachable_and_name_real_reference_fields():
    # Keep the skill loading/schema contract, not exact prose or art direction.
    # Runtime readiness/reference semantics are tested at their write boundaries.
    prompt = load_file_agent_prompt("creator_agent.system")
    assert "`view_skill` 读取 `visual-asset-design`" in prompt
    skill = _visual_asset_design_skill()
    assert skill.startswith("---")
    assert "name: visual-asset-design" in skill
    for field in (
        "canonical_variant_id",
        "derived_from_variant_id",
        "reference_artifact_version_ids",
    ):
        assert field in skill


def _visual_asset_design_skill() -> str:
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    return (backend / "skills" / "visual-asset-design" / "SKILL.md").read_text(
        encoding="utf-8",
    )


def test_creator_duration_is_injected_from_the_active_video_model(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    prompt = render_creator_system_prompt(
        project_id="project-duration-test",
        workspace_schema="SCHEMA",
        external_skills="",
    )
    assert "happyhorse-1.1" in prompt
    assert "3–15 秒整数" in prompt
    assert "3 秒短段合法" in prompt
    assert "30 秒单段不合法" in prompt
    assert "不设置统一的 8–10 秒、10 秒或 15 秒默认值" in prompt
    assert "`[Image 1]`、`[Image 2]`" in prompt
    assert "storyboard 固定为第一张，因此是 `[Image 1]`" in prompt
    assert "你负责编写和维护 `video_prompt`" in prompt
    assert "R2V Specialist" not in prompt
    assert "不得把整片机械改成固定时长" in prompt
    assert "不设统一的 7 秒镜头上限" in prompt
    assert "`ops` 必须直接传原生 JSON 数组" in prompt

    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "doubao-seedance-2-5-260628",
    )
    prompt = render_creator_system_prompt(
        project_id="project-duration-test",
        workspace_schema="SCHEMA",
        external_skills="",
    )
    assert "4–30 秒整数" in prompt
    assert "30 秒长段" in prompt


@pytest.mark.parametrize(
    ("role", "retired_terms"),
    [
        (
            SpecialistRole.R2V_GENERATION_DIRECTOR,
            (
                "R2V Specialist",
                "r2v_generation_director",
                "Specialist 兜底",
                "为媒体执行委派",
            ),
        ),
        (
            SpecialistRole.VISUAL_DEVELOPMENT,
            (
                "visual_development_agent",
                "视觉开发 Specialist",
                "委派视觉开发",
            ),
        ),
    ],
)
def test_retired_specialists_have_no_delegation_or_prompt_surface(
    role,
    retired_terms,
) -> None:
    with pytest.raises(ValueError, match="no active prompt"):
        _specialist_prompt(role)
    combined = "\n".join(_active_prompt_texts())
    for term in (*retired_terms, "不可委派", "已停用"):
        assert term not in combined


def test_source_prompt_only_describes_visible_inputs_tools_and_outputs() -> (
    None
):
    prompt = load_file_agent_prompt("source_intelligence_agent.system")
    for hidden_mechanism in (
        "Runtime",
        "父 Agent",
        "另一个 VLM",
        "下游 Specialist",
    ):
        assert hidden_mechanism not in prompt
    assert "`read_project_file`" in prompt


def _set_image_model(monkeypatch, name: str) -> None:
    monkeypatch.setattr(model_config, "get_image_model_name", lambda: name)


def _set_video_model(monkeypatch, name: str) -> None:
    monkeypatch.setattr(model_config, "get_video_model_name", lambda: name)


def _specialist_prompt(role: SpecialistRole, project=None) -> str:
    return specialist_system_prompt(
        role,
        project_id="project-guidance-test",
        project=project,
        workspace_schema="SCHEMA",
    )


def test_image_model_guidance_follows_configured_model(
    monkeypatch,
) -> None:
    _set_video_model(monkeypatch, "wan2.7-r2v")
    _set_image_model(monkeypatch, "qwen-image-3.0")
    prompt = render_creator_system_prompt(
        project_id="project-guidance-test",
        workspace_schema="SCHEMA",
    )
    assert "qwen-image-3.0" in prompt
    assert "总数必须不超过 3" in prompt
    assert "400 拒绝" in prompt
    assert "总数不超过 5" not in prompt
    assert "{{image_model_guidance}}" not in prompt
    _set_image_model(monkeypatch, "gpt-image-2")
    prompt = render_creator_system_prompt(
        project_id="project-guidance-test",
        workspace_schema="SCHEMA",
    )
    assert "最多 16 张" in prompt


def test_video_model_guidance_switches_on_configured_model(
    monkeypatch,
) -> None:
    _set_video_model(monkeypatch, "happyhorse-1.1-r2v")
    prompt = render_creator_system_prompt(project_id="project-guidance-test")
    assert "happyhorse-1.1-r2v" in prompt
    assert "`[Image 1]`、`[Image 2]`" in prompt
    assert "storyboard 固定为第一张，因此是 `[Image 1]`" in prompt
    assert "不支持参考视频" in prompt
    assert "3–15 秒整数" in prompt
    assert "分辨率仅支持 720P/1080P" in prompt
    assert "{{video_model_guidance}}" not in prompt
    assert "{{video_duration_guidance}}" not in prompt
    _set_video_model(monkeypatch, "wan2.7-r2v")
    prompt = render_creator_system_prompt(project_id="project-guidance-test")
    assert "图片最多 5 张" in prompt
    assert "视频最多 5 个" in prompt
    assert "合计最多 5 个" in prompt
    # Every model now instructs the canonical form; only the rendered syntax
    # documented underneath it is model-specific.
    assert "`[Image 1]`、`[Image 2]`" in prompt
    assert "中文 Prompt 用“图1、图2" in prompt
    _set_video_model(monkeypatch, "wan3.0-video")
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    delegator = render_creator_system_prompt(
        project_id="project-guidance-test",
    )
    assert "Wan3.0" in delegator
    assert "2–30 秒" in delegator


def _tts(monkeypatch, *, model: str, configured: bool = True) -> None:
    cfg = tts_guidance.model_config
    monkeypatch.setattr(cfg, "is_tts_configured", lambda: configured)
    monkeypatch.setattr(cfg, "get_tts_model_name", lambda: model)


def test_unconfigured_tts_leaves_no_trace(monkeypatch) -> None:
    _tts(monkeypatch, model="qwen3-tts-flash", configured=False)
    prompt = _specialist_prompt(SpecialistRole.AI_EDITING_DIRECTOR)
    assert "tts" not in prompt.lower()
    assert "音色" not in prompt
    assert "{{tts_guidance}}" not in prompt
    delegator = render_creator_system_prompt(
        project_id="project-guidance-test",
        workspace_schema="SCHEMA",
    )
    # The base prompt legitimately says "旁白"; TTS markers prove a leak.
    assert "旁白与配音能力" not in delegator
    assert "音色" not in delegator


def test_model_with_system_voices_presents_design_as_optional(
    monkeypatch,
) -> None:
    _tts(monkeypatch, model="qwen3-tts-flash")
    delegator = render_creator_system_prompt(
        project_id="project-guidance-test",
        workspace_schema="SCHEMA",
    )
    # Voice enrollment is a mainline tool now: the design path must be
    # documented where the tool lives.
    assert "create_character_voice" in delegator
    assert "voicePrompt" in delegator
    assert "可选" in delegator
    assert "没有系统音色" not in delegator
    editing = _specialist_prompt(SpecialistRole.AI_EDITING_DIRECTOR)
    assert "tts_generation" in editing
    assert "默认音色" in editing
    # Real voice names are enumerated so no foreign namespace is invented.
    assert "Cherry" in editing


def test_model_without_system_voices_makes_design_a_prerequisite(
    monkeypatch,
) -> None:
    """cosyvoice-v3.5-plus can only speak through a created voice."""
    _tts(monkeypatch, model="cosyvoice-v3.5-plus")
    delegator = render_creator_system_prompt(
        project_id="project-guidance-test",
        workspace_schema="SCHEMA",
    )
    assert "没有系统音色" in delegator
    assert "create_character_voice" in delegator
    # The audition path needs a system voice, so it is not advertised.
    assert "sampleText 不可用" in delegator
    editing = _specialist_prompt(SpecialistRole.AI_EDITING_DIRECTOR)
    assert "没有系统音色" in editing
    assert "必须传已绑定音色的 characterRef" in editing
    assert "create_character_voice" in editing


def test_scenario_steers_how_the_voice_is_used(monkeypatch) -> None:
    _tts(monkeypatch, model="qwen3-tts-flash")

    def _project(scenario: str) -> Project:
        return Project.new(
            project_id="project-guidance-test",
            name="scenario probe",
            scenario=scenario,
        )

    drama = _specialist_prompt(
        SpecialistRole.AI_EDITING_DIRECTOR,
        _project("short_drama"),
    )
    assert "短剧" in drama
    assert "角色台词" in drama
    assert "不再叠加一份 TTS 台词" in drama
    edit = _specialist_prompt(
        SpecialistRole.AI_EDITING_DIRECTOR,
        _project("video_edit"),
    )
    assert "剪辑" in edit
    assert "旁白" in edit
    # Roles outside the media pipeline never hear about TTS.
    other = _specialist_prompt(SpecialistRole.SOURCE_INTELLIGENCE)
    assert "tts_generation" not in other


@pytest.mark.parametrize(
    ("video_model", "backend", "supports_reference_voice"),
    [
        ("wan3.0-video-prime", "wan", True),
        ("wan2.7-r2v", "wan", True),
        ("happyhorse-1.1-r2v", "happyhorse", False),
    ],
)
def test_native_dialogue_voice_guidance_matches_video_capability(
    monkeypatch,
    video_model,
    backend,
    supports_reference_voice,
) -> None:
    _tts(monkeypatch, model="qwen-audio-3.0-tts-flash")
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: video_model,
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: backend)
    prompt = render_creator_system_prompt(project_id="project-guidance-test")
    assert ("当前视频模型支持参考音色" in prompt) is supports_reference_voice
    assert (
        "voice.sample_source_version_id" in prompt
    ) is supports_reference_voice
    # Lack of a system TTS voice must not disable native video dialogue.
    assert "通过 TTS 合成配音必须" in prompt


@pytest.mark.unit
def test_prompts_preserve_explicit_paid_image_ceiling() -> None:
    prompt = load_file_agent_prompt("creator_agent.system")
    for contract in (
        "显式媒体预算覆盖默认资产拆分",
        "共享设计图数 + R2V Element 数",
        "不能用共享设计 Artifact 冒充",
        "单张共享设计图预算例外",
        "不得建立 cast lineup 或创建第二个可调度视觉节点",
        "全部图片调用上限”不足以覆盖这些 storyboard",
    ):
        assert contract in prompt
