# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import json

from domain.enums import SpecialistRole
from services.file_agent_runtime.prompts import (
    FILE_AGENT_PROMPT_SPECS,
    load_file_agent_prompt,
    render_creator_system_prompt,
)
from services.file_agent_runtime.subagents import (
    delegate_tool_manifest,
    specialist_system_prompt,
)
from services.project_files.models import Project

_INACTIVE_STATE_WORDS = {
    "已取消",
    "已禁用",
    "已删除",
    "review-disabled",
}


def _active_prompt_texts() -> list[str]:
    project = Project.new(project_id="project-prompt-test", name="Prompt Test")
    texts = [
        render_creator_system_prompt(
            project_id=project.project_id,
        ),
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
        assert "# 标准流程" in raw
        assert "# 工具使用原则" in raw
        assert "# 限制" in raw

    for rendered in _active_prompt_texts():
        if rendered.startswith("# 定位"):
            assert "./project.json" in rendered
            assert "./assets/source-intelligence/*" in rendered
            assert "PROJECT_JSON_SCHEMA=" in rendered


def test_creator_asset_flow_is_conditional_and_uses_visible_message_language() -> (
    None
):
    prompt = load_file_agent_prompt("creator_agent.system")
    assert "处理本轮上传素材（如有）" in prompt
    assert "没有该段落时" in prompt
    assert "本轮已入库素材" in prompt
    assert "CURRENT_REQUEST_ASSET_VERSION_REFS" not in prompt


def test_creator_owns_timeline_element_planning() -> None:
    prompt = load_file_agent_prompt("creator_agent.system")
    for responsibility in (
        "Timeline Element",
        "creation.type=r2v/edit/overlay/transition/audio",
        "单个 R2V Element 不超过 15 秒",
        "elements_at",
        "jq_project",
    ):
        assert responsibility in prompt
    assert "结构完成后才进入视觉和媒体生产" in prompt
    assert "完整 Project 根对象" in prompt
    assert "jsonArgs" in prompt
    assert "`updated_at` 由 Runtime 自动维护" in prompt
    assert "content_type=pet_video" in prompt
    assert "overlay_kind=pet_os" in prompt
    assert "x=0.5, y=0.5" in prompt


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
    # Annotation text stays banned by default…
    assert (
        "No panel numbers, no captions, no labels, no subtitles, "
        "no watermarks, no annotation text in the image."
    ) in prompt
    # …while diegetic text (jersey numbers, signage) is declared explicitly
    # and carried through an exception-style clause.
    assert "画内叙事文字" in prompt
    assert "No text except" in prompt
    assert "不得因禁字规则而丢失" in prompt
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
    assert "先按真实场景和主要行为形成第一层自然分段" in prompt
    assert "ceil(durationMs / 90000)" in prompt
    assert "作为建议目标数量" in prompt
    assert "最终数量以真实可见边界为准" in prompt
    assert "画面状态连续稳定时保留自然长段" in prompt
    assert "大量边界同时落在整分钟、半分钟或其他固定刻度" in prompt
    assert "主体与可见外观；动作/状态及其阶段" in prompt
    assert "接近/准备 → 动作发生 → 动作完成或离开" in prompt
    assert "核心主体、对象和动作必须在该时间范围内实际可见" in prompt
    assert "不制造虚假的毫秒精度" in prompt
    assert "多条事件不应呈固定时间间隔" in prompt
    assert "min(12, max(4, ceil(durationMs / 600000)))" in prompt
    assert "不把整段场景当作一个窄事件" in prompt
    assert "30000ms 是窄事件的最大跨度，不是推荐长度" in prompt
    assert "时间一致的支持" in prompt
    assert "相同场景、对象和动作的时间顺序是否一致" in prompt
    assert "# 提交前自检" in prompt
    assert "最终产物限定为素材理解及其写入验证结果" in prompt
    assert "`jq_project`" not in prompt
    assert "15–60 秒" not in prompt
    assert "完整有效的 JSON" in prompt


def test_source_prompt_only_describes_visible_inputs_tools_and_outputs() -> (
    None
):
    prompt = load_file_agent_prompt("source_intelligence_agent.system")
    for hidden_mechanism in (
        "Runtime",
        "父 Agent",
        "另一个 VLM",
        "模型回合",
        "下游 Specialist",
        "工具不会再次调用 VLM",
    ):
        assert hidden_mechanism not in prompt
    for visible_tool in (
        "`read_project`",
        "`read_project_file`",
        "`transcribe_source_audio`",
        "`commit_source_intelligence`",
    ):
        assert visible_tool in prompt


def test_ai_editing_director_requires_pet_inner_monologue_not_action_labels() -> (
    None
):
    prompt = load_file_agent_prompt("ai_editing_director.system")
    for field in ("overlay_kind=pet_os", "文案", "`vibe`", "绝对 span"):
        assert field in prompt
    assert "不是镜头标题、动作标签或客观摘要" in prompt
    assert "不再使用相对某个内部对象" in prompt
    assert "多个选择就是多个 Element" in prompt
    assert (
        "round((source_out_tick - source_in_tick) / playback_rate)" in prompt
    )
    assert "不得把 `source_in_tick` 复制到 `span.start_tick`" in prompt
    assert "第一段 `span.start_tick=0`" in prompt
    assert "jsonArgs.elements" in prompt
    assert "不是可选项" in prompt
