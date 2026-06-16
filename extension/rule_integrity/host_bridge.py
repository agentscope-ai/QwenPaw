# -*- coding: utf-8 -*-
"""Host wiring for built-in tool guard rule integrity."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from .constants import (
    DANGEROUS_SHELL_RULES_NAME,
    HASH_SCHEME,
    MANIFEST_NAME,
    RECOVERY_SOURCE_URL,
    SIGNATURE_NAME,
    SIGNATURE_SCHEME,
)
from .models import (
    RuleIntegrityFinding,
    RuleIntegrityRepairResult,
    RuleIntegrityResult,
)
from .repair import repair_default_builtin_rule_file
from .enforcement import (
    get_enforcement_projection,
    reload_tool_guard_engine_rules,
    rule_integrity_lockdown_active,
)
from .runtime import get_rule_integrity_runtime
from .sse_hub import RuleIntegritySSEHub
from .startup import run_rule_integrity_startup_check
from .verifier import (
    get_last_rule_integrity_status,
    sha256_normalized_content,
    verify_builtin_rule_files,
    verify_default_builtin_rule_files,
)


def run_passive_check() -> dict[str, Any]:
    """Run passive rule integrity check for Integrity Protection delivery."""

    return verify_default_builtin_rule_files().to_dict()


def get_router():
    """Return the FastAPI router for rule integrity delivery routes."""

    from .routes import router

    return router


async def stream_rule_integrity_events(request) -> AsyncIterator[str]:
    runtime = get_rule_integrity_runtime()
    yield RuleIntegritySSEHub.format_sse({"type": "connected"})
    yield RuleIntegritySSEHub.format_sse(runtime.status_event_payload())
    async for event in runtime.sse_hub.subscribe():
        if await request.is_disconnected():
            break
        yield RuleIntegritySSEHub.format_sse(event)
        await asyncio.sleep(0)


__all__ = [
    "DANGEROUS_SHELL_RULES_NAME",
    "HASH_SCHEME",
    "MANIFEST_NAME",
    "RECOVERY_SOURCE_URL",
    "SIGNATURE_NAME",
    "SIGNATURE_SCHEME",
    "RuleIntegrityFinding",
    "RuleIntegrityRepairResult",
    "RuleIntegrityResult",
    "get_last_rule_integrity_status",
    "get_enforcement_projection",
    "repair_default_builtin_rule_file",
    "rule_integrity_lockdown_active",
    "run_passive_check",
    "run_rule_integrity_startup_check",
    "get_router",
    "stream_rule_integrity_events",
    "sha256_normalized_content",
    "verify_builtin_rule_files",
    "verify_default_builtin_rule_files",
]
