# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Capability table for the supported DashScope speech-synthesis models.

The provider exposes two families that share nothing but the credential:

- ``qwen-tts``: synthesis over HTTP ``multimodal-generation``; voice cloning and
  voice design live on separate companion models (``-vc-`` / ``-vd-``) and are
  managed through ``qwen-voice-enrollment`` / ``qwen-voice-design``.
- ``cosyvoice``: synthesis over WebSocket; one ``voice-enrollment`` surface
  handles both cloning and design. Only ``cosyvoice-v3.5-plus`` ships no
  system voices, so it needs a created voice before anything can be spoken;
  every Qwen-Audio model publishes its own list, and a voice is accepted only
  by a model that publishes it: ``longanfengyue`` is a 3.0 id while
  ``longanfengyue_v3.1`` is a 3.1 id, 3.0's own list mixes bare ids with
  ``_v3.6`` ones, and 3.1 Plus publishes four names out of Flash's
  eighty-eight - so no model can borrow another model's list as its own.
  Only the Chinese and
  English names are recorded: ``3.1-flash`` publishes 51 further low-resource
  locales whose ids start with the model name, and a name missing from its
  model's list is refused locally before any call.

Keeping the differences in one table lets the rest of the backend ask
capability questions ("does this model have system voices?", "which model do I
enroll against?") instead of pattern-matching model names, and lets the UI ask
for a model list without duplicating the knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TtsFamily = Literal["qwen-tts", "cosyvoice"]
TtsTransport = Literal["http", "websocket"]
TtsProvider = Literal["bailian", "gateway"]


@dataclass(frozen=True, slots=True)
class TtsModelCapability:
    """What one synthesis model supports and which models it enrolls against."""

    model: str
    family: TtsFamily
    transport: TtsTransport
    label: str
    # System (preset) voices usable without creating a voice first.
    system_voices: tuple[str, ...]
    # Model that cloned voices are bound to; empty means "this model itself".
    clone_target: str = ""
    # Model that designed voices are bound to; empty means "not supported".
    design_target: str = ""
    # Providers this model is available on (protocol→provider mapping).
    providers: tuple[TtsProvider, ...] = ("bailian",)

    @property
    def has_system_voices(self) -> bool:
        return bool(self.system_voices)

    def clone_model(self) -> str:
        return self.clone_target or self.model

    def design_model(self) -> str:
        return self.design_target or self.model

    @property
    def supports_design(self) -> bool:
        return bool(self.design_target) or self.family == "cosyvoice"


# Only the current generation of each family is supported: older revisions add
# configuration surface without adding capability.
_QWEN_TTS_VOICES = (
    "Cherry",
    "Serena",
    "Ethan",
    "Chelsie",
    "Dylan",
    "Jada",
    "Sunny",
    "Nofish",
    "Marcus",
    "Roy",
)

# Qwen-Audio 3.0 Flash's published system voices. The ids are read straight
# from the provider's voice list: a voice outside its own model's list is
# rejected upstream, and the proxy reports that rejection as a retryable 502,
# which reads exactly like a broken route.
_QWEN_AUDIO_30_FLASH_VOICES = (
    "longanfengyue",
    "longanyuanfei",
    "longanlingxi",
    "longanxiaoxin",
    "longanhuan_v3.6",
    "longjielidou_v3.6",
    "longpaopao_v3.6",
    "longhuohuo_v3.6",
    "longchuanshu_v3.6",
    "loongmary",
    "loongeva_v3.6",
    "loongjohn",
)

# Qwen-Audio 3.0 Plus ships two flagship voices; the ids do not carry the
# ``_v3.6`` suffix that Flash's new voices use and are not interchangeable
# with the 3.1 names.
_QWEN_AUDIO_30_PLUS_VOICES = (
    "longanlingxin",
    "longanlufeng",
)

# Qwen-Audio 3.1 Plus ships four flagship voices; the ids carry the ``_v3.1``
# revision suffix and are not interchangeable with the 3.0 names.
_QWEN_AUDIO_31_PLUS_VOICES = (
    "longanlingxin_v3.1",
    "xunanchuan_v3.1",
    "longanhuan_v3.1",
    "longanfengyue_v3.1",
)

# Qwen-Audio 3.1 Flash publishes 139 voices. The 51 low-resource-language
# ones (``qwen-audio-3.1-tts-flash-<name>_<locale>``) are left out: Creator
# narration is Chinese or English, and the provider restricts those voices to
# their own locale, so listing them would offer 51 names that fail on any
# other text.
_QWEN_AUDIO_31_FLASH_VOICES = (
    # Multi-language and dialect voices: these four also carry the regional
    # dialects reachable through the instruction field.
    "longanhuan_v3.1",
    "longanlingxin_v3.1",
    "longanfengyue_v3.1",
    "xunanchuan_v3.1",
    # Premium Mandarin.
    "yuxiaoyun_v3.1",
    "qiaoxiaojiao_v3.1",
    "xiaxiaochen_v3.1",
    "anmingyuan_v3.1",
    "wenhuaiqing_v3.1",
    "anxiaolan_v3.1",
    "xieshurou_v3.1",
    "baiqinglan_v3.1",
    "xuyuyuan_v3.1",
    "anruorou_v3.1",
    "wenhuaizhi_v3.1",
    "xiaoxingzhi_v3.1",
    "guyunshu_v3.1",
    "huozhuoshi_v3.1",
    "yeqinghe_v3.1",
    "yunhuanhuan_v3.1",
    "xuxiaoqiao_v3.1",
    "baianran_v3.1",
    "xuyanchu_v3.1",
    "yezhiqing_v3.1",
    "andi_v3.1",
    "anyuqing_v3.1",
    "linxiaoling_v3.1",
    "longfeifei_v3.1",
    "longjing_v3.1",
    "longqiang_v3.1",
    "longyan_v3.1",
    "longxiaobai_v3.1",
    "longyue_v3.1",
    "longcheng_v3.1",
    "longlaotie_v3.1",
    "longshao_v3.1",
    "longshu_v3.1",
    "longze_v3.1",
    "longhao_v3.1",
    "longjin_v3.1",
    "longnan_v3.1",
    "longshuo_v3.1",
    "longtian_v3.1",
    "longxiaocheng_v3.1",
    "longke_v3.1",
    "loongbella_v3.1",
    # Premium English.
    "Emily_v3.1",
    "Luna_v3.1",
    "Eric_v3.1",
    "Luca_v3.1",
    "Abby_v3.1",
    "Annie_v3.1",
    "Ava_v3.1",
    "Beth_v3.1",
    "Betty_v3.1",
    "Cally_v3.1",
    "Cindy_v3.1",
    "Donna_v3.1",
    "Andy_v3.1",
    "Brian_v3.1",
    "David_v3.1",
    # Remaining system voices.
    "longanyuanfei_v3.1",
    "longjielidou_v3.1",
    "longanlingxi_v3.1",
    "longhuohuo_v3.1",
    "longyingtao_v3.1",
    "longanya_v3.1",
    "longwan_v3.1",
    "longxing_v3.1",
    "longhua_v3.1",
    "longhan_v3.1",
    "longanzhi_v3.1",
    "longzhe_v3.1",
    "longanyang_v3.1",
    "libai_v3.1",
    "longling_v3.1",
    "longniuniu_v3.1",
    "longshanshan_v3.1",
    "longpaopao_v3.1",
    "loongstella_v3.1",
    "longyuan_v3.1",
    "longmiao_v3.1",
    "longsanshu_v3.1",
    "longanli_v3.1",
    "longanwen_v3.1",
    "longanlang_v3.1",
    "longxiaoxia_v3.1",
    "longanchong_v3.1",
)

_CAPABILITIES: tuple[TtsModelCapability, ...] = (
    TtsModelCapability(
        model="qwen3-tts-flash",
        family="qwen-tts",
        transport="http",
        label="Qwen3 TTS Flash（系统音色，快速）",
        system_voices=_QWEN_TTS_VOICES,
        clone_target="qwen3-tts-vc-2026-01-22",
        design_target="qwen3-tts-vd-2026-01-26",
    ),
    TtsModelCapability(
        model="cosyvoice-v3.5-plus",
        family="cosyvoice",
        transport="websocket",
        label="CosyVoice 3.5 Plus（无系统音色，需先设计或复刻音色）",
        system_voices=(),
    ),
    TtsModelCapability(
        model="qwen-audio-3.0-tts-flash",
        family="cosyvoice",
        transport="websocket",
        label="Qwen-Audio 3.0 TTS Flash（12 个系统音色）",
        system_voices=_QWEN_AUDIO_30_FLASH_VOICES,
        providers=("bailian", "gateway"),
    ),
    # Listed after its cheaper sibling on purpose: a protocol switch that has
    # to pick a replacement model takes the first available one, and that
    # should never be the flagship.
    TtsModelCapability(
        model="qwen-audio-3.0-tts-plus",
        family="cosyvoice",
        transport="websocket",
        label="Qwen-Audio 3.0 TTS Plus（旗舰音色，2 个系统音色）",
        system_voices=_QWEN_AUDIO_30_PLUS_VOICES,
        providers=("bailian", "gateway"),
    ),
    # 3.1 speaks the same WebSocket protocol and enrolls voices through the
    # same ``voice-enrollment`` surface as 3.0; only the published voices are
    # new. Flash is listed before Plus - the order the interactive-video table
    # uses too, so merging the two tables never renumbers the choices the
    # configuration page renders in table order. 3.1 stays on the default
    # ``providers=("bailian",)``: the proxy has not published these names yet.
    TtsModelCapability(
        model="qwen-audio-3.1-tts-flash",
        family="cosyvoice",
        transport="websocket",
        label="Qwen-Audio 3.1 TTS Flash（88 个系统音色，实时快速）",
        system_voices=_QWEN_AUDIO_31_FLASH_VOICES,
    ),
    TtsModelCapability(
        model="qwen-audio-3.1-tts-plus",
        family="cosyvoice",
        transport="websocket",
        label="Qwen-Audio 3.1 TTS Plus（旗舰音色，4 个系统音色）",
        system_voices=_QWEN_AUDIO_31_PLUS_VOICES,
    ),
)

_BY_MODEL = {item.model: item for item in _CAPABILITIES}

DEFAULT_TTS_MODEL = "qwen3-tts-flash"


def supported_models() -> tuple[TtsModelCapability, ...]:
    return _CAPABILITIES


def models_for(provider: TtsProvider) -> tuple[TtsModelCapability, ...]:
    """Models available on ``provider`` (e.g. ``"bailian"`` or ``"gateway"``)."""

    return tuple(item for item in _CAPABILITIES if provider in item.providers)


def capability_for(model: str) -> TtsModelCapability | None:
    """Capability of ``model``, or None when it is not a supported model."""

    return _BY_MODEL.get((model or "").strip())


def require_capability(model: str) -> TtsModelCapability:
    """Capability of ``model``, falling back to the default synthesis model.

    A deployment can carry a model name this build does not know (an older
    config, or a hand-edited file). Falling back keeps narration working
    instead of failing the whole run, and the caller logs the substitution.
    """

    found = capability_for(model)
    if found is not None:
        return found
    return _BY_MODEL[DEFAULT_TTS_MODEL]


def resolve_system_voice(
    capability: TtsModelCapability,
    requested: str,
    configured: str,
) -> str | None:
    """The system voice this call will actually speak, or None if rejected.

    ``None`` means the caller named a voice this model does not publish; the
    caller turns that into an error before any provider round-trip.

    A name that did not come from the caller is a different case: one
    ``TTS_VOICE`` default is shared by every model while each model publishes
    its own list, so switching the synthesis model outside the configuration
    dialog leaves a name the model cannot speak. Refusing it would silence
    every narration in that deployment, so it is swapped for the model's own
    first voice.

    This is the only place that decides. The semantic-replay cache in
    ``audio_execution`` keys a stored narration by the voice it resolved to,
    so a second, slightly different resolution there would make every
    fallback miss its own cache and pay the provider for the same audio
    again.
    """

    active = (requested or configured).strip()
    if not active or active in capability.system_voices:
        return active
    if requested.strip():
        return None
    if capability.system_voices:
        return capability.system_voices[0]
    # A family with no published list at all has nothing to fall back to, so
    # the configured name is passed through unchanged.
    return active


__all__ = [
    "DEFAULT_TTS_MODEL",
    "TtsFamily",
    "TtsModelCapability",
    "TtsProvider",
    "TtsTransport",
    "capability_for",
    "models_for",
    "require_capability",
    "resolve_system_voice",
    "supported_models",
]
