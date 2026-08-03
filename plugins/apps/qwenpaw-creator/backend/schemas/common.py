# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ContentPart(StrictModel):
    type: Literal["text", "image_url", "video_url", "audio", "document"]
    text: str | None = None
    image_url: dict[str, Any] | None = None
    video_url: dict[str, Any] | None = None
    attachment: dict[str, Any] | None = None


class ExpectedTargetVersion(StrictModel):
    ref: str
    object_version: str = Field(alias="objectVersion")


class ErrorEnvelope(StrictModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
