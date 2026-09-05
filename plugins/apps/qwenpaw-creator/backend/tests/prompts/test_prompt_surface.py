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
        "单个 R2V Element 的时长必须落在「当前视频模型时长要求」内",
        "不设 Creator 全局上限",
        "jq_project",
    ):
        assert responsibility in prompt
    assert "结构完成后才进入视觉和媒体生产" in prompt
    assert "Runtime 自动选择最新 Project 快照并维护受保护字段" in prompt
    assert "content_type=pet_video" in prompt
    assert "台词卡 Overlay Element" in prompt


def _visual_asset_design_skill() -> str:
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    return (backend / "skills" / "visual-asset-design" / "SKILL.md").read_text(
        encoding="utf-8",
    )


def test_creator_owns_the_visual_asset_structural_contract() -> None:
    prompt = load_file_agent_prompt("creator_agent.system")
    assert "### 视觉资产结构合同" in prompt
    assert "一图一 Variant（硬性）" in prompt
    assert "生成前去重（硬性）" in prompt
    assert "generated_artifact_version_ids" in prompt
    assert "重复进入同一目标不等于用户要求重做" in prompt
    assert "`required_variant_ids` 是计划合同" in prompt
    # The craft doctrine is loaded on demand, so the mandatory skill read
    # must be spelled out where the contract lives and where repair starts.
    assert "`view_skill` 读取 `visual-asset-design`" in prompt
    assert "visual-asset-design" in prompt


def test_visual_asset_design_skill_carries_the_migrated_doctrine() -> None:
    skill = _visual_asset_design_skill()
    assert skill.startswith("---")
    assert "name: visual-asset-design" in skill
    for requirement in (
        "电影感艺术身份板",
        "大型、略偏离中心的英雄全身视角",
        "不得重叠、融合、堆叠",
        "小型轮廓研究区",
        "小型表情研究区",
        "小型细节研究区",
        "名称、角色、核心情绪、视觉标志",
        "相同脸部与比例",
        "规避图片审核误判（硬性）",
        "构图与镜头语言",
    ):
        assert requirement in skill
    assert "不得同时要求 `clear spatial labels` 与 `no text`" in skill
    assert "无文字视觉拓扑" in skill
    # The cost contracts stay inline in the creator prompt, not the skill.
    assert "一图一 Variant" in skill  # referenced, authoritative copy inline
    assert "以主 Agent 系统提示中的结构" in skill


def test_creator_compiles_dense_action_nodes_without_uniform_timestamps() -> (
    None
):
    prompt = load_file_agent_prompt("creator_agent.system")
    assert "professional-media-prompts" in prompt
    assert "动作密集、蒙太奇" in prompt
    assert "6–15 个短动作节点" in prompt
    assert "3–6 个核心电影段落" in prompt
    assert "10 秒内的 12 个节点" in prompt
    assert "机械分配 12 个小数时间戳" in prompt
    assert "不为每格/每个 Shot 设置 2–4 秒建议区间或 5 秒硬上限" in prompt
    assert "单个常规 Shot 不超过 5 秒" not in prompt
    assert "3–4 秒极短段通常只承载一个占主导的连续微动作" in prompt
    assert "专业完整不等于重复冗长" in prompt
    assert "每一个分镜格内部画框" in prompt
    assert "正方形网格（N 列×N 行）" in prompt
    assert "只有列数等于行数时单格才等于项目画幅" in prompt


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
    assert "你是 `video_prompt` 的唯一作者" in prompt
    assert "R2V Specialist" not in prompt
    assert "禁止套用“每段固定 5 Shot”" in prompt
    assert "不设统一的 7 秒 Shot 上限" in prompt
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


def test_active_surfaces_never_mention_the_retired_r2v_specialist() -> None:
    combined = "\n".join(_active_prompt_texts())
    assert "R2V Specialist" not in combined
    assert "r2v_generation_director" not in combined
    assert "不可委派" not in combined
    assert "已停用" not in combined
    # Media execution belongs to the scheduler, not any specialist; text
    # implying such a specialist exists is retired-R2V residue.
    assert "Specialist 兜底" not in combined
    assert "为媒体执行委派" not in combined


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


def test_r2v_specialist_is_not_an_active_delegation_surface() -> None:
    with pytest.raises(ValueError, match="no active prompt"):
        _specialist_prompt(SpecialistRole.R2V_GENERATION_DIRECTOR)


def test_visual_development_is_not_an_active_delegation_surface() -> None:
    with pytest.raises(ValueError, match="no active prompt"):
        _specialist_prompt(SpecialistRole.VISUAL_DEVELOPMENT)


def test_active_surfaces_never_mention_the_retired_visual_specialist() -> None:
    combined = "\n".join(_active_prompt_texts())
    assert "visual_development_agent" not in combined
    assert "视觉开发 Specialist" not in combined
    assert "委派视觉开发" not in combined


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
    edit = _specialist_prompt(
        SpecialistRole.AI_EDITING_DIRECTOR,
        _project("video_edit"),
    )
    assert "剪辑" in edit
    assert "旁白" in edit
    # Roles outside the media pipeline never hear about TTS.
    other = _specialist_prompt(SpecialistRole.SOURCE_INTELLIGENCE)
    assert "tts_generation" not in other
