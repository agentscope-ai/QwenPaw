# -*- coding: utf-8 -*-
"""Pydantic models for the render self-review module (backend-internal).

The self-review switch is code-level only, so these models intentionally do
not join the frontend API contract; they are persisted under each Project's
``runtime/render-review/`` directory and consumed by the review loop.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewDimension(StrEnum):
    """Eight-row protocol: the seven vendored Appeal rubric rows
    (``vendor/media_toolkit/review_rubrics.APPEAL_RUBRIC_ROWS``, verbatim keys)
    plus one Creator engineering row that keeps the objective defect checks
    (black frames, silence, duration drift) from the original six-dimension
    protocol.
    """

    CONCEPT = "concept"
    CONTRACT = "contract"
    RHYTHM = "rhythm"
    RESTRAINT = "restraint"
    CRAFT = "craft"
    SOUND = "sound"
    TYPOGRAPHY_MOTION = "typography_motion"
    ENGINEERING = "engineering"

    @classmethod
    def _missing_(cls, value: object) -> "ReviewDimension | None":
        # Reports persisted before the eight-row protocol carry the old
        # six-dimension names; map them so history stays readable.
        legacy = {
            "visual_quality": cls.CRAFT,
            "pacing": cls.RHYTHM,
            "voiceover": cls.SOUND,
            "subtitles": cls.TYPOGRAPHY_MOTION,
            "duration_match": cls.ENGINEERING,
        }
        return legacy.get(str(value).casefold())


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
    # Appeal rubric 0-10 score; required for the concept row (score <= 5
    # forces a revise verdict per the upstream veto rule).
    score: int | None = Field(default=None, ge=0, le=10)


class ChallengeFinding(RenderReviewModel):
    """One near-miss challenge question verdict (APE-style polarity).

    ``ET`` confirms the ABSENCE of the hypothesized defect, ``CT``
    confirms its presence, ``NA`` marks the question as not applicable
    (a non-empty ``reason`` is mandatory for NA — anti-hallucination).
    """

    question_id: str
    question: str
    verdict: Literal["ET", "CT", "NA"]
    severity: Literal["minor", "major"] = "major"
    evidence_timestamp_ms: int | None = Field(default=None, ge=0)
    reason: str = ""
    suggestion: str = ""


class RenderReviewReport(RenderReviewModel):
    video_ref: str
    round: int = Field(ge=1)
    findings: list[ReviewFinding] = Field(default_factory=list)
    # Near-miss challenge verdicts appended by the challenge pass; kept
    # apart from the eight protocol rows so row parsing stays strict.
    challenge_findings: list[ChallengeFinding] = Field(default_factory=list)
    # Tier-0 objective facts snapshot (advisory hints shown to the VLM).
    objective_facts: dict[str, Any] | None = None
    verdict: Literal["pass", "revise"]
    created_at: datetime | None = None

    def failed_findings(self) -> list[ReviewFinding]:
        return [item for item in self.findings if not item.passed]

    def confirmed_challenges(self) -> list[ChallengeFinding]:
        return [
            item for item in self.challenge_findings if item.verdict == "CT"
        ]


__all__ = [
    "AudioProfile",
    "ChallengeFinding",
    "LoudnessSegment",
    "RenderReviewReport",
    "ReviewDimension",
    "ReviewFinding",
    "ReviewFrame",
]
