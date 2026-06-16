# -*- coding: utf-8 -*-
"""Pydantic models for built-in tool guard rule integrity APIs."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ToolGuardRuleIntegrityFindingResponse(BaseModel):
    file: str
    reason: str
    expected_sha256: Optional[str] = None
    actual_sha256: Optional[str] = None
    detail: str = ""


class ToolGuardRuleIntegrityResponse(BaseModel):
    ok: bool
    status: str
    message: str
    checked_at: Optional[str] = None
    findings: List[ToolGuardRuleIntegrityFindingResponse] = Field(
        default_factory=list,
    )
    rules_disabled: bool = False
    auto_repair_in_progress: bool = False
    auto_repair_completed: bool = False
    auto_repair_timeout_retry: int = 0
    auto_repair_abandoned: bool = False
    auto_repair_timeout_max: int = 5


class ToolGuardRuleIntegrityRepairResponse(BaseModel):
    ok: bool
    message: str
    source_url: str
    backup_path: Optional[str] = None
    integrity: ToolGuardRuleIntegrityResponse
