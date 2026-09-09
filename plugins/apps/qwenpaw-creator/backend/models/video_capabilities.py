# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Model-aware capability catalog for reference-to-video providers.

Both the submit path (``models.video_model``) and the specialist prompt
surface (``services.file_agent_runtime.subagents``) consult this module so
model-specific request constraints and prompt-writing rules never drift
apart.

HappyHorse r2v (Bailian) shares the Wan DashScope async protocol but has a
narrower contract, transcribed from the official API reference:
https://help.aliyun.com/zh/model-studio/happyhorse-reference-to-video-api-reference

- ``media`` accepts ``reference_image`` only (no reference videos), 1-9 items.
- The prompt must cite each reference as ``[Image N]`` (1-based, following
  the ``media`` array order) and name the concrete subject in that image.
- ``resolution`` is 720P/1080P only; ``duration`` is an integer in [3, 15].
- ``parameters`` documents resolution/ratio/duration/watermark/seed only, so
  Wan-specific fields such as ``prompt_extend`` are not sent.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from models.reference_markers import (
    CANONICAL_MARKER_PATTERN,
    ReferenceMarkerSpec,
    canonical_marker_indices,
)

HAPPYHORSE_MODEL_PREFIX = "happyhorse"
HAPPYHORSE_MAX_REFERENCE_IMAGES = 9
HAPPYHORSE_RESOLUTIONS = frozenset({"720P", "1080P"})
HAPPYHORSE_RATIOS = frozenset(
    {"16:9", "9:16", "3:4", "4:3", "4:5", "5:4", "1:1", "9:21", "21:9"},
)
HAPPYHORSE_MIN_DURATION_SECONDS = 3
HAPPYHORSE_MAX_DURATION_SECONDS = 15
# HappyHorse video_edit inputs: 3-60s videos, anything above 15s is
# truncated to the first 15s by the provider; output duration follows input.
HAPPYHORSE_VIDEO_EDIT_MIN_INPUT_SECONDS = 3
HAPPYHORSE_VIDEO_EDIT_MAX_INPUT_SECONDS = 60
HAPPYHORSE_VIDEO_EDIT_KEPT_SECONDS = 15
HAPPYHORSE_VIDEO_EDIT_MAX_REFERENCE_IMAGES = 5

# Wan3.0 All-in-One request and reference-video duration contract.
WAN_30_RESOLUTIONS = frozenset({"480P", "720P", "1080P"})
WAN_30_RATIOS = frozenset({"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"})
WAN_30_MIN_DURATION_SECONDS = 2
WAN_30_MAX_DURATION_SECONDS = 30
WAN_30_MAX_REFERENCE_VIDEO_SECONDS = 15


@dataclass(frozen=True, slots=True)
class VideoReferenceCapability:
    """Official R2V reference-media contract for one model family."""

    family: str
    max_reference_images: int
    max_reference_videos: int
    max_reference_media: int
    documentation_url: str
    max_reference_video_duration_seconds: int | None = None
    max_input_output_duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class VideoModelCapability:
    """Generation modes documented for one exact provider model ID.

    ``known=False`` is deliberately fail-closed.  A compatible gateway alias
    may speak the same HTTP protocol, but that does not prove that it exposes
    the same model siblings or accepts the same media inputs.
    """

    backend: str
    model: str
    supported_modes: frozenset[str]
    derives_mode_model: bool
    documentation_url: str
    known: bool = True


_HAPPYHORSE_REFERENCE_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/"
    "happyhorse-reference-to-video-api-reference"
)
_WAN_27_REFERENCE_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/video-to-video-guide"
)
_WAN_30_REFERENCE_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/"
    "wan3-video-generation-api-reference"
)
_WAN_26_REFERENCE_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/"
    "legacy-wan-reference-to-video-api-reference"
)
_SEEDANCE_20_REFERENCE_DOCUMENTATION = (
    "https://www.volcengine.com/docs/82379/1520757"
)
_SEEDANCE_ARK_DOCUMENTATION = "https://www.volcengine.com/docs/82379/1520757"
_VEO_REFERENCE_DOCUMENTATION = "https://ai.google.dev/gemini-api/docs/veo"
_KLING_REFERENCE_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/"
    "kling-video-generation-api-reference/"
)
_MINIMAX_REFERENCE_DOCUMENTATION = (
    "https://platform.minimax.io/docs/api-reference/video-generation-t2v"
)
_MINIMAX_H3_VIDEO_DOCUMENTATION = (
    "https://platform.minimax.io/docs/api-reference/"
    "video-generation-v2-create"
)
_MINIMAX_H3_SGLANG_DOCUMENTATION = (
    "https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3"
)
_VIDU_BAILIAN_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/"
    "vidu-reference-to-video-api-reference"
)

# These are R2V input limits, not generated-video counts. Keep the catalog
# closed over model IDs whose official contracts are known. In particular, a
# gateway endpoint alias is not assumed to be Wan merely because it speaks the
# same transport protocol: reference use must fail before billing until the
# alias is mapped to an official model capability.
_HAPPYHORSE_REFERENCE_PATTERN = re.compile(
    r"^happyhorse-1\.(?:0|1)(?:-r2v)?$",
    re.IGNORECASE,
)
_WAN_30_REFERENCE_PATTERN = re.compile(
    r"^wan3\.0-video(?:-prime)?$",
    re.IGNORECASE,
)
_SEEDANCE_20_REFERENCE_PATTERN = re.compile(
    r"^doubao-seedance-2-0(?:-(?:fast|mini))?-\d{6}$",
    re.IGNORECASE,
)
# Seedance 2.5 (Ark, e.g. doubao-seedance-2-5-260628) is matched after the
# same separator canonicalisation as 2.0 (dots/underscores -> hyphens).
_SEEDANCE_25_REFERENCE_PATTERN = re.compile(
    r"^(?:doubao-)?seedance-?2-5(?:-\d{6})?$",
    re.IGNORECASE,
)
_VEO_31_REFERENCE_PATTERN = re.compile(
    r"^veo-3\.1(?:-fast)?-generate-preview$",
    re.IGNORECASE,
)
_VEO_31_LITE_REFERENCE_PATTERN = re.compile(
    r"^veo-3\.1-lite-generate-preview$",
    re.IGNORECASE,
)
_KLING_OMNI_REFERENCE_PATTERN = re.compile(
    r"^kling/kling-v3-omni-video-generation$",
    re.IGNORECASE,
)
_KLING_DIRECT_OMNI_REFERENCE_PATTERN = re.compile(
    r"^kling-[\w.-]*omni[\w.-]*$",
    re.IGNORECASE,
)
_VIDU_DIRECT_Q2_PRO_REFERENCE_PATTERN = re.compile(
    r"^viduq2-pro$",
    re.IGNORECASE,
)
_VIDU_DIRECT_IMAGE_ONLY_REFERENCE_PATTERN = re.compile(
    r"^(?:viduq3(?:-mix|-turbo)?|viduq2|viduq1|vidu2\.0)$",
    re.IGNORECASE,
)
_MINIMAX_S2V_REFERENCE_PATTERN = re.compile(
    r"^s2v-01$",
    re.IGNORECASE,
)
_MINIMAX_H3_REFERENCE_PATTERN = re.compile(
    r"^minimax-h3(?:-max|-ref2va)?$",
    re.IGNORECASE,
)
_VIDU_IMAGE_ONLY_REFERENCE_PATTERN = re.compile(
    r"^vidu/(?:viduq3(?:-ad|-drama|-mix|-turbo)?|viduq2)_reference2video$",
    re.IGNORECASE,
)
_VIDU_Q2_PRO_REFERENCE_PATTERN = re.compile(
    r"^vidu/viduq2-pro_reference2video$",
    re.IGNORECASE,
)

_HAPPYHORSE_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="happyhorse-1.0/1.1-r2v",
    max_reference_images=9,
    max_reference_videos=0,
    max_reference_media=9,
    documentation_url=_HAPPYHORSE_REFERENCE_DOCUMENTATION,
)
_WAN_27_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="wan2.7-r2v",
    max_reference_images=5,
    max_reference_videos=5,
    max_reference_media=5,
    documentation_url=_WAN_27_REFERENCE_DOCUMENTATION,
)
_WAN_30_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="wan3.0-video",
    max_reference_images=10,
    max_reference_videos=5,
    # The official contract declares independent image/video maxima and no
    # smaller combined-media cap, so the combined ceiling is their sum.
    max_reference_media=15,
    documentation_url=_WAN_30_REFERENCE_DOCUMENTATION,
    max_reference_video_duration_seconds=WAN_30_MAX_REFERENCE_VIDEO_SECONDS,
    max_input_output_duration_seconds=WAN_30_MAX_DURATION_SECONDS,
)
_WAN_26_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="wan2.6-r2v",
    max_reference_images=5,
    max_reference_videos=3,
    max_reference_media=5,
    documentation_url=_WAN_26_REFERENCE_DOCUMENTATION,
)
_SEEDANCE_20_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="doubao-seedance-2.0",
    max_reference_images=9,
    max_reference_videos=3,
    max_reference_media=12,
    documentation_url=_SEEDANCE_20_REFERENCE_DOCUMENTATION,
)
# Seedance 2.5 omni reference: 1-30 images plus up to 10 reference videos
# (official Ark task API reference, "模型能力" table).
_SEEDANCE_25_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="doubao-seedance-2.5",
    max_reference_images=30,
    max_reference_videos=10,
    max_reference_media=40,
    documentation_url=_SEEDANCE_ARK_DOCUMENTATION,
)
# Veo 3.1 / 3.1 Fast: "Up to three images to be used as style and content
# references"; Veo 3.1 Lite documents no referenceImages support at all.
_VEO_31_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="veo-3.1",
    max_reference_images=3,
    max_reference_videos=0,
    max_reference_media=3,
    documentation_url=_VEO_REFERENCE_DOCUMENTATION,
)
_VEO_31_LITE_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="veo-3.1-lite",
    max_reference_images=0,
    max_reference_videos=0,
    max_reference_media=0,
    documentation_url=_VEO_REFERENCE_DOCUMENTATION,
)
# Kling v3 omni on Bailian: reference generation accepts up to 7 refer
# images (images + element subjects <= 7) plus at most 1 feature
# reference video; with a video the image budget shrinks to 4 (enforced
# at submit time). kling/kling-v3-video-generation has no refer support.
_KLING_OMNI_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="kling-v3-omni",
    max_reference_images=7,
    max_reference_videos=1,
    max_reference_media=7,
    documentation_url=_KLING_REFERENCE_DOCUMENTATION,
)
# Official-channel Kling omni (kling-3.0-omni): the same 7-image budget,
# at most 1 feature reference video (images then limited to 4).
_KLING_DIRECT_OMNI_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="kling-omni-direct",
    max_reference_images=7,
    max_reference_videos=1,
    max_reference_media=7,
    documentation_url=(
        "https://kling.ai/document-api/api/video/3-0-omni/video-omni"
    ),
)
# MiniMax subject reference is served by S2V-01 only: one character
# subject carrying exactly one image.
_MINIMAX_S2V_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="minimax-s2v-01",
    max_reference_images=1,
    max_reference_videos=0,
    max_reference_media=1,
    documentation_url=_MINIMAX_REFERENCE_DOCUMENTATION,
)
# MiniMax H3 omni reference (v2 API and SGLang Ref2VA): up to 9 reference
# images and 3 reference videos. The official 12-file total also counts
# reference audio, which this catalog does not track — the submit builders
# enforce the audio-inclusive cap.
_MINIMAX_H3_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="minimax-h3",
    max_reference_images=9,
    max_reference_videos=3,
    max_reference_media=12,
    documentation_url=_MINIMAX_H3_VIDEO_DOCUMENTATION,
)
# Vidu reference-to-video hosted on Bailian: image-only models accept
# 1-7 reference images; viduq2-pro additionally accepts 1-2 reference
# videos (with images then limited to 1-4 — enforced at submit time).
_VIDU_IMAGE_ONLY_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="vidu-reference2video",
    max_reference_images=7,
    max_reference_videos=0,
    max_reference_media=7,
    documentation_url=_VIDU_BAILIAN_DOCUMENTATION,
)
_VIDU_Q2_PRO_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="vidu-viduq2-pro-reference2video",
    max_reference_images=7,
    max_reference_videos=2,
    max_reference_media=7,
    documentation_url=_VIDU_BAILIAN_DOCUMENTATION,
)
_VIDU_DIRECT_DOCUMENTATION = (
    "https://platform.vidu.com/docs/reference-to-video"
)
# Official-channel Vidu reference2video: image-only models take 1-7
# images; viduq2-pro additionally takes up to 2 reference videos (with
# images then limited to 1-4 — enforced at submit time).
_VIDU_DIRECT_IMAGE_ONLY_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="vidu-direct-reference2video",
    max_reference_images=7,
    max_reference_videos=0,
    max_reference_media=7,
    documentation_url=_VIDU_DIRECT_DOCUMENTATION,
)
_VIDU_DIRECT_Q2_PRO_REFERENCE_CAPABILITY = VideoReferenceCapability(
    family="vidu-direct-viduq2-pro",
    max_reference_images=7,
    max_reference_videos=2,
    max_reference_media=7,
    documentation_url=_VIDU_DIRECT_DOCUMENTATION,
)

# Generation modes exposed on the r2v_generation tool. ``r2v`` keeps the
# historical behaviour; the others map onto the upstream model families
# (happyhorse-*-t2v/-i2v/-video-edit, wan*-t2v/-i2v).
VIDEO_MODES = ("r2v", "t2v", "i2v", "video_edit")

_DASHSCOPE_VIDEO_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/video-generation-api-reference"
)
_SEEDANCE_VIDEO_DOCUMENTATION = "https://www.volcengine.com/docs/82379/1520757"
_VEO_VIDEO_DOCUMENTATION = "https://ai.google.dev/gemini-api/docs/veo"
_KLING_DIRECT_DOCUMENTATION = (
    "https://kling.ai/document-api/api/video/video-generation"
)
_MINIMAX_VIDEO_DOCUMENTATION = (
    "https://platform.minimax.io/docs/api-reference/video-generation-t2v"
)
_VIDU_DIRECT_VIDEO_DOCUMENTATION = "https://platform.vidu.com/docs"

_HAPPYHORSE_11_MODEL_PATTERN = re.compile(
    r"^happyhorse-1\.1(?:-(?:r2v|t2v|i2v))?$",
    re.IGNORECASE,
)
_HAPPYHORSE_10_MODEL_PATTERN = re.compile(
    r"^happyhorse-1\.0(?:-(?:r2v|t2v|i2v|video-edit))?$",
    re.IGNORECASE,
)
_WAN_27_MODEL_PATTERN = re.compile(
    r"^wan2\.7(?:-(?:r2v|t2v|i2v))?(?:-20\d{2}-\d{2}-\d{2})?$",
    re.IGNORECASE,
)
_WAN_26_MODEL_PATTERN = re.compile(
    r"^wan2\.6(?:-(?:r2v(?:-flash)?|t2v|i2v))?(?:-20\d{2}-\d{2}-\d{2})?$",
    re.IGNORECASE,
)

_SEEDANCE_MODELS = frozenset(
    {
        "doubao-seedance-2-5-260628",
        "doubao-seedance-2-0-260128",
        "doubao-seedance-2-0-fast-260128",
        "doubao-seedance-2-0-mini-260615",
    },
)
_VEO_MODEL_MODES: dict[str, frozenset[str]] = {
    "veo-3.1-generate-preview": frozenset({"r2v", "t2v", "i2v"}),
    "veo-3.1-fast-generate-preview": frozenset({"r2v", "t2v", "i2v"}),
    "veo-3.1-lite-generate-preview": frozenset({"t2v", "i2v"}),
}
_KLING_HOSTED_MODEL_MODES: dict[str, frozenset[str]] = {
    "kling/kling-v3-omni-video-generation": frozenset(
        {"r2v", "t2v", "i2v"},
    ),
    "kling/kling-v3-video-generation": frozenset({"t2v", "i2v"}),
}
_KLING_DIRECT_MODEL_MODES: dict[str, frozenset[str]] = {
    "kling-3.0-omni": frozenset({"r2v", "t2v", "i2v"}),
    "kling-2.6": frozenset({"t2v", "i2v"}),
}
_MINIMAX_MODEL_MODES: dict[str, frozenset[str]] = {
    "minimax-h3": frozenset({"t2v", "i2v", "r2v"}),
    "minimax-h3-max": frozenset({"t2v", "i2v", "r2v"}),
    "minimax-hailuo-2.3": frozenset({"t2v", "i2v"}),
    "minimax-hailuo-2.3-fast": frozenset({"i2v"}),
    "minimax-hailuo-02": frozenset({"t2v", "i2v"}),
    "t2v-01": frozenset({"t2v"}),
    "t2v-01-director": frozenset({"t2v"}),
    "i2v-01": frozenset({"i2v"}),
    "i2v-01-live": frozenset({"i2v"}),
    "i2v-01-director": frozenset({"i2v"}),
    "s2v-01": frozenset({"r2v"}),
}
# SGLang self-hosted H3: one server instance loads exactly one checkpoint
# variant (``sglang serve --model-variant fl2va|ref2va``, official ports
# 30010/30011), so the configured model name records which variant the
# endpoint serves and fail-closes the other modes. The wire request never
# carries the model name.
_MINIMAX_H3_SGLANG_MODEL_MODES: dict[str, frozenset[str]] = {
    "minimax-h3-fl2va": frozenset({"t2v", "i2v"}),
    "minimax-h3-ref2va": frozenset({"r2v"}),
}
_VIDU_HOSTED_MODEL_MODES: dict[str, frozenset[str]] = {
    f"vidu/{name}_reference2video": frozenset({"r2v"})
    for name in (
        "viduq3-ad",
        "viduq3-drama",
        "viduq3-mix",
        "viduq3",
        "viduq3-turbo",
        "viduq2-pro",
        "viduq2",
    )
}
_VIDU_DIRECT_MODEL_MODES: dict[str, frozenset[str]] = {
    "viduq3-mix": frozenset({"r2v"}),
    "viduq3-turbo": frozenset({"r2v", "t2v", "i2v"}),
    "viduq3": frozenset({"r2v"}),
    "viduq2-pro": frozenset({"r2v", "i2v"}),
    "viduq2": frozenset({"r2v", "t2v"}),
    "viduq1": frozenset({"r2v", "t2v", "i2v"}),
    "vidu2.0": frozenset({"r2v", "i2v"}),
}

_MODE_SUFFIXES = {
    "r2v": "r2v",
    "t2v": "t2v",
    "i2v": "i2v",
    "video_edit": "video-edit",
}
# Longest first so "-video-edit" wins over any hyphen-token overlap.
_KNOWN_SUFFIX_SEGMENTS = ("-video-edit", "-t2v", "-i2v", "-r2v")

# Backends whose providers keep the configured model name for every mode
# (their upstream families do not encode the mode in the model ID).
_CONFIGURED_NAME_BACKENDS = frozenset(
    {"seedance2", "veo", "kling", "minimax", "minimax_sglang", "vidu"},
)

# --- Official per-family request constraints -------------------------------
# Veo 3.1 (Gemini API): durationSeconds is one of "4"/"6"/"8" and must be 8
# with reference images or 1080p/4k output; aspectRatio is 16:9 or 9:16.
VEO_DURATION_SECONDS = frozenset({4, 6, 8})
VEO_REFERENCE_DURATION_SECONDS = 8
VEO_RESOLUTIONS = frozenset({"720p", "1080p", "4k"})
VEO_RATIOS = frozenset({"16:9", "9:16"})

# Kling constraints. Bailian hosting (kling/kling-v3-*-video-generation,
# DashScope video-synthesis protocol): duration 3-15 (3-10 with a feature
# reference video), parameters.mode maps the output tier (std=720P /
# pro=1080P / 4k). Official channel (api-singapore.klingai.com, Bearer
# API Key): kling-2.6 t2v/i2v renders 5s or 10s at 720p/1080p;
# kling-3.0-omni renders 3-15s at 720p/1080p/4k and serves reference
# generation via refer_image/feature_video contents.
KLING_RATIOS = frozenset({"16:9", "9:16", "1:1"})
KLING_MIN_DURATION_SECONDS = 3
KLING_MAX_DURATION_SECONDS = 15
KLING_FEATURE_VIDEO_MAX_DURATION_SECONDS = 10
KLING_MAX_PROMPT_CHARS = 2500
KLING_OMNI_MODEL = "kling/kling-v3-omni-video-generation"
KLING_REFER_MAX_IMAGES_WITH_VIDEO = 4
KLING_MODE_BY_RESOLUTION = {"720p": "std", "1080p": "pro", "4k": "4k"}
KLING_V26_DURATIONS = frozenset({5, 10})
KLING_V26_RESOLUTIONS = frozenset({"720p", "1080p"})
KLING_OMNI_DURATIONS = frozenset(range(3, 16))
KLING_OMNI_RESOLUTIONS = frozenset({"720p", "1080p", "4k"})


def is_kling_omni_model(model_name: str) -> bool:
    """True for Kling omni models (reference-capable, e.g. kling-3.0-omni)."""

    return "omni" in model_name.strip().casefold()


# MiniMax video generation: resolution -> allowed durations (seconds).
MINIMAX_HAILUO_RESOLUTIONS: dict[str, tuple[int, ...]] = {
    "768P": (6, 10),
    "1080P": (6,),
}
MINIMAX_HAILUO_02_RESOLUTIONS: dict[str, tuple[int, ...]] = {
    "512P": (6, 10),
    "768P": (6, 10),
    "1080P": (6,),
}
MINIMAX_LEGACY_RESOLUTIONS: dict[str, tuple[int, ...]] = {"720P": (6,)}
MINIMAX_MAX_PROMPT_CHARS = 2000
MINIMAX_SUBJECT_REFERENCE_MODEL = "S2V-01"

# MiniMax H3 (v2 API): any integer duration inside the documented window;
# H3-Max starts at 5s. 768P leads each matrix so it is the default tier.
MINIMAX_H3_RESOLUTIONS: dict[str, tuple[int, ...]] = {
    "768P": tuple(range(4, 16)),
    "480P": tuple(range(4, 16)),
    "2K": tuple(range(4, 16)),
}
MINIMAX_H3_MAX_MODEL_RESOLUTIONS: dict[str, tuple[int, ...]] = {
    "768P": tuple(range(5, 16)),
    "480P": tuple(range(5, 16)),
    "2K": tuple(range(5, 16)),
}
# Self-hosted H3-Base renders 768p only; 2K needs the hosted Regenerate-2K.
MINIMAX_H3_SGLANG_RESOLUTIONS: dict[str, tuple[int, ...]] = {
    "768P": tuple(range(4, 16)),
}
MINIMAX_H3_MAX_PROMPT_CHARS = 7000
MINIMAX_H3_RATIOS = frozenset(
    {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"},
)
MINIMAX_H3_MAX_REFERENCE_AUDIO = 3
MINIMAX_H3_MAX_TOTAL_MEDIA = 12

# Bailian-hosted Vidu reference-to-video: per-model duration window
# (inclusive), resolutions, default resolution, allowed ratios and whether
# the ``audio`` parameter is documented for the model.
_VIDU_ALL_RATIOS = ("16:9", "4:3", "1:1", "3:4", "9:16")
VIDU_MODEL_SPECS: dict[str, dict] = {
    "vidu/viduq3-ad_reference2video": {
        "durations": (3, 15),
        "resolutions": ("720P", "1080P"),
        "default_resolution": "720P",
        "ratios": _VIDU_ALL_RATIOS,
        "audio": True,
    },
    "vidu/viduq3-drama_reference2video": {
        "durations": (2, 15),
        "resolutions": ("720P", "1080P"),
        "default_resolution": "1080P",
        "ratios": ("16:9", "9:16"),
        "audio": False,
    },
    "vidu/viduq3-mix_reference2video": {
        "durations": (1, 16),
        "resolutions": ("540P", "720P", "1080P"),
        "default_resolution": "720P",
        "ratios": _VIDU_ALL_RATIOS,
        "audio": True,
    },
    "vidu/viduq3_reference2video": {
        "durations": (1, 16),
        "resolutions": ("540P", "720P", "1080P"),
        "default_resolution": "720P",
        "ratios": _VIDU_ALL_RATIOS,
        "audio": True,
    },
    "vidu/viduq3-turbo_reference2video": {
        "durations": (1, 16),
        "resolutions": ("540P", "720P", "1080P"),
        "default_resolution": "720P",
        "ratios": _VIDU_ALL_RATIOS,
        "audio": True,
    },
    "vidu/viduq2-pro_reference2video": {
        "durations": (1, 10),
        "resolutions": ("540P", "720P", "1080P"),
        "default_resolution": "720P",
        "ratios": _VIDU_ALL_RATIOS,
        "audio": False,
    },
    "vidu/viduq2_reference2video": {
        "durations": (1, 10),
        "resolutions": ("540P", "720P", "1080P"),
        "default_resolution": "720P",
        "ratios": _VIDU_ALL_RATIOS,
        "audio": False,
    },
}
# resolution tier -> ratio -> "width*height" (official Bailian size table).
VIDU_SIZE_MAP: dict[str, dict[str, str]] = {
    "540P": {
        "16:9": "1024*576",
        "4:3": "1024*768",
        "1:1": "1024*1024",
        "3:4": "768*1024",
        "9:16": "576*1024",
    },
    "720P": {
        "16:9": "1280*720",
        "4:3": "1280*960",
        "1:1": "1280*1280",
        "3:4": "960*1280",
        "9:16": "720*1280",
    },
    "1080P": {
        "16:9": "1920*1080",
        "4:3": "1920*1440",
        "1:1": "1808*1808",
        "3:4": "1440*1920",
        "9:16": "1080*1920",
    },
}

# Official-channel Vidu reference2video (api.vidu.com, Token auth):
# per-model duration windows, resolutions and ratios from the official
# "Reference to Video" request-body table. The ``audio`` switch is sent
# for the q3 generation only (defaults documented per model).
VIDU_MAX_PROMPT_CHARS = 5000
_VIDU_DIRECT_BASE_RATIOS = ("16:9", "9:16", "1:1")
_VIDU_DIRECT_Q2_RATIOS = ("16:9", "9:16", "3:4", "4:3", "1:1")
VIDU_DIRECT_SPECS: dict[str, dict] = {
    "viduq3-mix": {
        "durations": (1, 16),
        "resolutions": ("720p", "1080p"),
        "default_resolution": "720p",
        "ratios": _VIDU_DIRECT_BASE_RATIOS,
        "audio": True,
    },
    "viduq3-turbo": {
        "durations": (3, 16),
        "resolutions": ("540p", "720p", "1080p"),
        "default_resolution": "720p",
        "ratios": _VIDU_DIRECT_BASE_RATIOS,
        "audio": True,
    },
    "viduq3": {
        "durations": (3, 16),
        "resolutions": ("540p", "720p", "1080p"),
        "default_resolution": "720p",
        "ratios": _VIDU_DIRECT_BASE_RATIOS,
        "audio": True,
    },
    "viduq2-pro": {
        "durations": (1, 10),
        "resolutions": ("540p", "720p", "1080p"),
        "default_resolution": "720p",
        "ratios": _VIDU_DIRECT_Q2_RATIOS,
        "audio": False,
    },
    "viduq2": {
        "durations": (1, 10),
        "resolutions": ("540p", "720p", "1080p"),
        "default_resolution": "720p",
        "ratios": _VIDU_DIRECT_Q2_RATIOS,
        "audio": False,
    },
    "viduq1": {
        "durations": (5, 5),
        "resolutions": ("1080p",),
        "default_resolution": "1080p",
        "ratios": _VIDU_DIRECT_BASE_RATIOS,
        "audio": False,
    },
    "vidu2.0": {
        "durations": (4, 4),
        "resolutions": ("360p", "720p"),
        "default_resolution": "360p",
        "ratios": _VIDU_DIRECT_BASE_RATIOS,
        "audio": False,
    },
}


def seedance_video_generation(
    model_name: str,
) -> str | None:
    """Classify a Seedance model into its documented generation family.

    Returns "2.5", "2.0", "2.0-fast", "1.5" or "1.0" for known Seedance
    IDs (dots/underscores canonicalised to hyphens), else ``None``.
    """
    # pylint: disable=too-many-return-statements
    canonical = (
        model_name.strip().replace("_", "-").replace(".", "-").casefold()
    )
    if "seedance" not in canonical:
        return None
    if re.search(r"seedance-?2-5", canonical):
        return "2.5"
    if re.search(r"seedance-?2(?:-0)?-(?:fast|mini)", canonical):
        return "2.0-fast"
    if re.search(r"seedance-?2(?:-0)?", canonical):
        return "2.0"
    if re.search(r"seedance-?1-5", canonical):
        return "1.5"
    if re.search(r"seedance-?1-0", canonical):
        return "1.0"
    return None


# Seedance family -> (resolutions, min duration, max duration, allows -1).
SEEDANCE_FAMILY_SPECS: dict[str, tuple[frozenset[str], int, int, bool]] = {
    "2.5": (frozenset({"480p", "720p", "1080p"}), 4, 30, True),
    "2.0": (frozenset({"480p", "720p", "1080p", "4k"}), 4, 15, True),
    "2.0-fast": (frozenset({"480p", "720p"}), 4, 15, True),
    "1.5": (frozenset({"480p", "720p", "1080p"}), 4, 12, True),
    "1.0": (frozenset({"480p", "720p", "1080p"}), 2, 12, False),
}

# Reference-voice input shapes documented by the official R2V contracts:
# - "per_media": wan2.7 binds one voice per reference entry via
#   ``media[].reference_voice`` (video-to-video guide, 参数设置 table).
# - "standalone": wan3.0 accepts up to five ``type=reference_audio`` media
#   entries (total <= 15s); Seedance 2.x accepts ``type=audio_url`` content
#   entries with role ``reference_audio`` (2.5: up to 10; 2.0: up to 3,
#   paired with image/video references); MiniMax H3 accepts up to three
#   ``audio_url`` content entries with role ``reference_audio`` (v2 API)
#   or ``type=audio`` reference conditions (SGLang Ref2VA).
# Every other family (wan2.6, HappyHorse, Kling, Vidu, Veo, the v1 MiniMax
# models) documents no audio input — only automatic-audio switches.
REFERENCE_VOICE_PER_MEDIA = "per_media"
REFERENCE_VOICE_STANDALONE = "standalone"


def video_reference_voice_support(  # pylint: disable=too-many-return-statements  # noqa: E501
    model_name: str,
    protocol_backend: str | None = None,
) -> tuple[str, int] | None:
    """Return ``(shape, max_audio_count)`` or ``None`` when unsupported."""

    name = (model_name or "").strip()
    if not name:
        return None
    if _MINIMAX_H3_REFERENCE_PATTERN.fullmatch(name):
        return (REFERENCE_VOICE_STANDALONE, MINIMAX_H3_MAX_REFERENCE_AUDIO)
    if _WAN_27_MODEL_PATTERN.match(name):
        return (REFERENCE_VOICE_PER_MEDIA, 5)
    if is_wan3_video_model(name):
        return (REFERENCE_VOICE_STANDALONE, 5)
    seedance_family = seedance_video_generation(name)
    if seedance_family is None and (protocol_backend or "") == "seedance2":
        return None
    if seedance_family == "2.5":
        return (REFERENCE_VOICE_STANDALONE, 10)
    if seedance_family in ("2.0", "2.0-fast"):
        return (REFERENCE_VOICE_STANDALONE, 3)
    return None


def is_happyhorse_model(model_name: str) -> bool:
    """True when the configured video model is a Bailian HappyHorse model."""

    return model_name.strip().casefold().startswith(HAPPYHORSE_MODEL_PREFIX)


def is_wan3_video_model(model_name: str) -> bool:
    """True for Wan3.0 All-in-One video generation model IDs."""

    return _WAN_30_REFERENCE_PATTERN.fullmatch(model_name.strip()) is not None


def is_vidu_model(model_name: str) -> bool:
    """True when the configured video model is a Bailian-hosted Vidu model."""

    return model_name.strip().casefold().startswith("vidu")


def is_minimax_video_model(model_name: str) -> bool:
    """True for MiniMax video model IDs (Hailuo / T2V-01 / I2V-01 / S2V-01)."""

    lowered = model_name.strip().casefold()
    if not lowered:
        return False
    if "hailuo" in lowered or lowered.startswith("minimax"):
        return True
    return lowered.startswith(("t2v-01", "i2v-01", "s2v-01"))


def video_backend_key(
    model_name: str,
    protocol_backend: str = "",
) -> str:
    """Map a configured model (+ optional protocol backend) to a matrix key."""
    # pylint: disable=too-many-return-statements
    normalized_protocol = protocol_backend.strip().casefold()
    if normalized_protocol in {
        "veo",
        "kling",
        "minimax",
        "minimax_sglang",
        "vidu",
    }:
        return normalized_protocol
    if is_happyhorse_model(model_name):
        return "happyhorse"
    if (
        normalized_protocol == "seedance2"
        or "seedance" in model_name.casefold()
    ):
        return "seedance2"
    lowered = model_name.strip().casefold()
    if lowered.startswith("veo"):
        return "veo"
    if lowered.startswith("kling"):
        return "kling"
    if is_minimax_video_model(lowered):
        return "minimax"
    if is_vidu_model(lowered):
        return "vidu"
    return "wan"


def video_model_capability(
    model_name: str,
    protocol_backend: str = "",
) -> VideoModelCapability:
    """Resolve generation modes for an exact model ID and provider channel.

    This is the canonical capability lookup used by API, prompts and submit
    validation.  It intentionally does not inherit a provider-wide mode set.
    """
    # Exact model registration is intentionally fail-closed and each provider
    # has a distinct naming contract, so the branches are the registry itself.
    # pylint: disable=too-many-branches,too-many-statements

    model = model_name.strip()
    lowered = model.casefold()
    backend = video_backend_key(model, protocol_backend)
    modes: frozenset[str] | None = None
    derives = False
    documentation_url = ""

    # A model ID can exist on a different channel with a different payload
    # contract.  Do not infer an official-channel adapter merely from the
    # name when the selected protocol is DashScope hosting (or vice versa).
    protocol = protocol_backend.strip().casefold()
    expected_protocols = {
        "happyhorse": {"wan", "happyhorse"},
        "wan": {"wan"},
        "seedance2": {"seedance2"},
        "veo": {"veo"},
        "minimax": {"minimax"},
        "kling": ({"wan"} if lowered.startswith("kling/") else {"kling"}),
        "vidu": ({"wan"} if lowered.startswith("vidu/") else {"vidu"}),
    }.get(backend, {backend})
    if protocol and protocol not in expected_protocols:
        return VideoModelCapability(
            backend=backend,
            model=model,
            supported_modes=frozenset(),
            derives_mode_model=False,
            documentation_url="",
            known=False,
        )

    if backend == "happyhorse":
        if _HAPPYHORSE_11_MODEL_PATTERN.fullmatch(model):
            modes = frozenset({"r2v", "t2v", "i2v"})
        elif _HAPPYHORSE_10_MODEL_PATTERN.fullmatch(model):
            modes = frozenset({"r2v", "t2v", "i2v", "video_edit"})
        derives = modes is not None
        documentation_url = _HAPPYHORSE_REFERENCE_DOCUMENTATION
    elif backend == "wan":
        if is_wan3_video_model(model):
            modes = frozenset({"r2v", "t2v", "i2v"})
            documentation_url = _WAN_30_REFERENCE_DOCUMENTATION
        elif _WAN_27_MODEL_PATTERN.fullmatch(
            model,
        ) or _WAN_26_MODEL_PATTERN.fullmatch(model):
            modes = frozenset({"r2v", "t2v", "i2v"})
            derives = True
            documentation_url = _DASHSCOPE_VIDEO_DOCUMENTATION
    elif backend == "seedance2":
        if lowered in _SEEDANCE_MODELS:
            modes = frozenset({"r2v", "t2v", "i2v"})
        documentation_url = _SEEDANCE_VIDEO_DOCUMENTATION
    elif backend == "veo":
        modes = _VEO_MODEL_MODES.get(lowered)
        documentation_url = _VEO_VIDEO_DOCUMENTATION
    elif backend == "kling":
        if lowered.startswith("kling/"):
            modes = _KLING_HOSTED_MODEL_MODES.get(lowered)
            documentation_url = _KLING_REFERENCE_DOCUMENTATION
        else:
            modes = _KLING_DIRECT_MODEL_MODES.get(lowered)
            documentation_url = _KLING_DIRECT_DOCUMENTATION
    elif backend == "minimax":
        modes = _MINIMAX_MODEL_MODES.get(lowered)
        documentation_url = _MINIMAX_VIDEO_DOCUMENTATION
    elif backend == "minimax_sglang":
        modes = _MINIMAX_H3_SGLANG_MODEL_MODES.get(lowered)
        documentation_url = _MINIMAX_H3_SGLANG_DOCUMENTATION
    elif backend == "vidu":
        if lowered.startswith("vidu/"):
            modes = _VIDU_HOSTED_MODEL_MODES.get(lowered)
            documentation_url = _VIDU_BAILIAN_DOCUMENTATION
        else:
            modes = _VIDU_DIRECT_MODEL_MODES.get(lowered)
            documentation_url = _VIDU_DIRECT_VIDEO_DOCUMENTATION

    if modes is None:
        return VideoModelCapability(
            backend=backend,
            model=model,
            supported_modes=frozenset(),
            derives_mode_model=False,
            documentation_url=documentation_url,
            known=False,
        )
    return VideoModelCapability(
        backend=backend,
        model=model,
        supported_modes=modes,
        derives_mode_model=derives,
        documentation_url=documentation_url,
    )


def video_model_supported_modes(
    model_name: str,
    protocol_backend: str = "",
) -> frozenset[str]:
    """Documented modes for this exact model/channel pair."""

    return video_model_capability(
        model_name,
        protocol_backend,
    ).supported_modes


def video_reference_capability(  # pylint: disable=too-many-return-statements
    model_name: str,
) -> VideoReferenceCapability | None:
    """Resolve an official R2V reference contract without guessing."""
    # pylint: disable=too-many-return-statements,too-many-branches
    normalized = model_name.strip()
    if not normalized:
        return None
    if _HAPPYHORSE_REFERENCE_PATTERN.fullmatch(normalized):
        return _HAPPYHORSE_REFERENCE_CAPABILITY
    if _WAN_30_REFERENCE_PATTERN.fullmatch(normalized):
        return _WAN_30_REFERENCE_CAPABILITY
    # These exact model IDs advertise a family reference contract even when
    # their suffix names the t2v/i2v entry point. This catalog describes what
    # the family can accept; submit-time mode validation independently decides
    # whether the current request may carry references. Keeping the same model
    # resolver here and in prompt guidance prevents known t2v/i2v IDs from
    # falling into the false "unknown Wan protocol" blocker.
    if _WAN_27_MODEL_PATTERN.fullmatch(normalized):
        return _WAN_27_REFERENCE_CAPABILITY
    if _WAN_26_MODEL_PATTERN.fullmatch(normalized):
        return _WAN_26_REFERENCE_CAPABILITY
    if _VEO_31_LITE_REFERENCE_PATTERN.fullmatch(normalized):
        return _VEO_31_LITE_REFERENCE_CAPABILITY
    if _VEO_31_REFERENCE_PATTERN.fullmatch(normalized):
        return _VEO_31_REFERENCE_CAPABILITY
    if _KLING_OMNI_REFERENCE_PATTERN.fullmatch(normalized):
        return _KLING_OMNI_REFERENCE_CAPABILITY
    if _KLING_DIRECT_OMNI_REFERENCE_PATTERN.fullmatch(normalized):
        return _KLING_DIRECT_OMNI_REFERENCE_CAPABILITY
    if _MINIMAX_H3_REFERENCE_PATTERN.fullmatch(normalized):
        return _MINIMAX_H3_REFERENCE_CAPABILITY
    if _MINIMAX_S2V_REFERENCE_PATTERN.fullmatch(normalized):
        return _MINIMAX_S2V_REFERENCE_CAPABILITY
    if _VIDU_Q2_PRO_REFERENCE_PATTERN.fullmatch(normalized):
        return _VIDU_Q2_PRO_REFERENCE_CAPABILITY
    if _VIDU_IMAGE_ONLY_REFERENCE_PATTERN.fullmatch(normalized):
        return _VIDU_IMAGE_ONLY_REFERENCE_CAPABILITY
    if _VIDU_DIRECT_Q2_PRO_REFERENCE_PATTERN.fullmatch(normalized):
        return _VIDU_DIRECT_Q2_PRO_REFERENCE_CAPABILITY
    if _VIDU_DIRECT_IMAGE_ONLY_REFERENCE_PATTERN.fullmatch(normalized):
        return _VIDU_DIRECT_IMAGE_ONLY_REFERENCE_CAPABILITY
    # Seedance model IDs use both dots and hyphens for the 2.0 segment across
    # the Ark presets and compatible endpoint configurations. Canonicalising
    # separators keeps those official IDs equivalent without accepting an
    # opaque endpoint alias.
    seedance_name = normalized.replace("_", "-").replace(".", "-")
    if _SEEDANCE_25_REFERENCE_PATTERN.fullmatch(seedance_name):
        return _SEEDANCE_25_REFERENCE_CAPABILITY
    if _SEEDANCE_20_REFERENCE_PATTERN.fullmatch(seedance_name):
        return _SEEDANCE_20_REFERENCE_CAPABILITY
    return None


def video_reference_violation(
    capability: VideoReferenceCapability,
    *,
    image_count: int,
    video_count: int,
) -> str | None:
    """Return the first official R2V reference-limit violation, if any."""

    if image_count < 0 or video_count < 0:
        raise ValueError("reference counts must be non-negative")
    total = image_count + video_count
    if total < 1:
        return "r2v 至少需要 1 个参考图像或参考视频"
    if image_count > capability.max_reference_images:
        return (
            f"参考图像最多 {capability.max_reference_images} 个，"
            f"当前为 {image_count} 个"
        )
    if video_count > capability.max_reference_videos:
        if capability.max_reference_videos == 0:
            return f"该模型不支持参考视频，当前为 {video_count} 个"
        return (
            f"参考视频最多 {capability.max_reference_videos} 个，"
            f"当前为 {video_count} 个"
        )
    if total > capability.max_reference_media:
        return (
            f"参考图像与参考视频合计最多 "
            f"{capability.max_reference_media} 个，当前为 {total} 个"
        )
    return None


def validate_video_mode(
    backend_key: str,
    model_name: str,
    mode: str,
) -> str:
    """Normalize ``mode`` and reject unsupported (backend, mode) pairs.

    Raises ``ValueError`` with a readable message naming the supported
    alternatives; callers wrap it into their own error type.
    """

    normalized = (mode or "r2v").strip().casefold() or "r2v"
    if normalized not in VIDEO_MODES:
        raise ValueError(
            f"未知的视频生成 mode {mode!r}；支持: {', '.join(VIDEO_MODES)}",
        )
    capability = video_model_capability(model_name, backend_key)
    supported = capability.supported_modes
    if normalized not in supported:
        supported_text = ", ".join(
            sorted(supported, key=VIDEO_MODES.index),
        )
        if not capability.known:
            supported_text = "无（精确模型 ID 未收录）"
        unknown_prefix = (
            "VIDEO_MODEL_CAPABILITY_UNKNOWN: " if not capability.known else ""
        )
        raise ValueError(
            f"{unknown_prefix}当前视频模型 `{model_name}`（{capability.backend}）不支持 "
            f"mode={normalized}；该模型仅支持 {supported_text}。"
            "请切换到明确支持该模式的模型，或先把兼容网关别名映射到"
            "官方模型能力表",
        )
    return normalized


def derive_video_model_name(model_name: str, mode: str) -> str:
    """Derive the mode-specific model name from a base or full model name.

    Upstream families name models per mode (``happyhorse-1.1-t2v`` /
    ``wan2.7-i2v`` ...). Users may configure either a base name
    (``happyhorse-1.1``) or a full name (``happyhorse-1.1-r2v``,
    ``wan2.7-i2v-2026-04-25``): an existing mode segment is replaced in
    place so dated variants keep their tail, otherwise the suffix is
    appended.

    A derived name is only as available as its model family: measured on a
    Bailian workspace endpoint, ``happyhorse-1.1`` serves t2v/i2v/r2v but
    has **no** ``-video-edit`` model, while ``happyhorse-1.0-video-edit``
    exists. Verify a name at zero cost by POSTing the video-synthesis
    endpoint **without** the ``X-DashScope-Async`` header: an existing
    model answers HTTP 403 ``AccessDenied`` ("does not support synchronous
    calls") and creates no task, a missing one answers HTTP 404
    ``InvalidParameter: Model not exist.``
    """

    normalized_mode = (mode or "r2v").strip().casefold() or "r2v"
    suffix = _MODE_SUFFIXES.get(normalized_mode)
    if suffix is None:
        raise ValueError(f"未知的视频生成 mode {mode!r}")
    base = model_name.strip()
    if is_wan3_video_model(base):
        return base
    lowered = base.casefold()
    for segment in _KNOWN_SUFFIX_SEGMENTS:
        index = lowered.find(segment)
        if index == -1:
            continue
        end = index + len(segment)
        # Only replace a full hyphen-delimited segment, not a substring of
        # a longer token (e.g. "-r2v2" must not match "-r2v").
        if end < len(base) and base[end] != "-":
            continue
        return f"{base[:index]}-{suffix}{base[end:]}"
    return f"{base}-{suffix}"


def configured_mode_segment(model_name: str) -> str | None:
    """The mode encoded in a configured model name, or ``None`` for bases.

    ``wan2.7-i2v`` encodes ``i2v``; ``happyhorse-1.1`` and other bare family
    names encode nothing. Follows the same full-segment matching rule as
    ``derive_video_model_name`` so dated variants and hyphen-token overlaps
    resolve identically.
    """

    suffix_to_mode = {
        f"-{value}": key for key, value in _MODE_SUFFIXES.items()
    }
    base = model_name.strip()
    lowered = base.casefold()
    for segment in _KNOWN_SUFFIX_SEGMENTS:
        index = lowered.find(segment)
        if index == -1:
            continue
        end = index + len(segment)
        if end < len(base) and base[end] != "-":
            continue
        return suffix_to_mode[segment]
    return None


def effective_video_model_name(
    model_name: str,
    mode: str,
    backend_key: str,
) -> str:
    """The model name a submission will actually carry.

    Single source of truth for both the submit path and the execution
    authorization snapshot: HappyHorse and Wan2.x name every mode, so a bare
    family name also derives the official sibling for the default r2v mode
    (``wan2.7`` -> ``wan2.7-r2v``). A configured name encoding another mode is
    replaced in place (``wan2.7-i2v`` -> ``wan2.7-r2v``). All-in-One Wan3 and
    backends in ``_CONFIGURED_NAME_BACKENDS`` keep the configured name as-is.
    """

    configured = model_name.strip()
    backend = backend_key.strip().casefold()
    if is_wan3_video_model(configured):
        return configured
    if backend in _CONFIGURED_NAME_BACKENDS:
        return configured
    normalized_mode = (mode or "r2v").strip().casefold() or "r2v"
    capability = video_model_capability(configured, backend)
    if capability.derives_mode_model:
        return derive_video_model_name(configured, normalized_mode)
    return configured


def _mode_guidance(model_name: str, protocol_backend: str = "") -> str:
    """One prompt block describing the mode matrix for the active model."""

    capability = video_model_capability(model_name, protocol_backend)
    supported = sorted(
        capability.supported_modes,
        key=VIDEO_MODES.index,
    )
    lines = [
        "生成模式矩阵（r2v_generation 的 mode 参数）：当前精确模型支持 "
        f"{', '.join(supported) if supported else '无（模型 ID 未收录）'}。",
    ]
    if "r2v" in supported:
        lines.append("- r2v：storyboard + 参考图生成视频（默认）。")
    if "t2v" in supported:
        lines.append("- t2v：纯文本生视频，不得携带任何参考素材。")
    if "i2v" in supported:
        lines.append(
            "- i2v：首帧生视频，必须传 firstFrameRef（exact 图片 version id，"
            "可用已选定的 storyboard 版本）；画幅跟随首帧。",
        )
    if "video_edit" in supported:
        lines.append(
            "- video_edit：按 prompt 指令编辑已有视频，必须传 videoRef（exact "
            "视频 version id）；输入需 3–60 秒，超过 15 秒时上游自动只取前 "
            "15 秒，输出时长跟随输入。",
        )
    rejected = [item for item in VIDEO_MODES if item not in supported]
    if rejected:
        lines.append(
            f"- 不支持的 mode（{', '.join(rejected)}）会被拒绝，不要尝试。",
        )
    return "\n".join(lines)


def _reference_guidance(
    model_name: str,
    protocol_backend: str = "",
) -> str:
    """One prompt block rendered from the official R2V media budget."""

    model_capability = video_model_capability(
        model_name,
        protocol_backend,
    )
    if not model_capability.known:
        return (
            "- 当前协议与精确模型 ID 没有匹配到 Creator 内置的官方视频"
            "能力表；不得创建或提交 r2v/t2v/i2v Element。"
        )
    if "r2v" not in model_capability.supported_modes:
        return "- 当前精确模型官方不支持 r2v，不得提交任何参考素材。"
    capability = video_reference_capability(model_name)
    if capability is None:
        return (
            "- 当前模型名没有匹配到 Creator 内置的官方视频参考能力表；"
            "不得提交 r2v 参考素材。若这是兼容网关别名，必须先映射到官方"
            "模型能力，不可套用 Wan 或通用默认值。"
        )
    if capability.max_reference_media == 0:
        return (
            "- 当前模型官方不支持任何 r2v 参考素材（例如 veo-3.1-lite 无"
            " referenceImages 能力），只能使用 t2v/i2v 模式。"
        )
    if capability.max_reference_videos == 0:
        return (
            f"- R2V 参考素材仅支持 1–{capability.max_reference_images} 张"
            "图片，不支持参考视频；storyboard 也计入图片总数。"
        )
    return (
        f"- R2V 参考预算：图片最多 {capability.max_reference_images} 张，"
        f"视频最多 {capability.max_reference_videos} 个，图片与视频合计"
        f"最多 {capability.max_reference_media} 个且至少 1 个；storyboard "
        "计入图片总数。超出时必须先缩减 Project 的 exact reference "
        "version 列表，不得静默截断。"
    )


def _family_constraint_guidance(
    model_name: str,
    protocol_backend: str = "",
) -> str:
    """Official duration/resolution/ratio constraints for the active family.

    Rendered into the R2V director prompt so the agent plans within the
    documented request contract instead of discovering violations as
    provider rejections.
    """
    # Provider guidance mirrors each official request contract explicitly.
    # pylint: disable=too-many-branches,too-many-return-statements
    backend = video_backend_key(model_name, protocol_backend)
    lowered = model_name.strip().casefold()
    if backend == "happyhorse":
        return "\n".join(
            [
                f"- 时长 duration 为 {HAPPYHORSE_MIN_DURATION_SECONDS}–"
                f"{HAPPYHORSE_MAX_DURATION_SECONDS} 秒的整数。",
                "- 分辨率仅支持 720P/1080P；画幅仅支持 "
                + "/".join(sorted(HAPPYHORSE_RATIOS))
                + "。",
            ],
        )
    if is_wan3_video_model(model_name):
        return "\n".join(
            [
                "- Wan3.0 是 All-in-One 模型，t2v/i2v/r2v 均提交同一个模型名，不派生模式后缀。",
                "- 时长 duration 为 2–30 秒的整数；分辨率仅支持 "
                "480P/720P/1080P；画幅支持 "
                "adaptive/16:9/4:3/1:1/3:4/9:16。",
                "- 默认生成有声视频；仅在内容不需要声音时设置 generateAudio=false。",
            ],
        )
    if backend == "veo":
        lines = [
            "- 时长 duration 仅支持 4/6/8 秒；使用参考图（r2v）或 1080p/4k 分辨率时必须为 8 秒。",
            "- 分辨率仅支持 720p/1080p/4k；画幅仅支持 16:9 或 9:16。",
            "- 参考素材仅接受图片（referenceImages，不支持参考视频）。",
        ]
        if "lite" in lowered:
            lines.append(
                "- veo-3.1-lite 不支持 4k 分辨率，也不支持参考图（r2v）。",
            )
        return "\n".join(lines)
    if backend == "kling":
        if "/" not in model_name:
            # Official channel (api-singapore.klingai.com, Bearer API Key).
            lines = [
                f"- prompt 不超过 {KLING_MAX_PROMPT_CHARS} 字符。",
            ]
            if is_kling_omni_model(model_name):
                lines += [
                    "- 时长 duration 为 3–15 秒的整数；分辨率仅支持" + " 720p/1080p/4k。",
                    "- r2v 参考图最多 7 张；可额外携带 1 个特征参考视频，"
                    + "此时参考图最多 4 张且 audio 必须为 off。video prompt"
                    + " 用 @image_N 按参考顺序引用图片（视频用 @video_1）。",
                    "- t2v 与仅参考图的 r2v 必须设置画幅，仅支持"
                    + " 16:9/9:16/1:1；i2v 画幅跟随首帧。",
                ]
            else:
                lines += [
                    "- 时长 duration 只能为 5 或 10 秒；分辨率仅支持"
                    + " 720p/1080p；生成原生音频时仅支持 1080p。",
                    "- 该模型不支持 r2v；参考生视频需改用 kling-3.0-omni。",
                ]
            return "\n".join(lines)
        return "\n".join(
            [
                f"- prompt 不超过 {KLING_MAX_PROMPT_CHARS} 字符，超出会报错。",
                f"- 时长 duration 为 {KLING_MIN_DURATION_SECONDS}–"
                + f"{KLING_MAX_DURATION_SECONDS} 秒的整数（携带参考视频时为"
                + " 3–10 秒）；分辨率档位由 mode 决定：std=720P、"
                + "pro=1080P、4k=4K。",
                "- t2v 与 r2v 必须设置画幅，仅支持 16:9/9:16/1:1；i2v 画幅跟随首帧，不可设置。",
                "- r2v（参考生视频）仅 kling/kling-v3-omni-video-generation"
                + " 支持：参考图最多 7 张；可额外携带 1 个特征参考视频，此时"
                + "参考图最多 4 张。video prompt 必须用 <<<image_N>>> 按"
                + " media 顺序引用参考图（视频用 <<<video_1>>>）。",
                "- 携带参考视频时 audio 必须为 false。",
            ],
        )
    if backend == "minimax":
        return "\n".join(
            [
                f"- prompt 不超过 {MINIMAX_MAX_PROMPT_CHARS} 字符。",
                "- Hailuo 2.3/Fast：768P 支持 6 或 10 秒，1080P 仅支持 "
                "6 秒；Hailuo-02 还支持 512P 6/10 秒；T2V-01/I2V-01 "
                "系列仅支持 720P 6 秒。",
                "- r2v（主体参考）仅 S2V-01 支持，且只接受 1 张角色参考图；其他 MiniMax 模型不支持 r2v。",
            ],
        )
    if backend == "vidu":
        name = model_name.strip().casefold()
        spec = VIDU_MODEL_SPECS.get(name) or VIDU_DIRECT_SPECS.get(name)
        if spec is None:
            return (
                "- 当前 Vidu 模型名既不在百炼托管列表也不在官方直连列表中，"
                "请改用 vidu/viduq3-*_reference2video（百炼）或 viduq3-mix 等"
                "（官方）系列模型。"
            )
        low, high = spec["durations"]
        lines = [
            f"- 时长 duration 为 [{low}, {high}] 秒的整数；分辨率仅支持"
            + f" {'/'.join(spec['resolutions'])}；画幅仅支持"
            + f" {'/'.join(spec['ratios'])}。",
            "- prompt 不超过 5000 字符。",
        ]
        if name in {"vidu/viduq2-pro_reference2video", "viduq2-pro"}:
            lines.append(
                "- viduq2-pro 支持参考视频：传入视频时图片限 1–4 张、视频限 1–2 个；仅图片时为 1–7 张。",
            )
        return "\n".join(lines)
    if backend == "seedance2":
        family = seedance_video_generation(model_name)
        spec = SEEDANCE_FAMILY_SPECS.get(family or "")
        if spec is None:
            return ""
        resolutions, low, high, allows_auto = spec
        auto_note = "，或 -1 表示模型自动规划时长" if allows_auto else ""
        return (
            f"- 时长 duration 为 [{low}, {high}] 秒的整数{auto_note}；"
            f"分辨率仅支持 {'/'.join(sorted(resolutions))}；画幅支持 "
            "16:9/4:3/1:1/3:4/9:16/21:9/adaptive。"
        )
    return ""


# Each return is an exact provider-specific protocol, kept separate to avoid
# accidentally blending incompatible reference syntaxes.
# pylint: disable-next=too-many-return-statements
def _model_reference_syntax_guidance(
    model_name: str,
    protocol_backend: str = "",
) -> str:
    """Exact provider token contract for references in the prompt text.

    Reference payload order and prompt identifiers are different concepts.
    Some providers expose literal identifiers, some number images and videos
    independently, and others carry references only in structured request
    fields.

    This describes the *wire* form, which really does differ per provider.
    Authors no longer write it: they use canonical ``[Image N]`` and
    ``render_reference_markers`` rewrites it at submit. What stays useful here
    is each provider's counting rule and its video-reference syntax, which the
    canonical image form does not cover.
    """

    normalized = model_name.strip()
    backend = video_backend_key(normalized, protocol_backend)
    if is_wan3_video_model(normalized):
        return (
            "- Wan3.0 All-in-One：中文 Prompt 用“图1、图2 …”和“视频1、"
            "视频2 …”；图片与视频按 media 中各自类型的出现顺序分别计数；"
            "storyboard 是第一张参考图，因此为“图1”。每次引用同时说明素材"
            "中的具体主体、动作或用途。"
        )
    if is_happyhorse_model(normalized):
        return (
            "- HappyHorse：只能使用 `[Image 1]`、`[Image 2]` …；这是 media "
            "数组中所有图片共用的单一顺序，storyboard 固定为第一张，因此是 "
            "`[Image 1]`。每次标记后说明图中具体对象。不要改写成“图1”、"
            "`image1` 或 `character1`，也不存在 `[Video N]`。"
        )
    if backend == "wan":
        if _WAN_27_MODEL_PATTERN.fullmatch(normalized):
            return (
                "- Wan 2.7：中文 Prompt 用“图1、图2 …”和“视频1、视频2 …”；"
                "英文 Prompt 用 `Image 1`、`Video 1`（首字母大写且英文单词与"
                "数字间有空格）。图片与视频按 media 中各自类型的出现顺序"
                "分别计数；storyboard 是第一张 reference_image，因此为“图1”。"
                "不得使用 Wan 2.6 的 `character1`。"
            )
        if _WAN_26_MODEL_PATTERN.fullmatch(normalized):
            return (
                "- Wan 2.6：只用 `character1`、`character2` …；按 "
                "reference_urls 的图片/视频混合总顺序统一计数，不按媒体类型"
                "分开。Runtime 的 storyboard 排在第一，因此对应 `character1`。"
                "每个 reference_url 必须只有一个主体；不得使用 Wan 2.7 的"
                "“图1/视频1”或 HappyHorse 方括号。"
            )
        return (
            "- 当前 Wan 名称没有匹配到已知 2.6/2.7 引用协议；不得猜测“图1”"
            "或 `character1`，在付费 R2V 提交前报告阻塞。"
        )
    if backend == "seedance2":
        return (
            "- Seedance API：中文 Prompt 用“图片1、图片2 …”“视频1、视频2 …”"
            "（有音频输入时用“音频1 …”），按 content 中同类型素材的出现顺序"
            "分别计数；英文可用 `image1`、`video1`。storyboard 是第一张 "
            "reference_image，因此为“图片1”。不得带 HappyHorse 方括号，也"
            "不要把 Wan 的“图1”当成统一语法。"
        )
    if backend == "kling":
        if "/" in normalized:
            return (
                "- Kling 百炼托管 Omni：严格使用 `<<<image_1>>>`、"
                "`<<<image_2>>>` … 与 `<<<video_1>>>`；图片和视频分别按 media "
                "顺序计数，storyboard 是 `<<<image_1>>>`。"
            )
        return (
            "- Kling 官方直连 Omni：严格使用 `@image_1`、`@image_2` … 与 "
            "`@video_1`；这些 ID 与 contents 中 refer_image/feature_video 的 id "
            "一致，storyboard 是 `@image_1`。不得使用百炼的三尖括号语法。"
        )
    if backend == "veo":
        return (
            "- Veo 3.1：参考图通过结构化 `referenceImages` 传入，官方 Prompt "
            "没有 `[Image N]`、`图N` 或 `@image_N` 位置标记。Prompt 直接用"
            "自然语言描述要保留的角色/产品及动作；参考职责只作为编译前合同，"
            "不要把虚构编号写进最终 Prompt。"
        )
    if backend == "minimax":
        return (
            "- MiniMax S2V-01：唯一角色图通过结构化 `subject_reference` 传入，"
            "Prompt 直接用角色名称描述动作；没有官方图片序号标记，不得写"
            " `[Image 1]`、`图1` 或 `@image_1`。"
        )
    if backend == "vidu":
        if "/" in normalized:
            return (
                "- Vidu 百炼托管参考生视频：中文 Prompt 的图片强调段使用"
                "“图1为…；图2为…”并按输入图片顺序计数；只有官方文档明确"
                "支持的标记才使用。参考视频没有已文档化的位置标记时，用"
                "自然语言说明其动作/运镜职责，不发明 `视频N`。"
            )
        return (
            "- Vidu 官方直连 flat reference2video：图片/视频通过结构化 "
            "`images`/`videos` 数组传入，官方 Prompt 没有位置标记。当前"
            " Runtime 未使用 subjects API，因此这里不会渲染出任何位置标记；"
            "直接用自然语言描述目标主体与动作。"
        )
    return (
        "- 当前模型没有已文档化的 Prompt 引用标记协议。照常写 "
        "`[Image N]`：Runtime 不会为它编造标记，而是改写成“第 N 张"
        "参考图”这类自然语言，因此不会有任何标记被误当作字面协议。"
    )


# CJK has no word boundary, so a bare "图\d" also matches inside 地图2, 视图1,
# 构图3, 草图2, 贴图1, 插图2, 截图3 … Enumerating those prefixes never ends;
# requiring that the token is not preceded by a CJK character is the actual
# rule, since a real marker starts a clause or follows punctuation. Without it
# ordinary prose triggered VIDEO_REFERENCE_SYNTAX_INVALID and GATED the node.
_POSITIONAL_REFERENCE_TOKEN = re.compile(
    r"(?:\[Image\s*\d+\]|(?<![\u4e00-\u9fff])(?:图片|图)\s*\d+|"
    r"Image\s+\d+|image\s*_?\d+|character\s*\d+|"
    r"<<<(?:image|video)_\d+>>>|@(?:image|video)_\d+)",
    re.IGNORECASE,
)


# Explicit family dispatch keeps incompatible provider grammars separate.
# pylint: disable-next=too-many-return-statements
def _image_reference_marker_spec(
    model_name: str,
    protocol_backend: str = "",
    *,
    language: str = "zh-CN",
) -> tuple[re.Pattern[str], str] | None:
    """Return the provider's pattern plus a ``{index}`` marker template.

    The template is stored rather than an index-1 literal: rebuilding one by
    substituting "1" silently misplaces the index the moment a literal
    contains another "1".
    """

    normalized = model_name.strip()
    backend = video_backend_key(normalized, protocol_backend)
    is_chinese = language.strip().casefold().startswith("zh")
    if is_happyhorse_model(normalized):
        return (re.compile(r"\[Image\s+(\d+)\]"), "[Image {index}]")
    if is_wan3_video_model(normalized) or (
        backend == "wan" and _WAN_27_MODEL_PATTERN.fullmatch(normalized)
    ):
        return (
            re.compile(r"图\s*(\d+)")
            if is_chinese
            else re.compile(r"\bImage\s+(\d+)\b", re.IGNORECASE),
            "图{index}" if is_chinese else "Image {index}",
        )
    if backend == "wan" and _WAN_26_MODEL_PATTERN.fullmatch(normalized):
        return (
            re.compile(r"\bcharacter\s*(\d+)\b", re.IGNORECASE),
            "character{index}",
        )
    if backend == "seedance2":
        return (
            re.compile(r"图片\s*(\d+)")
            if is_chinese
            else re.compile(r"\bimage\s*(\d+)\b", re.IGNORECASE),
            "图片{index}" if is_chinese else "image{index}",
        )
    if backend == "kling":
        if "/" in normalized:
            return (
                re.compile(r"<<<image_(\d+)>>>", re.IGNORECASE),
                "<<<image_{index}>>>",
            )
        return (
            re.compile(r"@image_(\d+)\b", re.IGNORECASE),
            "@image_{index}",
        )
    if backend == "vidu" and "/" in normalized:
        return (re.compile(r"图\s*(\d+)"), "图{index}")
    return None


def video_prompt_image_reference_markers(
    prompt: str,
    model_name: str,
    protocol_backend: str = "",
    *,
    language: str = "zh-CN",
) -> tuple[tuple[int, int, str], ...]:
    """Extract ``(index, offset, literal)`` for official image markers.

    An empty tuple means either the configured model uses structured
    references or the prompt did not use that model's exact marker syntax.
    Keeping extraction beside the capability table lets synchronous role
    review share one provider grammar with first-storyboard validation.
    """

    spec = _image_reference_marker_spec(
        model_name,
        protocol_backend,
        language=language,
    )
    if spec is None:
        return ()
    pattern, _literal = spec
    return tuple(
        (int(match.group(1)), match.start(), match.group(0))
        for match in pattern.finditer(prompt or "")
    )


def video_prompt_image_reference_marker(
    index: int,
    model_name: str,
    protocol_backend: str = "",
    *,
    language: str = "zh-CN",
) -> str | None:
    """Return the provider's exact marker literal for one image index.

    ``None`` means the configured model takes structured references, where
    inventing an inline number would misdescribe the actual payload.
    """

    spec = _image_reference_marker_spec(
        model_name,
        protocol_backend,
        language=language,
    )
    if spec is None:
        return None
    _pattern, template = spec
    return template.format(index=index)


def video_reference_marker_spec(
    model_name: str,
    protocol_backend: str = "",
    *,
    language: str = "zh-CN",
) -> ReferenceMarkerSpec | None:
    """This provider's in-prompt reference syntax, for canonical rendering.

    ``None`` means the model takes structured references and documents no
    per-image addressing, so canonical markers must be reworded rather than
    emitted.
    """

    spec = _image_reference_marker_spec(
        model_name,
        protocol_backend,
        language=language,
    )
    if spec is None:
        return None
    pattern, template = spec
    capability = video_reference_capability(
        effective_video_model_name(
            model_name.strip(),
            "r2v",
            video_backend_key(model_name.strip(), protocol_backend),
        ),
    )
    return ReferenceMarkerSpec(
        template=template,
        pattern=pattern,
        documentation_url=(capability.documentation_url if capability else ""),
    )


# Provider syntax is deliberately kept in one auditable dispatch table.
# pylint: disable-next=too-many-branches
def video_prompt_storyboard_reference_violation(
    prompt: str,
    model_name: str,
    protocol_backend: str = "",
    *,
    language: str = "zh-CN",
) -> str | None:
    """Validate the provider literal for the first storyboard reference.

    The exact payload is still assembled and checked at submit time. Keeping
    this narrow authoring check beside the capability catalog prevents sync
    review from growing a second, drifting provider-syntax table.
    """

    text = prompt or ""
    normalized = model_name.strip()
    backend = video_backend_key(normalized, protocol_backend)
    expected = _image_reference_marker_spec(
        normalized,
        protocol_backend,
        language=language,
    )

    # The canonical form is what authors write; the runtime renders it to the
    # provider literal at submit. Demanding the literal here would reject
    # every correctly authored prompt.
    addresses_first = any(
        index == 1 for index in canonical_marker_indices(text)
    )

    if expected is not None:
        pattern, template = expected
        literal = template.format(index=1)
        if not addresses_first and not any(
            int(match.group(1)) == 1 for match in pattern.finditer(text)
        ):
            return (
                f"当前模型 `{normalized or '未配置'}` 的 storyboard 第一参考"
                f"必须在 video_prompt 中用 `[Image 1]` 指代"
                f"（Runtime 会渲染为 `{literal}`）"
            )
        return None

    if backend in {"veo", "minimax"} or (
        backend == "vidu" and "/" not in normalized
    ):
        # Canonical markers are rewritten to prose for these models, so they
        # are not an invented provider token; strip them before looking.
        invented = _POSITIONAL_REFERENCE_TOKEN.search(
            CANONICAL_MARKER_PATTERN.sub("", text),
        )
        if invented is not None:
            return (
                f"当前模型 `{normalized or '未配置'}` 使用结构化参考，"
                f"video_prompt 不得发明位置标记 `{invented.group(0)}`"
            )
    return None


def video_model_prompt_guidance(
    model_name: str,
    protocol_backend: str = "",
) -> str:
    """Model-specific prompt-writing rules injected into Creator and R2V."""

    normalized = model_name.strip() or "未配置"
    backend = video_backend_key(normalized, protocol_backend)
    extra: list[str] = []
    if backend == "seedance2":
        # Prompt contract follows the official Seedance guides:
        # https://ark.volcengine.com/region:cn-beijing/docs/82379/2607689?lang=zh
        family = seedance_video_generation(normalized) or "未知"
        if family == "2.5":
            extra.append(
                "- Seedance 2.5 可以使用整数秒时间段；区间必须连续、无空档，"
                "不得使用小数秒。动作节点稠密时，把相邻节点合并为 3–6 个"
                "可执行时间段，每段只写一个核心状态变化与明确结束状态。",
            )
        else:
            extra.append(
                f"- Seedance {family} 不套用 2.5 的时间戳语法；使用“镜头 1 / "
                "镜头 2 …”或顺序段落表达镜头与动作推进，不写时间戳。",
            )
    family_constraints = _family_constraint_guidance(
        normalized,
        protocol_backend,
    )
    return "\n".join(
        item
        for item in (
            f"当前视频生成模型是 `{normalized}`。**引用参考图时统一写 "
            f"`[Image 1]`、`[Image 2]` …**，Runtime 会在提交前把它渲染成该"
            "模型官方文档规定的形式；不要自己写下面的字面语法，也不要跨模型"
            "套用。下面列出的是渲染结果与各模型的计数规则，供你确认编号含义：",
            _model_reference_syntax_guidance(normalized, protocol_backend),
            "- 参考职责是语义合同。`[Image N]` 的 N 就是该图在参考图序列中的"
            "位置（storyboard 为 1）；结构化引用模型没有位置标记，Runtime 会把"
            "标记改写为“第 N 张参考图”这类自然语言。参考视频若需在 Prompt 中"
            "点名，按上方该模型的视频标记规则自行书写——canonical 形式只覆盖"
            "参考图。无论哪种协议，采用项/排除项必须和 Runtime "
            "实际提交素材一致，storyboard 只提供阅读顺序、近似构图、动作链和"
            "镜头节奏，最终视频不继承宫格、边框、编号、箭头、彩色标记、"
            "说明文字、草图媒介或占位角色。",
            *extra,
            _reference_guidance(normalized, protocol_backend),
            family_constraints,
            _mode_guidance(normalized, protocol_backend),
        )
        if item
    )


# Duration guidance mirrors the provider capability families above.
# pylint: disable-next=too-many-return-statements
def video_model_duration_guidance(
    model_name: str,
    protocol_backend: str = "",
) -> str:
    """Concise duration planning contract for the Creator main agent.

    Duration is a provider capability, never a global Creator default.  Keep
    this surface beside the submit-time capability tables so planning can
    accept a 3-second beat or a 30-second generation unit when the configured
    model actually supports it, while still rejecting an invalid pairing.
    """

    normalized = model_name.strip() or "未配置"
    backend = video_backend_key(normalized, protocol_backend)
    if is_wan3_video_model(normalized):
        return (
            f"当前视频模型 `{normalized}`（Wan3.0 All-in-One）支持 "
            "2–30 秒整数。可按内容直接规划 2 秒短段或 30 秒长段，不套用"
            "固定 8–10 秒；t2v/i2v/r2v 均保持同一模型 ID。"
        )
    if backend == "happyhorse":
        return (
            f"当前视频模型 `{normalized}` 的 r2v/t2v/i2v 生成时长必须为 "
            f"{HAPPYHORSE_MIN_DURATION_SECONDS}–"
            f"{HAPPYHORSE_MAX_DURATION_SECONDS} 秒整数。3 秒短段合法；"
            "30 秒单段不合法，必须换用支持 30 秒的模型或按叙事边界拆段。"
        )
    if backend == "seedance2":
        family = seedance_video_generation(normalized)
        spec = SEEDANCE_FAMILY_SPECS.get(family or "")
        if spec is not None:
            _resolutions, low, high, allows_auto = spec
            auto = "，也可用 -1 让模型自动规划" if allows_auto else ""
            return (
                f"当前视频模型 `{normalized}`（Seedance {family}）支持 "
                f"{low}–{high} 秒整数{auto}。只要叙事适合，允许直接规划为"
                f" {low} 秒短段或 {high} 秒长段，不套用 8–10 秒默认值。"
            )
    if backend == "veo":
        if "lite" in normalized.casefold():
            reference_note = "该 Lite 型号不支持 r2v 参考图。"
        else:
            reference_note = "r2v 或 1080p/4k 时必须为 8 秒。"
        return (
            f"当前视频模型 `{normalized}` 只支持 4、6 或 8 秒；"
            + reference_note
            + "不得把范围中间的其他整数当作合法值。"
        )
    if backend == "kling":
        if is_kling_omni_model(normalized):
            return f"当前视频模型 `{normalized}` 支持 3–15 秒整数；携带特征" "参考视频时上限降为 10 秒。"
        return f"当前视频模型 `{normalized}` 只支持 5 或 10 秒。"
    if backend == "minimax":
        return (
            f"当前视频模型 `{normalized}` 的时长是离散能力：Hailuo 768P"
            " 支持 6/10 秒，1080P 仅 6 秒；T2V-01/I2V-01 为 6 秒。"
        )
    if backend == "vidu":
        lookup_name = normalized.casefold()
        spec = VIDU_MODEL_SPECS.get(lookup_name) or VIDU_DIRECT_SPECS.get(
            lookup_name,
        )
        if spec is not None:
            low, high = spec["durations"]
            return (
                f"当前视频模型 `{normalized}` 支持 {low}–{high} 秒整数。"
                "按内容选择任一合法时长，不套用固定 8–10 秒。"
            )
    return (
        f"当前视频模型 `{normalized}` 没有可注入的确定性时长表。不要使用"
        " Creator 全局默认时长；必须依据该模型的 provider 能力确认合法值，"
        "无法确认时在付费提交前报告阻塞。"
    )


def video_model_delegator_guidance(
    model_name: str,
    protocol_backend: str = "",
) -> str:
    """Concise exact-mode guard injected into the main Creator agent."""

    normalized = model_name.strip() or "未配置"
    capability = video_model_capability(normalized, protocol_backend)
    supported = sorted(capability.supported_modes, key=VIDEO_MODES.index)
    if not capability.known:
        return (
            f"当前视频模型 `{normalized}` 的精确能力未收录。不要创建 "
            "creation.type=r2v/t2v/i2v；执行层也会在上传素材和创建上游"
            "任务前拒绝。请先让用户选择已收录的官方模型 ID。"
        )
    effective = {
        mode: effective_video_model_name(
            normalized,
            mode,
            capability.backend,
        )
        for mode in supported
    }
    mapping = "、".join(f"{mode}→`{effective[mode]}`" for mode in supported)
    rejected = [mode for mode in VIDEO_MODES if mode not in supported]
    suffix_note = (
        "该家族会在提交时派生模式后缀。"
        if capability.derives_mode_model
        else "该模型是单模型能力声明，提交时保持原模型 ID。"
    )
    rejected_note = (
        " 不得创建这些视频类型：" + "、".join(rejected) + "。" if rejected else ""
    )
    constraints = _family_constraint_guidance(normalized, protocol_backend)
    guidance = (
        f"当前精确视频模型 `{normalized}` 仅允许 creation.type="
        f"{','.join(supported)}（{mapping}）。{suffix_note}{rejected_note}"
        " r2v 可由工作图在依赖就绪后自动生成；t2v/i2v 并不因此自动"
        "调度，只有用户目标确实需要且模型支持时才创建对应 Element。"
    )
    return f"{guidance}\n{constraints}" if constraints else guidance


def video_model_capability_payload(
    model_name: str,
    protocol_backend: str = "",
) -> dict[str, object]:
    """JSON-ready canonical capability description for the settings UI."""

    capability = video_model_capability(model_name, protocol_backend)
    modes = sorted(capability.supported_modes, key=VIDEO_MODES.index)
    return {
        "provider": capability.backend,
        "model": capability.model,
        "known": capability.known,
        "supportedModes": modes,
        "effectiveModels": {
            mode: effective_video_model_name(
                capability.model,
                mode,
                capability.backend,
            )
            for mode in modes
        },
        "derivesModeModel": capability.derives_mode_model,
        "documentationUrl": capability.documentation_url,
    }


__all__ = [
    "HAPPYHORSE_MAX_REFERENCE_IMAGES",
    "HAPPYHORSE_MAX_DURATION_SECONDS",
    "HAPPYHORSE_MIN_DURATION_SECONDS",
    "HAPPYHORSE_MODEL_PREFIX",
    "HAPPYHORSE_RATIOS",
    "HAPPYHORSE_RESOLUTIONS",
    "HAPPYHORSE_VIDEO_EDIT_KEPT_SECONDS",
    "HAPPYHORSE_VIDEO_EDIT_MAX_INPUT_SECONDS",
    "HAPPYHORSE_VIDEO_EDIT_MAX_REFERENCE_IMAGES",
    "HAPPYHORSE_VIDEO_EDIT_MIN_INPUT_SECONDS",
    "KLING_FEATURE_VIDEO_MAX_DURATION_SECONDS",
    "KLING_MAX_DURATION_SECONDS",
    "KLING_MAX_PROMPT_CHARS",
    "KLING_MIN_DURATION_SECONDS",
    "KLING_MODE_BY_RESOLUTION",
    "KLING_OMNI_DURATIONS",
    "KLING_OMNI_MODEL",
    "KLING_OMNI_RESOLUTIONS",
    "KLING_RATIOS",
    "KLING_REFER_MAX_IMAGES_WITH_VIDEO",
    "KLING_V26_DURATIONS",
    "KLING_V26_RESOLUTIONS",
    "MINIMAX_HAILUO_RESOLUTIONS",
    "MINIMAX_HAILUO_02_RESOLUTIONS",
    "MINIMAX_LEGACY_RESOLUTIONS",
    "MINIMAX_MAX_PROMPT_CHARS",
    "MINIMAX_SUBJECT_REFERENCE_MODEL",
    "SEEDANCE_FAMILY_SPECS",
    "VEO_DURATION_SECONDS",
    "VEO_RATIOS",
    "VEO_REFERENCE_DURATION_SECONDS",
    "VEO_RESOLUTIONS",
    "VIDU_DIRECT_SPECS",
    "VIDU_MAX_PROMPT_CHARS",
    "VIDU_MODEL_SPECS",
    "VIDU_SIZE_MAP",
    "VideoModelCapability",
    "VideoReferenceCapability",
    "VIDEO_MODES",
    "WAN_30_MAX_DURATION_SECONDS",
    "WAN_30_MAX_REFERENCE_VIDEO_SECONDS",
    "WAN_30_MIN_DURATION_SECONDS",
    "WAN_30_RATIOS",
    "WAN_30_RESOLUTIONS",
    "configured_mode_segment",
    "derive_video_model_name",
    "effective_video_model_name",
    "is_happyhorse_model",
    "is_kling_omni_model",
    "is_minimax_video_model",
    "is_vidu_model",
    "is_wan3_video_model",
    "seedance_video_generation",
    "validate_video_mode",
    "video_backend_key",
    "video_model_capability",
    "video_model_capability_payload",
    "video_model_delegator_guidance",
    "video_model_duration_guidance",
    "video_model_prompt_guidance",
    "video_model_supported_modes",
    "video_prompt_image_reference_marker",
    "video_reference_marker_spec",
    "video_prompt_image_reference_markers",
    "video_reference_capability",
    "video_prompt_storyboard_reference_violation",
    "video_reference_violation",
]
