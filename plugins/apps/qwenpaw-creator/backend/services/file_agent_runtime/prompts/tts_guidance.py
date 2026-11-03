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

Above those capability states sits one preference: the video model speaks.
Dialogue and voice-over belong in ``creation.narrative`` / ``video_prompt`` and
come back inside the rendered clip.  Synthesizing narration is the exception,
reserved for two cases -- a voice sample the user supplied, and footage that
cannot speak at all (motion carriers, edits over existing material).  Real
output made that call: a TTS voice laid over generated video sounded worse than
the native track and could double it, so this guidance states the preference
first instead of advertising the capability first.

Getting this wrong in either direction is expensive: promising a capability the
model lacks makes the agent fail mid-run, and hiding a prerequisite makes it
retry synthesis that can never succeed.
"""

from __future__ import annotations

from domain.enums import SpecialistRole
from models import config as model_config
from models.tts_capabilities import require_capability
from models.video_capabilities import video_reference_voice_support

_SCENARIO_USES = {
    "short_drama": (
        "本项目是短剧：台词与旁白默认由视频模型原生说出。已安排视频原生对白时"
        "保留角色台词、口型与原声，不再叠加一份 TTS 台词。只有明确采用后期配音"
        "或需要画外解说的区间才单独合成音频，并按说话者和对应画面分段。"
    ),
    "video_edit": "本项目是剪辑：画面不会自行发声，旁白用 `tts_generation` 分段合成后混入。",
    "general": (
        "默认让视频模型原生说出台词与旁白；只有用户提供了自己的音色文件，或该"
        "区间画面本身不能发声（动效载体、既有素材剪辑）时，才用 TTS 合成。"
    ),
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
        "- 台词与旁白优先由视频模型原生生成：把逐字台词、画外旁白、说话者与声音"
        "来源直接写进该 Element 的 `creation.narrative` 与 `video_prompt`，让人声"
        "随视频一起生成，不再为同一区间另建音频轨。**只有两种例外才允许 TTS "
        "合成**：① 用户提供了自己的音色音频文件，据此复刻角色音色；② 该区间的"
        "画面本身不会自发声——`motion_clip` 等动效载体、既有素材剪辑，以及需要"
        "外部驱动音频才能开口的 s2v 数字人。不要因为原生人声不够理想就改走 "
        "TTS。",
        "- 落在上述例外里时才委派 ai_editing_director 到 timeline:<timelineId>："
        "它可把旁白文本合成为音频资产并创建 creation.type=audio、role=narration "
        "的 Element，写回后成片由系统自动重新合成；要求按镜头/语义分段生成、每段"
        " span 对齐对应画面。自带人声的区间（creation.type=s2v 的数字人口播、"
        "已经安排视频原生人声的 R2V 区间）不安排旁白。",
    ]
    if capability.has_system_voices:
        lines.append(
            "- 你可以用 `create_character_voice` 为 character 实体创建专属"
            "音色（可选增强）：targetRef 传目标角色的 exact asset:<entityId>。"
            "两条路径——传 voicePrompt 按角色设定直接设计音色（无需样本，"
            "优先用它），或传 sampleSourceVersionId / sampleText 从音频样本"
            "复刻。用户自己上传了音色文件时走复刻路径，这份音色才是 TTS 旁白"
            "允许使用的那一个；跨镜头保持声音身份、给视频模型提供参考音色时"
            "也用同一个工具。",
        )
    else:
        lines.append(
            f"- 当前语音模型 {capability.model} 没有系统音色：通过 TTS 合成配音必须"
            "先有角色专属音色。先用 `create_character_voice` 按角色设定设计"
            "音色并绑定到 character 实体（该模型不支持系统音色试音，"
            "sampleText 不可用；只能用 voicePrompt 设计，或用已有音频 "
            "version 复刻），再委派台词或旁白生成，否则合成会失败。",
        )
    lines.append(
        "- voicePrompt 要从该角色已有的设定推导（年龄、性别、性格、语速、"
        "音质等），例如「低沉沙哑的中年男声，语速缓慢，带疲惫感」；同一角色"
        "重新创建会替换旧绑定。创建后用 read_project 确认 voice 已绑定到"
        "目标实体；该角色的 tts_generation 传 characterRef 即自动沿用此音色。",
    )
    if video_reference_voice_support(
        model_config.get_video_model_name(),
        model_config.get_video_backend(),
    ):
        lines.append(
            "- 当前视频模型支持参考音色。需要跨镜头、跨集保持角色声音时，"
            "先为说话角色创建并确认专属音色，确认 voice.sample_source_version_id "
            "指向真实可用的音频样本；已有符合要求的音色直接复用。R2V 同时引用"
            "该 character 和其形象参考图时，会自动携带绑定的音频样本。"
            "在 narrative/video_prompt 中写清逐字台词、说话者和轮流开口的表演；"
            "参考样本提供声音身份，不替代本段台词，也不需要把同一句台词再作为"
            "独立 TTS 叠到原生对白上。演唱与说话分别说明，普通 TTS 不冒充演唱。",
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
    if role is SpecialistRole.AI_EDITING_DIRECTOR:
        return _editing_guidance(capability, scenario)
    return ""


def _editing_guidance(capability, scenario: str) -> str:
    lines = [
        "\n# 旁白与配音\n",
        f"- {_scenario_line(scenario)}",
        "- 先判画面能不能自己发声：R2V/T2V/I2V 区间的台词与旁白由视频模型原生"
        "生成（逐字写进该 Element 的 narrative 与 video_prompt），不要为同一区"
        "间再合成一份 TTS 音频。只有两种例外才用 `tts_generation`：① 用户提供了"
        "自己的音色音频文件；② 该区间画面不会自发声——`motion_clip` 等动效载体、"
        "既有素材剪辑，以及需要外部驱动音频才能开口的 s2v 数字人。两种都不适用"
        "时如实说明该段没有旁白，不要用系统音色硬凑。",
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
            "音色，先汇报阻塞，由 Creator 主 Agent 用 create_character_voice "
            "设计音色。",
        )
    lines.append(
        "- 属于上述例外、确实要合成时，旁白必须按镜头或语义段落拆分：每段单独调"
        "一次 tts_generation，对应一个独立的 audio Element，span 只覆盖它解说的"
        "画面区间；禁止用一条音频贯穿整条 Timeline。每段文本长度要与画面时长匹配"
        "（中文语速约每秒 4–5 字），生成后用返回的 durationSeconds 校准 span。",
    )
    lines.append(
        "- 自带人声的区间不安排旁白：数字人口播（creation.type=s2v）的 span "
        "内视频自身就是人声；已安排原生人声台词的 R2V/T2V/I2V 区间同理"
        "（生成视频会原生说出台词）。系统只对 s2v 区间与两条旁白相互重叠"
        "自动拒绝，R2V 等原生人声区间与旁白重叠不会被拦截，需你自行避免："
        "旁白 Element 的 span 不得与任何已安排原生人声的区间重叠，否则"
        "会出现视频已发声、旁白又重念一遍的双声。",
    )
    lines.append(
        "- 音频上片：用 jq_project 在目标 Timeline 创建 creation.type=audio 的"
        " Element，旁白必须设 role=narration（配乐用 role=bgm、音效用"
        " role=sfx），引用对应 version id；音频 Element 不需要 location，"
        "gain_db 调音量、pan 调声像。",
    )
    lines.append(
        "- 改配音/换音色某段旁白时，必须复用既有 audio Element：用 "
        "jq_project 把它的 source_asset_version_id 换绑成新合成的 "
        "version（或先删除旧 Element 再建）；禁止在同一区间再叠一条 "
        "narration——两条旁白重叠会变成双声同时播放，系统会直接拒绝写入。",
    )
    lines.append(
        "- 合成时旁白按 span 混入成片，旁白播放区间内画面原声会自动压低，"
        "两者不会互相干扰；若某段原声本身是内容重点（台词、现场声），"
        "该段不要安排旁白。",
    )
    return "\n".join(lines) + "\n"


__all__ = ["delegator_guidance", "specialist_guidance"]
