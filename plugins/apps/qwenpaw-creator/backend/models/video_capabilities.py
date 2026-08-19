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

# Generation modes exposed on the r2v_generation tool. ``r2v`` keeps the
# historical behaviour; the others map onto the upstream model families
# (happyhorse-*-t2v/-i2v/-video-edit, wan*-t2v/-i2v).
VIDEO_MODES = ("r2v", "t2v", "i2v", "video_edit")

# backend key -> supported generation modes. seedance2 (Volcengine, not
# Bailian) stays r2v-only this cycle: real-model verification is limited to
# Bailian, so t2v/i2v are rejected at validation instead of shipped unproven.
VIDEO_MODE_MATRIX: dict[str, frozenset[str]] = {
    "happyhorse": frozenset({"r2v", "t2v", "i2v", "video_edit"}),
    "wan": frozenset({"r2v", "t2v", "i2v"}),
    "seedance2": frozenset({"r2v"}),
}

_MODE_SUFFIXES = {
    "r2v": "r2v",
    "t2v": "t2v",
    "i2v": "i2v",
    "video_edit": "video-edit",
}
# Longest first so "-video-edit" wins over any hyphen-token overlap.
_KNOWN_SUFFIX_SEGMENTS = ("-video-edit", "-t2v", "-i2v", "-r2v")


def is_happyhorse_model(model_name: str) -> bool:
    """True when the configured video model is a Bailian HappyHorse model."""

    return model_name.strip().casefold().startswith(HAPPYHORSE_MODEL_PREFIX)


def video_backend_key(model_name: str, protocol_backend: str = "") -> str:
    """Map a configured model (+ optional protocol backend) to a matrix key."""

    if is_happyhorse_model(model_name):
        return "happyhorse"
    if (
        protocol_backend.strip().casefold() == "seedance2"
        or "seedance" in model_name.casefold()
    ):
        return "seedance2"
    return "wan"


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
    if backend_key == "seedance2":
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
            "- 参考素材仅支持 1–9 张图片，不支持参考视频。\n"
            "- 视频时长必须是 3–15 秒的整数；分辨率仅支持 720P 或 1080P。\n"
            + _mode_guidance(normalized)
        )
    return (
        f"当前视频生成模型是 `{normalized}`。video prompt 用自然语言直接描述"
        "参考素材中的主体、场景与动作；参考素材顺序与 Element creation 的"
        " exact reference version 列表一致，storyboard 是第一参考。\n"
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
    "VIDEO_MODES",
    "VIDEO_MODE_MATRIX",
    "configured_mode_segment",
    "derive_video_model_name",
    "effective_video_model_name",
    "is_happyhorse_model",
    "validate_video_mode",
    "video_backend_key",
    "video_model_prompt_guidance",
]
