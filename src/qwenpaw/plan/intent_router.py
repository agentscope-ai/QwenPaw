# -*- coding: utf-8 -*-
"""Lightweight automatic plan intent routing."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanIntentRoute:
    """Result of automatic plan intent detection."""

    reason: str
    score: int
    matched: tuple[str, ...] = ()


_NEGATIVE_PATTERNS = (
    "不要计划",
    "不用计划",
    "别计划",
    "不需要计划",
    "直接回答",
    "just answer",
    "no plan",
    "without a plan",
)

_SIMPLE_IMAGE_PATTERNS = (
    "画一张",
    "生成一张",
    "做一张",
    "一张图片",
    "一张海报",
    "single image",
    "one image",
)

_COMPLEX_TERMS = (
    "计划",
    "拆解",
    "步骤",
    "方案",
    "完整流程",
    "端到端",
    "批量",
    "多页",
    "多阶段",
    "多个页面",
    "每个页面",
    "根据文档",
    "最后",
    "接着",
    "然后",
    "并且",
    "同时",
    "验证",
    "生成ppt",
    "pptx",
    "ppt",
    "slides",
    "presentation",
    "deck",
    "imagegen",
    "skill",
)

_PIPELINE_TERMS = (
    "先",
    "再",
    "接着",
    "然后",
    "最后",
    "first",
    "then",
    "after that",
    "finally",
)

_ARTIFACT_TERMS = (
    "ppt",
    "pptx",
    "slides",
    "presentation",
    "deck",
    "文档",
    "报告",
    "网页",
    "项目",
)

_TOOL_TERMS = (
    "imagegen",
    "pptx",
    "skill",
    "工具",
    "调用",
    "生成图片",
    "合成",
)

_THRESHOLDS = {
    "low": 8,
    "medium": 12,
    "high": 17,
}


def _contains_any(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text]


def _page_count_score(text: str) -> tuple[int, tuple[str, ...]]:
    matches = re.findall(r"(\d+)\s*(?:-|到|~)?\s*(\d+)?\s*(?:页|pages?|张)", text)
    score = 0
    labels: list[str] = []
    for first, second in matches:
        nums = [int(first)]
        if second:
            nums.append(int(second))
        if max(nums) >= 5:
            score += 6
            labels.append("many_pages")
    return score, tuple(labels)


class PlanIntentRouter:
    """Detect complex tasks that should start with a structured plan."""

    def __init__(
        self,
        *,
        threshold: str = "medium",
        auto_enabled: bool = True,
    ) -> None:
        self._threshold = _THRESHOLDS.get(threshold, _THRESHOLDS["medium"])
        self._auto_enabled = auto_enabled

    def route(self, query: str | None) -> PlanIntentRoute | None:
        if not self._auto_enabled:
            return None
        text = str(query or "").strip().lower()
        if not text:
            return None
        if _contains_any(text, _NEGATIVE_PATTERNS):
            logger.info("Plan router: disabled by user wording")
            return None

        matched: list[str] = []
        score = 0

        complex_hits = _contains_any(text, _COMPLEX_TERMS)
        score += min(len(complex_hits), 6) * 2
        matched.extend(complex_hits[:6])

        pipeline_hits = _contains_any(text, _PIPELINE_TERMS)
        if len(pipeline_hits) >= 2:
            score += 5
            matched.append("pipeline")

        artifact_hits = _contains_any(text, _ARTIFACT_TERMS)
        tool_hits = _contains_any(text, _TOOL_TERMS)
        if artifact_hits and tool_hits:
            score += 5
            matched.append("artifact_with_tools")

        if "imagegen" in text and ("ppt" in text or "pptx" in text):
            score += 8
            matched.append("imagegen_ppt_pipeline")

        page_score, page_labels = _page_count_score(text)
        score += page_score
        matched.extend(page_labels)

        if len(text) >= 120 and (pipeline_hits or artifact_hits):
            score += 3
            matched.append("long_request")

        if (
            score < self._threshold
            and _contains_any(text, _SIMPLE_IMAGE_PATTERNS)
            and not artifact_hits
        ):
            return None

        if score < self._threshold:
            logger.info(
                "Plan router: not complex enough score=%s threshold=%s",
                score,
                self._threshold,
            )
            return None

        return PlanIntentRoute(
            reason="complex_task",
            score=score,
            matched=tuple(dict.fromkeys(matched)),
        )
