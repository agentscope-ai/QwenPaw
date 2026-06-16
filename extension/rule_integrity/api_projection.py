# -*- coding: utf-8 -*-
"""Map rule integrity domain results to API response models."""
from __future__ import annotations

from .models import RuleIntegrityRepairResult, RuleIntegrityResult
from .enforcement import get_enforcement_projection
from .schemas import (
    ToolGuardRuleIntegrityFindingResponse,
    ToolGuardRuleIntegrityRepairResponse,
    ToolGuardRuleIntegrityResponse,
)


def result_to_response(status: RuleIntegrityResult) -> ToolGuardRuleIntegrityResponse:
    projection = get_enforcement_projection()
    return ToolGuardRuleIntegrityResponse(
        ok=status.ok,
        status=status.status,
        message=status.message,
        checked_at=status.checked_at,
        findings=[
            ToolGuardRuleIntegrityFindingResponse(**finding.to_dict())
            for finding in status.findings
        ],
        rules_disabled=bool(projection["rules_disabled"]),
        auto_repair_in_progress=bool(projection["auto_repair_in_progress"]),
        auto_repair_completed=bool(projection["auto_repair_completed"]),
        auto_repair_timeout_retry=int(projection["auto_repair_timeout_retry"]),
        auto_repair_abandoned=bool(projection["auto_repair_abandoned"]),
        auto_repair_timeout_max=int(projection["auto_repair_timeout_max"]),
        tamper_banner_cycle_active=bool(projection["tamper_banner_cycle_active"]),
    )


def repair_result_to_response(
    result: RuleIntegrityRepairResult,
) -> ToolGuardRuleIntegrityRepairResponse:
    return ToolGuardRuleIntegrityRepairResponse(
        ok=result.ok,
        message=result.message,
        source_url=result.source_url,
        backup_path=result.backup_path,
        integrity=result_to_response(result.integrity),
    )
