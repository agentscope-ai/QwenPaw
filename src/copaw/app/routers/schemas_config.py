# -*- coding: utf-8 -*-
"""Request/response schemas for config API endpoints."""

from typing import Optional

from pydantic import BaseModel, Field

from ...config.config import ActiveHoursConfig
from ...constant import HEARTBEAT_DEFAULT_TIMEOUT_SECONDS


class HeartbeatBody(BaseModel):
    """Request body for PUT /config/heartbeat."""

    enabled: bool = False
    every: str = "6h"
    target: str = "main"
    timeout_seconds: int = Field(
        default=HEARTBEAT_DEFAULT_TIMEOUT_SECONDS,
        ge=1,
        alias="timeoutSeconds",
    )
    active_hours: Optional[ActiveHoursConfig] = Field(
        default=None,
        alias="activeHours",
    )

    model_config = {"populate_by_name": True, "extra": "allow"}
