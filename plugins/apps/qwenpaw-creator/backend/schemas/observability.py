# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import StrictModel


class ObservabilityConfigData(StrictModel):
    enabled: bool = True
    trace_directory: str = Field(
        default="observability/traces",
        min_length=1,
        alias="traceDirectory",
    )
    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = Field(
        default="INFO",
        alias="logLevel",
    )
    capture_content: bool = Field(default=False, alias="captureContent")
    retention_days: int = Field(
        default=14,
        ge=1,
        le=365,
        alias="retentionDays",
    )
