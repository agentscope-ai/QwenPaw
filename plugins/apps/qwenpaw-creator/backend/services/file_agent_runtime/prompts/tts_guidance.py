# -*- coding: utf-8 -*-
"""Narration/voice prompt sections, built from the configured TTS model.

Speech guidance is injected only when it is actually true for the running
deployment. Three states matter and each produces different text:

- no TTS configured: nothing is injected, matching the tool registry which
  hides the TTS tools entirely;
- a model with system voices: narration can be synthesized right away, and
  designing a character voice is an optional enhancement;
- a model without system voices (the newest CosyVoice / Qwen-Audio models):
  nothing can be spoken until a character voice exists, so designing one is a
  hard prerequisite rather than an option.

Getting this wrong in either direction is expensive: promising a capability the
model lacks makes the agent fail mid-run, and hiding a prerequisite makes it
retry synthesis that can never succeed.
"""

from __future__ import annotations

from domain.enums import SpecialistRole
from models import config as model_config
from models.tts_capabilities import require_capability

_SCENARIO_USES = {
    "short_drama": (
        "本项目是短剧：角色台词用该角色的专属音色合成，与画面在 Timeline 上" "合成；旁白仅在需要解说时使用。"
    ),
    "video_edit": ("本项目是剪辑：以旁白/解说为主，按镜头分段合成后混入成片。"),
    "general": "按项目需要选择旁白解说或角色台词配音。",
}


def _scenario_line(scenario: str) -> str:
    return _SCENARIO_USES.get(scenario, _SCENARIO_USES["general"])


def delegator_guidance() -> str:
    """Narration section for the delegating Creator agent."""

    if not model_config.is_tts_configured():
        return ""
    capability = require_capability(model_config.get_tts_model_name())
    lines = [
        "\n# 旁白与配音能力\n",
        "- ai_editing_director 具备旁白生成能力：可把旁白文本合成为音频资产、"
        "创建 creation.type=audio 的 Element 并重新合成成片。旁白/配音需求直接"
        "委派它到 timeline:<timelineId>，在任务中写明旁白文案要求，并要求按"
        "镜头/语义分段生成、每段 span 对齐对应画面；自带人声的区间（如"
        " creation.type=s2v 的数字人口播）不安排旁白；不需要用户提供音频文件。",
    ]
    if capability.has_system_voices:
        lines.append(
            "- visual_development_agent 可为 character 实体创建专属音色"
            "（可选增强）：既能按角色设定直接设计音色，也能从音频样本复刻。"
            "需要角色专属声线时先委派它完成音色绑定，再委派台词或旁白生成。",
        )
    else:
        lines.append(
            f"- 当前语音模型 {capability.model} 没有系统音色：任何配音都必须"
            "先有角色专属音色。先委派 visual_development_agent 按角色设定设计"
            "音色并绑定到 character 实体，再委派台词或旁白生成，否则合成会失败。",
        )
    return "\n".join(lines) + "\n"


def specialist_guidance(
    role: SpecialistRole,
    scenario: str = "general",
) -> str:
    """Narration section for one specialist, or "" when TTS is unavailable."""

    if not model_config.is_tts_configured():
        return ""
    capability = require_capability(model_config.get_tts_model_name())
    if role is SpecialistRole.VISUAL_DEVELOPMENT:
        return _visual_guidance(capability, scenario)
    if role is SpecialistRole.AI_EDITING_DIRECTOR:
        return _editing_guidance(capability, scenario)
    return ""


def _visual_guidance(capability, scenario: str) -> str:
    lines = ["\n# 角色音色\n", f"- {_scenario_line(scenario)}"]
    if capability.has_system_voices:
        lines.append(
            "- `create_character_voice` 为 character 实体创建专属音色，属可选"
            "增强：characterRef 传目标角色的 exact asset:<entityId>。两条路径——"
            "传 voicePrompt 按角色设定直接设计音色（无需样本，优先用它），或传"
            " sampleSourceVersionId / sampleText 从音频样本复刻。",
        )
    else:
        lines.append(
            f"- 当前语音模型 {capability.model} 没有系统音色：需要配音的角色"
            "必须先创建专属音色，否则任何合成都会失败。用 "
            "`create_character_voice` 传 characterRef 与 voicePrompt 按角色"
            "设定设计音色（该模型不支持系统音色试音，sampleText 不可用；只能"
            "用 voicePrompt 设计，或用已有音频 version 复刻）。",
        )
    lines.append(
        "- voicePrompt 要从该角色已有的设定推导（年龄、性别、性格、语速、"
        "音质等），例如「低沉沙哑的中年男声，语速缓慢，带疲惫感」；同一角色"
        "重新创建会替换旧绑定。",
    )
    lines.append(
        "- 创建后用 read_project 确认 voice 已绑定到目标实体；该角色的 "
        "tts_generation 传 characterRef 即自动沿用此音色。",
    )
    return "\n".join(lines) + "\n"


def _editing_guidance(capability, scenario: str) -> str:
    lines = [
        "\n# 旁白与配音\n",
        f"- {_scenario_line(scenario)}",
    ]
    if capability.has_system_voices:
        lines.append(
            "- `tts_generation` 把一段台词或旁白文本合成为音频 "
            "SourceAssetVersion 并返回 exact version id；不传 characterRef 时"
            "使用配置的默认音色，传已绑定音色的 characterRef 时自动改用该角色"
            "的专属音色。",
        )
        lines.append(
            "- voice 参数只接受以下系统音色（其它名字会直接报错）："
            f"{'、'.join(capability.system_voices)}；省略时用默认音色。",
        )
    else:
        lines.append(
            f"- 当前语音模型 {capability.model} 没有系统音色：`tts_generation` "
            "必须传已绑定音色的 characterRef，否则合成失败。若目标角色还没有"
            "音色，先让 Creator 委派 visual_development_agent 设计音色。",
        )
    lines.append(
        "- 旁白必须按镜头或语义段落拆分：每段单独调一次 tts_generation，对应"
        "一个独立的 audio Element，span 只覆盖它解说的画面区间；禁止用一条"
        "音频贯穿整条 Timeline。每段文本长度要与画面时长匹配（中文语速约每秒"
        " 4–5 字），生成后用返回的 durationSeconds 校准 span。",
    )
    lines.append(
        "- 自带人声的区间不安排旁白：数字人口播（creation.type=s2v）的"
        " span 内视频自身就是人声，台词/现场声为内容重点的片段同理；"
        "旁白 Element 的 span 不得与这些区间重叠。",
    )
    lines.append(
        "- 音频上片：用 jq_project 在目标 Timeline 创建 creation.type=audio 的"
        " Element，引用对应 version id；音频 Element 不需要 location，"
        "gain_db 调音量、pan 调声像。",
    )
    lines.append(
        "- 合成时旁白按 span 混入成片，旁白播放区间内画面原声会自动压低，"
        "两者不会互相干扰；若某段原声本身是内容重点（台词、现场声），"
        "该段不要安排旁白。",
    )
    return "\n".join(lines) + "\n"


__all__ = ["delegator_guidance", "specialist_guidance"]
