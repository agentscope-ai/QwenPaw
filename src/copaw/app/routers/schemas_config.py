# -*- coding: utf-8 -*-
"""Request/response schemas for config API endpoints."""

from typing import Optional

from pydantic import BaseModel, Field

from ...config.config import ActiveHoursConfig, LocalEmbeddingConfig


class LocalEmbeddingBody(LocalEmbeddingConfig):
    """Request body for PUT /config/agents/local-embedding.

    Inherits all fields from LocalEmbeddingConfig.
    """


class LocalEmbeddingTestResult(BaseModel):
    """Response for POST /config/agents/local-embedding/test."""

    success: bool
    message: str
    latency_ms: Optional[float] = None
    model_info: Optional[dict] = None


class ModelDownloadStatus(BaseModel):
    """Response for model download operations."""

    status: str  # "downloading", "completed", "error"
    progress: Optional[float] = None  # 0-100
    message: str
    local_path: Optional[str] = None


class HeartbeatBody(BaseModel):
    """Request body for PUT /config/heartbeat."""

    enabled: bool = False
    every: str = "6h"
    target: str = "main"
    active_hours: Optional[ActiveHoursConfig] = Field(
        default=None,
        alias="activeHours",
    )

    model_config = {"populate_by_name": True, "extra": "allow"}
