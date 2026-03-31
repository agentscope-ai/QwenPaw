# -*- coding: utf-8 -*-
"""Pydantic data models for providers and models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelSlotConfig(BaseModel):
    provider_id: str = Field(default="")
    model: str = Field(default="")


class ActiveModelsInfo(BaseModel):
    active_llm: ModelSlotConfig | None
