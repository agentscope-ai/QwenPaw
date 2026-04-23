# -*- coding: utf-8 -*-
"""Request/response schemas for config API endpoints."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ...config.config import ActiveHoursConfig


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


class ChannelHealthResponse(BaseModel):
    """Response model for GET /config/channels/{channel_name}/health."""

    channel: str
    status: Literal["healthy", "unhealthy", "disabled"]
    detail: str = ""


class ChannelRestartResponse(BaseModel):
    """Response model for POST /config/channels/{channel_name}/restart."""

    channel: str
    status: Literal["restarted"]
    detail: str = ""
