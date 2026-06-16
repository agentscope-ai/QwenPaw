# -*- coding: utf-8 -*-
"""Pydantic models for Integrity Protection delivery APIs."""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from ...security.rule_integrity_bridge import (
    ToolGuardRuleIntegrityFindingResponse,
    ToolGuardRuleIntegrityRepairResponse,
    ToolGuardRuleIntegrityResponse,
)

__all__ = [
    "HealthCheckFixRequest",
    "HealthCheckFixResponse",
    "HealthCheckScanRequest",
    "HealthCheckScanResponse",
    "IntegrityProtectionSettingsResponse",
    "FileBaselineProtectionActionRequest",
    "FileBaselineProtectionActionResponse",
    "FileBaselineProtectionAlertsResponse",
    "FileBaselineProtectionSettingsResponse",
    "FileBaselineProtectionSettingsUpdateRequest",
    "FileBaselineWorkspaceBrowseEntry",
    "FileBaselineWorkspaceBrowseResponse",
    "ToolGuardRuleIntegrityFindingResponse",
    "ToolGuardRuleIntegrityRepairResponse",
    "ToolGuardRuleIntegrityResponse",
]


class IntegrityProtectionSettingsResponse(BaseModel):
    file_baseline_enabled: bool = False
    health_check_enabled: bool = False
    rule_integrity_check_passive: bool = True
    protected_paths: List[str] = Field(default_factory=list)
    menus: List[str] = Field(default_factory=list)


class HealthCheckScanResponse(BaseModel):
    scan_id: str
    read_only: bool
    progress: int
    check_items: List[dict[str, Any]] = Field(default_factory=list)
    risk_summary: List[str] = Field(default_factory=list)
    repair_suggestions: List[dict[str, Any]] = Field(default_factory=list)
    mutated_files: List[str] = Field(default_factory=list)


class HealthCheckScanRequest(BaseModel):
    deep: bool = False


class HealthCheckFixRequest(BaseModel):
    fix_id: str
    selected_repair: str = ""


class HealthCheckFixResponse(BaseModel):
    confirmed: bool
    selected_repair: str
    fix_id: str
    executed: bool
    exit_code: int
    output: List[str] = Field(default_factory=list)


class FileBaselineProtectionSettingsResponse(BaseModel):
    enabled: bool = False
    pilot_mode: bool = True
    protected_targets: List[str] = Field(default_factory=list)
    protected_paths: List[str] = Field(default_factory=list)
    baseline_established: bool = False
    baseline_cleared_at: Optional[str] = None
    open_alert_count: int = 0
    scan_status: Optional[str] = None
    last_scan_at: Optional[str] = None
    last_scan_drift_count: Optional[int] = None
    agents: List[dict[str, Any]] = Field(default_factory=list)


class FileBaselineProtectionSettingsUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    protected_targets: Optional[List[str]] = None
    confirmation_phrase: Optional[str] = None


class FileBaselineProtectionAlertsResponse(BaseModel):
    enabled: bool = False
    scanning: bool = False
    alerts: List[dict[str, Any]] = Field(default_factory=list)
    open_alert_count: int = 0


class FileBaselineProtectionActionRequest(BaseModel):
    alert_id: str
    confirmation_phrase: str


class FileBaselineProtectionActionResponse(BaseModel):
    confirmed: bool
    message: Optional[str] = None
    alert_id: Optional[str] = None
    action: Optional[str] = None


class FileBaselineWorkspaceBrowseEntry(BaseModel):
    name: str
    type: str
    rel_path: str
    size: Optional[int] = None


class FileBaselineWorkspaceBrowseResponse(BaseModel):
    agent_id: str
    workspace_label: str
    current_path: str
    parent_path: str
    default_path: str
    entries: List[FileBaselineWorkspaceBrowseEntry] = Field(default_factory=list)
