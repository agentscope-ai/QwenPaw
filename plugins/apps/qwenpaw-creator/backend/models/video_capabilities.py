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


def is_happyhorse_model(model_name: str) -> bool:
    """True when the configured video model is a Bailian HappyHorse model."""

    return model_name.strip().casefold().startswith(HAPPYHORSE_MODEL_PREFIX)


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
            "- 视频时长必须是 3–15 秒的整数；分辨率仅支持 720P 或 1080P。"
        )
    return (
        f"当前视频生成模型是 `{normalized}`。video prompt 用自然语言直接描述"
        "参考素材中的主体、场景与动作；参考素材顺序与 Element creation 的"
        " exact reference version 列表一致，storyboard 是第一参考。"
    )


__all__ = [
    "HAPPYHORSE_MAX_REFERENCE_IMAGES",
    "HAPPYHORSE_MAX_DURATION_SECONDS",
    "HAPPYHORSE_MIN_DURATION_SECONDS",
    "HAPPYHORSE_MODEL_PREFIX",
    "HAPPYHORSE_RATIOS",
    "HAPPYHORSE_RESOLUTIONS",
    "is_happyhorse_model",
    "video_model_prompt_guidance",
]
