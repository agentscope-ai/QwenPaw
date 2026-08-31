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
    project = Project.new(project_id="project-prompt-test", name="Prompt Test")
    texts = [
        render_creator_system_prompt(project_id=project.project_id),
        json.dumps(delegate_tool_manifest(), ensure_ascii=False),
    ]
    texts.extend(
        specialist_system_prompt(
            role,
            project_id=project.project_id,
            project=project,
        )
        for role in (
            SpecialistRole.SOURCE_INTELLIGENCE,
            SpecialistRole.VISUAL_DEVELOPMENT,
            SpecialistRole.R2V_GENERATION_DIRECTOR,
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
        "visual_development_agent.system",
        "r2v_generation_director.system",
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
            assert "PROJECT_JSON_SCHEMA=" in rendered


def test_creator_asset_flow_is_conditional_and_uses_visible_message_language() -> (
    None
):
    prompt = load_file_agent_prompt("creator_agent.system")
    assert "处理本轮上传素材（如有）" in prompt
    assert "本轮已入库素材" in prompt
    assert "CURRENT_REQUEST_ASSET_VERSION_REFS" not in prompt


def test_creator_owns_timeline_element_planning() -> None:
    prompt = load_file_agent_prompt("creator_agent.system")
    for responsibility in (
        "Timeline Element",
        "creation.type=r2v/t2v/i2v/s2v/edit/overlay/transition/audio",
        "单个 R2V Element 的时长必须符合本轮注入的当前精确视频模型能力上限",
        "jq_project",
    ):
        assert responsibility in prompt
    assert "结构完成后才进入视觉和媒体生产" in prompt
    assert "Runtime 自动选择最新 Project 快照并维护受保护字段" in prompt
    assert "content_type=pet_video" in prompt
    assert "台词卡 Overlay Element" in prompt


def test_visual_prompt_reuses_an_existing_variant_sheet_by_default() -> None:
    prompt = load_file_agent_prompt("visual_development_agent.system")
    assert "一图一 Variant（硬性规则）" in prompt
    assert "生成前去重（硬性规则）" in prompt
    assert "generated_artifact_version_ids" in prompt
    assert "重复委派、继续执行或重新进入同一目标不等于用户要求重做" in prompt


def test_r2v_prompt_requires_text_free_storyboards_without_blind_retry() -> (
    None
):
    prompt = load_file_agent_prompt("r2v_generation_director.system")
    assert "分镜图画面纯净性（硬性规则）" in prompt
    assert (
        "No panel numbers, no captions, no labels, no subtitles, "
        "no watermarks, no annotation text in the image."
    ) in prompt
    # Diegetic text (jersey numbers, signage) rides an exception clause.
    assert "画内叙事文字" in prompt
    assert "No text except" in prompt
    assert "不要在未看到图片内容时臆测检查结果" in prompt
    assert "不要因此自动重复调用 `image_generation`" in prompt


def test_source_prompt_requires_outer_vlm_timeline_and_controlled_commit() -> (
    None
):
    prompt = load_file_agent_prompt("source_intelligence_agent.system")
    assert "直接观察本轮提供的原生图片或视频" in prompt
    assert "至少覆盖 90% 时长" in prompt
    assert "整数毫秒半开区间 `[startMs,endMs)`" in prompt
    assert "transcribe_source_audio" in prompt
    assert "commit_source_intelligence" in prompt
    assert "不使用等长时间网格生成 shots" in prompt
    assert "ceil(durationMs / 90000)" in prompt
    assert "最终数量以真实可见边界为准" in prompt
    assert "大量边界同时落在整分钟、半分钟或其他固定刻度" in prompt
    assert "不制造虚假的毫秒精度" in prompt
    assert "min(12, max(4, ceil(durationMs / 600000)))" in prompt
    assert "30000ms 是窄事件的最大跨度，不是推荐长度" in prompt
    assert "# 提交前自检" in prompt
    assert "`jq_project`" not in prompt
    assert "完整有效的 JSON" in prompt


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


def test_ai_editing_director_requires_pet_inner_monologue_not_action_labels() -> (
    None
):
    prompt = load_file_agent_prompt("ai_editing_director.system")
    for field in ("宠物 OS 台词卡", "文案", "`vibe`", "绝对 span"):
        assert field in prompt
    assert "不是镜头标题、动作标签或客观摘要" in prompt
    assert (
        "round((source_out_tick - source_in_tick) / playback_rate)" in prompt
    )
    assert "不得把 `source_in_tick` 复制到 `span.start_tick`" in prompt
    assert "第一段 `span.start_tick=0`" in prompt


_IMAGE_ROLES = (
    SpecialistRole.VISUAL_DEVELOPMENT,
    SpecialistRole.R2V_GENERATION_DIRECTOR,
)


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


@pytest.mark.parametrize("role", _IMAGE_ROLES)
def test_image_model_guidance_follows_configured_model(
    monkeypatch,
    role,
) -> None:
    _set_video_model(monkeypatch, "wan2.7-r2v")
    _set_image_model(monkeypatch, "qwen-image-3.0")
    prompt = _specialist_prompt(role)
    assert "qwen-image-3.0" in prompt
    assert "总数必须不超过 3" in prompt
    assert "400 拒绝" in prompt
    assert "总数不超过 5" not in prompt
    assert "{{image_model_guidance}}" not in prompt
    _set_image_model(monkeypatch, "gpt-image-2")
    prompt = _specialist_prompt(role)
    assert "最多 16 张" in prompt


def test_video_model_guidance_switches_on_configured_model(
    monkeypatch,
) -> None:
    _set_video_model(monkeypatch, "happyhorse-1.1-r2v")
    prompt = _specialist_prompt(SpecialistRole.R2V_GENERATION_DIRECTOR)
    assert "happyhorse-1.1-r2v" in prompt
    assert "[Image N]" in prompt
    assert "storyboard 是第一参考，即 `[Image 1]`" in prompt
    assert "不支持参考视频" in prompt
    assert "{{video_model_guidance}}" not in prompt
    _set_video_model(monkeypatch, "wan2.7-r2v")
    prompt = _specialist_prompt(SpecialistRole.R2V_GENERATION_DIRECTOR)
    assert "图片最多 5 张" in prompt
    assert "视频最多 5 个" in prompt
    assert "合计最多 5 个" in prompt
    assert "[Image N]" not in prompt
    _set_video_model(monkeypatch, "wan3.0-video")
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    specialist = _specialist_prompt(SpecialistRole.R2V_GENERATION_DIRECTOR)
    delegator = render_creator_system_prompt(
        project_id="project-guidance-test",
    )
    for rendered in (specialist, delegator):
        assert "Wan3.0" in rendered
        assert "2–30 秒" in rendered


def _tts(monkeypatch, *, model: str, configured: bool = True) -> None:
    cfg = tts_guidance.model_config
    monkeypatch.setattr(cfg, "is_tts_configured", lambda: configured)
    monkeypatch.setattr(cfg, "get_tts_model_name", lambda: model)


def test_unconfigured_tts_leaves_no_trace(monkeypatch) -> None:
    _tts(monkeypatch, model="qwen3-tts-flash", configured=False)
    for role in (
        SpecialistRole.VISUAL_DEVELOPMENT,
        SpecialistRole.AI_EDITING_DIRECTOR,
    ):
        prompt = _specialist_prompt(role)
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
    visual = _specialist_prompt(SpecialistRole.VISUAL_DEVELOPMENT)
    assert "create_character_voice" in visual
    assert "voicePrompt" in visual
    assert "可选" in visual
    assert "没有系统音色" not in visual
    editing = _specialist_prompt(SpecialistRole.AI_EDITING_DIRECTOR)
    assert "tts_generation" in editing
    assert "默认音色" in editing
    # Real voice names are enumerated so no foreign namespace is invented.
    assert "Cherry" in editing
    delegator = render_creator_system_prompt(
        project_id="project-guidance-test",
        workspace_schema="SCHEMA",
    )
    assert "没有系统音色" not in delegator


def test_model_without_system_voices_makes_design_a_prerequisite(
    monkeypatch,
) -> None:
    """cosyvoice-v3.5-plus can only speak through a created voice."""
    _tts(monkeypatch, model="cosyvoice-v3.5-plus")
    visual = _specialist_prompt(SpecialistRole.VISUAL_DEVELOPMENT)
    assert "没有系统音色" in visual
    assert "必须先创建专属音色" in visual
    # The audition path needs a system voice, so it is not advertised.
    assert "sampleText 不可用" in visual
    editing = _specialist_prompt(SpecialistRole.AI_EDITING_DIRECTOR)
    assert "没有系统音色" in editing
    assert "必须传已绑定音色的 characterRef" in editing
    delegator = render_creator_system_prompt(
        project_id="project-guidance-test",
        workspace_schema="SCHEMA",
    )
    assert "先委派 visual_development_agent" in delegator


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
    edit = _specialist_prompt(
        SpecialistRole.AI_EDITING_DIRECTOR,
        _project("video_edit"),
    )
    assert "剪辑" in edit
    assert "旁白" in edit
    # Roles outside the media pipeline never hear about TTS.
    other = _specialist_prompt(SpecialistRole.SOURCE_INTELLIGENCE)
    assert "tts_generation" not in other
