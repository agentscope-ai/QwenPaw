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


@dataclass(frozen=True, slots=True)
class VideoReferenceCapability:
    """Official R2V reference-media contract for one model family."""

    family: str
    max_reference_images: int
    max_reference_videos: int
    max_reference_media: int
    documentation_url: str


_HAPPYHORSE_REFERENCE_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/"
    "happyhorse-reference-to-video-api-reference"
)
_WAN_27_REFERENCE_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/video-to-video-guide"
)
_WAN_26_REFERENCE_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/"
    "legacy-wan-reference-to-video-api-reference"
)
_SEEDANCE_20_REFERENCE_DOCUMENTATION = "https://arxiv.org/abs/2604.14148"
_SEEDANCE_ARK_DOCUMENTATION = "https://www.volcengine.com/docs/82379/1520757"
_VEO_REFERENCE_DOCUMENTATION = "https://ai.google.dev/gemini-api/docs/veo"
_KLING_REFERENCE_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/"
    "kling-video-generation-api-reference/"
)
_MINIMAX_REFERENCE_DOCUMENTATION = (
    "https://platform.minimax.io/docs/api-reference/video-generation-t2v"
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
_WAN_27_REFERENCE_PATTERN = re.compile(
    r"^wan2\.7(?:-r2v)?(?:-20\d{2}-\d{2}-\d{2})?$",
    re.IGNORECASE,
)
_WAN_26_REFERENCE_PATTERN = re.compile(
    r"^wan2\.6(?:-r2v(?:-flash)?)?(?:-20\d{2}-\d{2}-\d{2})?$",
    re.IGNORECASE,
)
_SEEDANCE_20_REFERENCE_PATTERN = re.compile(
    r"^(?:doubao-)?seedance-?2(?:-0)?(?:-(?:pro|lite|fast))?(?:-\d{6})?$",
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

# backend key -> supported generation modes. seedance2 (Volcengine Ark)
# documents 文生视频 / 首帧 / 全模态参考, so t2v/i2v/r2v are exposed; veo,
# kling and minimax document text-to-video, image-to-video and their own
# reference flavours (referenceImages / multi-image2video /
# subject_reference); the Bailian-hosted Vidu models are
# reference-to-video only.
VIDEO_MODE_MATRIX: dict[str, frozenset[str]] = {
    "happyhorse": frozenset({"r2v", "t2v", "i2v", "video_edit"}),
    "wan": frozenset({"r2v", "t2v", "i2v"}),
    "seedance2": frozenset({"r2v", "t2v", "i2v"}),
    "veo": frozenset({"r2v", "t2v", "i2v"}),
    "kling": frozenset({"r2v", "t2v", "i2v"}),
    "minimax": frozenset({"r2v", "t2v", "i2v"}),
    "vidu": frozenset({"r2v"}),
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
    {"seedance2", "veo", "kling", "minimax", "vidu"},
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
MINIMAX_LEGACY_RESOLUTIONS: dict[str, tuple[int, ...]] = {"720P": (6,)}
MINIMAX_MAX_PROMPT_CHARS = 2000
MINIMAX_SUBJECT_REFERENCE_MODEL = "S2V-01"

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
        "durations": (0, 10),
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


def is_happyhorse_model(model_name: str) -> bool:
    """True when the configured video model is a Bailian HappyHorse model."""

    return model_name.strip().casefold().startswith(HAPPYHORSE_MODEL_PREFIX)


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
    if normalized_protocol in {"veo", "kling", "minimax", "vidu"}:
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
    if _WAN_27_REFERENCE_PATTERN.fullmatch(normalized):
        return _WAN_27_REFERENCE_CAPABILITY
    if _WAN_26_REFERENCE_PATTERN.fullmatch(normalized):
        return _WAN_26_REFERENCE_CAPABILITY
    if _VEO_31_LITE_REFERENCE_PATTERN.fullmatch(normalized):
        return _VEO_31_LITE_REFERENCE_CAPABILITY
    if _VEO_31_REFERENCE_PATTERN.fullmatch(normalized):
        return _VEO_31_REFERENCE_CAPABILITY
    if _KLING_OMNI_REFERENCE_PATTERN.fullmatch(normalized):
        return _KLING_OMNI_REFERENCE_CAPABILITY
    if _KLING_DIRECT_OMNI_REFERENCE_PATTERN.fullmatch(normalized):
        return _KLING_DIRECT_OMNI_REFERENCE_CAPABILITY
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
    supported = VIDEO_MODE_MATRIX.get(backend_key, frozenset({"r2v"}))
    if normalized not in supported:
        alternatives = " / ".join(
            key
            for key, modes in VIDEO_MODE_MATRIX.items()
            if normalized in modes
        )
        raise ValueError(
            f"当前视频模型 `{model_name}`（{backend_key}）不支持 "
            f"mode={normalized}；该模型仅支持 {', '.join(sorted(supported))}。"
            f"mode={normalized} 需要切换到 {alternatives} 系模型",
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
    authorization snapshot: HappyHorse names every mode (so even the default
    r2v derives ``-r2v``), other Bailian families derive for the non-default
    modes and whenever the configured name encodes a *different* mode (a
    configured ``wan2.7-i2v`` cannot serve an r2v request as-is, so it
    resolves to ``wan2.7-r2v``). A mode-less configured name keeps the
    historical byte-identical r2v behaviour, and seedance2 always uses the
    configured name as-is.
    """

    configured = model_name.strip()
    backend = backend_key.strip().casefold()
    if backend in _CONFIGURED_NAME_BACKENDS:
        return configured
    normalized_mode = (mode or "r2v").strip().casefold() or "r2v"
    if backend_key == "happyhorse" or normalized_mode != "r2v":
        return derive_video_model_name(configured, normalized_mode)
    encoded = configured_mode_segment(configured)
    if encoded is not None and encoded != normalized_mode:
        return derive_video_model_name(configured, normalized_mode)
    return configured


def _mode_guidance(model_name: str) -> str:
    """One prompt block describing the mode matrix for the active model."""

    backend = video_backend_key(model_name)
    supported = sorted(
        VIDEO_MODE_MATRIX.get(backend, frozenset({"r2v"})),
        key=VIDEO_MODES.index,
    )
    lines = [
        "生成模式矩阵（r2v_generation 的 mode 参数）：当前模型支持 " f"{', '.join(supported)}。",
        "- r2v：storyboard + 参考图生成视频（默认，保持现状）。",
    ]
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


def _reference_guidance(model_name: str) -> str:
    """One prompt block rendered from the official R2V media budget."""

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
) -> str:
    """Official duration/resolution/ratio constraints for the active family.

    Rendered into the R2V director prompt so the agent plans within the
    documented request contract instead of discovering violations as
    provider rejections.
    """
    # pylint: disable=too-many-return-statements
    backend = video_backend_key(model_name)
    lowered = model_name.strip().casefold()
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
                "- Hailuo 系列：768P 支持 6 或 10 秒，1080P 仅支持 6 秒；T2V-01/I2V-01 系列仅支持 720P 6 秒。",
                "- r2v（主体参考）仅 S2V-01 支持，且只接受 1 张角色参考图；其他 MiniMax 模型不支持 r2v。",
            ],
        )
    if backend == "vidu":
        name = model_name.strip()
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


def video_model_prompt_guidance(model_name: str) -> str:
    """Model-specific prompt-writing rules injected into the R2V director.

    The baseline reference-order contract lives in the static prompt; this
    only adds requirements that depend on which video model is configured,
    so the static prompt stays model-agnostic.
    """

    normalized = model_name.strip() or "未配置"
    if is_happyhorse_model(normalized):
        return (
            f"当前视频生成模型是 `{normalized}`（HappyHorse 参考生视频），"
            "video prompt 必须遵守其参考指代协议：\n"
            "- 用 `[Image N]` 指代第 N 个参考素材，顺序与 Element creation 的"
            " exact reference version 列表一致；storyboard 是第一参考，即 `[Image 1]`。\n"
            "- 每次指代都要说明该参考图中的具体对象，例如“[Image 1] 分镜图中的角色”。\n"
            + _reference_guidance(normalized)
            + "\n"
            "- 视频时长必须是 3–15 秒的整数；分辨率仅支持 720P 或 1080P。\n"
            + _mode_guidance(normalized)
        )
    return (
        f"当前视频生成模型是 `{normalized}`。video prompt 用自然语言直接描述"
        "参考素材中的主体、场景与动作；参考素材顺序与 Element creation 的"
        " exact reference version 列表一致，storyboard 是第一参考。\n"
        + _reference_guidance(normalized)
        + "\n"
        + (
            _family_constraint_guidance(normalized) + "\n"
            if _family_constraint_guidance(normalized)
            else ""
        )
        + _mode_guidance(normalized)
    )


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
    "VideoReferenceCapability",
    "VIDEO_MODES",
    "VIDEO_MODE_MATRIX",
    "configured_mode_segment",
    "derive_video_model_name",
    "effective_video_model_name",
    "is_happyhorse_model",
    "is_kling_omni_model",
    "is_minimax_video_model",
    "is_vidu_model",
    "seedance_video_generation",
    "validate_video_mode",
    "video_backend_key",
    "video_model_prompt_guidance",
    "video_reference_capability",
    "video_reference_violation",
]
