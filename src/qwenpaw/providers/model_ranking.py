# -*- coding: utf-8 -*-
"""Versioned ranking evidence and automatic selection policy."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RankingEvidence(BaseModel):
    """One attributable evaluation, shared across service offerings."""

    model_config = ConfigDict(extra=f"forbid", frozen=True)
    model_id: str
    metric: str
    version: str
    score: float = Field(ge=0, allow_inf_nan=False)
    estimated: bool = False
    checked_at: str
    source: str


class Recommendation(BaseModel):
    """Explain why a model can or cannot be added automatically."""

    eligible: bool = False
    reason: str = f"unranked"


class RankingCatalog(BaseModel):
    """A reviewed benchmark snapshot, independent of service pricing."""

    model_config = ConfigDict(extra=f"forbid")
    metric: str
    version: str
    minimum_score: float = Field(ge=0, allow_inf_nan=False)
    models: list[RankingEvidence] = Field(default_factory=list)


@lru_cache(maxsize=1)
def ranking_catalog() -> RankingCatalog:
    """Load reviewed evidence once; no leaderboard network dependency."""
    path = Path(__file__).parent / f"data" / f"model_rankings.json"
    return RankingCatalog.model_validate_json(path.read_bytes())


def model_ranking(model_id: str | None) -> RankingEvidence | None:
    """Match canonical identities exactly, without guessing aliases."""
    return next(
        (
            item
            for item in ranking_catalog().models
            if item.model_id == model_id
        ),
        None,
    )


# Independent eligibility gates keep the first rejection reason stable.
# pylint: disable-next=too-many-return-statements
def recommend(
    ranking_id: str | None,
    billing: Literal["free", "paid", "unknown"],
    supports_tools: bool | None,
    available: bool,
) -> Recommendation:
    """Keep commercial, functional and quality gates independent."""
    if billing != f"free":
        return Recommendation(reason=f"billing_{billing}")
    if not available:
        return Recommendation(reason=f"unavailable")
    if supports_tools is not True:
        return Recommendation(reason=f"tools_unverified")
    evidence = model_ranking(ranking_id)
    policy = ranking_catalog()
    if evidence is None:
        return Recommendation(reason=f"unranked")
    if evidence.estimated:
        return Recommendation(reason=f"estimated_score")
    if (evidence.metric, evidence.version) != (policy.metric, policy.version):
        return Recommendation(reason=f"ranking_version_mismatch")
    if evidence.score < policy.minimum_score:
        return Recommendation(reason=f"below_quality_threshold")
    return Recommendation(eligible=True, reason=f"qualified_free")
