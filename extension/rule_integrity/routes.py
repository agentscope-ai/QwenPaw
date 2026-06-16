# -*- coding: utf-8 -*-
"""FastAPI routes for built-in tool guard rule integrity."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from .api_projection import repair_result_to_response, result_to_response
from .auto_repair import run_trusted_source_repair
from .enforcement import mark_auto_repair_finished, rule_integrity_lockdown_active
from .host_bridge import stream_rule_integrity_events
from .repair import repair_default_builtin_rule_file
from .runtime import get_rule_integrity_runtime
from .schemas import (
    ToolGuardRuleIntegrityRepairResponse,
    ToolGuardRuleIntegrityResponse,
)
from .verifier import get_last_rule_integrity_status

router = APIRouter(tags=["config"])


@router.get(
    "/security/tool-guard/rules-integrity",
    response_model=ToolGuardRuleIntegrityResponse,
    summary="Get built-in tool guard rule integrity status",
)
async def get_tool_guard_rules_integrity() -> ToolGuardRuleIntegrityResponse:
    return result_to_response(get_last_rule_integrity_status())


@router.post(
    "/security/tool-guard/rules-integrity/repair",
    response_model=ToolGuardRuleIntegrityRepairResponse,
    summary="Repair built-in tool guard rule files from trusted source",
)
async def repair_tool_guard_rules_integrity() -> ToolGuardRuleIntegrityRepairResponse:
    runtime = get_rule_integrity_runtime()
    if rule_integrity_lockdown_active():
        result = await run_trusted_source_repair(retry_after_abandon=True)
        if result is None:
            result = await asyncio.to_thread(repair_default_builtin_rule_file)
    else:
        result = await asyncio.to_thread(repair_default_builtin_rule_file)
        if result.ok and result.integrity.ok:
            mark_auto_repair_finished(succeeded=True)
            await runtime.publish_status_if_changed("repair")
    return repair_result_to_response(result)


@router.get(
    "/security/tool-guard/rules-integrity/watch",
    summary="SSE stream for built-in rule integrity status changes",
)
async def watch_tool_guard_rules_integrity(request: Request) -> StreamingResponse:
    return StreamingResponse(
        stream_rule_integrity_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/security/integrity-protection/rules-integrity/check",
    response_model=ToolGuardRuleIntegrityResponse,
    summary="Run built-in rule integrity check without repair",
)
async def check_integrity_rule_entry() -> ToolGuardRuleIntegrityResponse:
    runtime = get_rule_integrity_runtime()
    result = await runtime.run_verify_and_react(source="manual_check")
    return result_to_response(result)
