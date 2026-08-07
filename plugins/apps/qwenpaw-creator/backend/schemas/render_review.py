# -*- coding: utf-8 -*-
"""Pydantic models for the render self-review module (backend-internal).

The self-review switch is code-level only, so these models intentionally do
not join the frontend API contract; they are persisted under each Project's
``runtime/render-review/`` directory and consumed by the review loop.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewDimension(StrEnum):
    """Six-dimension protocol adapted from the upstream video-edit skill."""

    VISUAL_QUALITY = "visual_quality"
    DURATION_MATCH = "duration_match"
    PACING = "pacing"
    VOICEOVER = "voiceover"
    SUBTITLES = "subtitles"
    ENGINEERING = "engineering"


class RenderReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ReviewFrame(RenderReviewModel):
    """One extracted evidence frame, resized to the VLM resolution budget."""

    timestamp_ms: int = Field(ge=0)
    image_path: str


class LoudnessSegment(RenderReviewModel):
    """A contiguous loudness segment summarized from the ebur128 timeline."""

    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    mean_momentary_lufs: float
    silent: bool


class AudioProfile(RenderReviewModel):
    """Audio evidence summary (ffmpeg ebur128) for the voiceover dimension."""

    has_audio: bool
    integrated_lufs: float | None = None
    loudness_segments: list[LoudnessSegment] = Field(default_factory=list)


class ReviewFinding(RenderReviewModel):
    dimension: ReviewDimension
    passed: bool
    severity: Literal["minor", "major"] = "minor"
    evidence_timestamp_ms: int | None = Field(default=None, ge=0)
    suggestion: str = ""


class RenderReviewReport(RenderReviewModel):
    video_ref: str
    round: int = Field(ge=1)
    findings: list[ReviewFinding] = Field(default_factory=list)
    verdict: Literal["pass", "revise"]
    created_at: datetime | None = None

    def failed_findings(self) -> list[ReviewFinding]:
        return [item for item in self.findings if not item.passed]


__all__ = [
    "AudioProfile",
    "LoudnessSegment",
    "RenderReviewReport",
    "ReviewDimension",
    "ReviewFinding",
    "ReviewFrame",
]
