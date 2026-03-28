# -*- coding: utf-8 -*-
"""Request/response schemas for config API endpoints."""

from typing import Optional

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
    heartbeat_ok_enabled: bool = True

    model_config = {"populate_by_name": True, "extra": "allow"}
