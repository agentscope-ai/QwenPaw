# -*- coding: utf-8 -*-
"""Configuration models for semantic skill routing.

Uses Pydantic BaseModel following QwenPaw's config pattern.
No heavy dependencies — safe to import unconditionally.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SemanticRoutingConfig(BaseModel):
    """Semantic routing configuration.

    Corresponds to the ``semantic_routing`` section in config.json.
    All fields have safe defaults (feature disabled).
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Whether to enable semantic skill routing",
    )
    encoder: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformers model name for encoding",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        description="Number of skills to retrieve per query",
    )
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score threshold. "
        "Skills below this score are excluded from results. "
        "Set to 0.0 to disable score filtering.",
    )
