# -*- coding: utf-8 -*-
"""Event-driven rule integrity runtime: verify, repair, SSE, and publish."""
from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache
from typing import Any

from .api_projection import result_to_response
from .auto_repair import maybe_run_auto_repair
from .constants import (
    DANGEROUS_SHELL_RULES_NAME,
    MANIFEST_NAME,
    SIGNATURE_NAME,
)
from .enforcement import tick_auto_repair_display
from .enforcement import rule_integrity_lockdown_active
from .models import RuleIntegrityResult
from .sse_hub import RuleIntegritySSEHub
from .verifier import get_last_rule_integrity_status, verify_default_builtin_rule_files

logger = logging.getLogger(__name__)

WATCHED_RULE_FILES = frozenset(
    {
        DANGEROUS_SHELL_RULES_NAME,
        MANIFEST_NAME,
        SIGNATURE_NAME,
    },
)
DISPLAY_TICK_SECONDS = 2.0
WATCHDOG_INTERVAL_SECONDS = 300.0


class RuleIntegrityRuntime:
    def __init__(self) -> None:
        self.sse_hub = RuleIntegritySSEHub()
        self._verify_lock = asyncio.Lock()
        self._last_sse_fingerprint: tuple[Any, ...] | None = None
        self._suppress_until: dict[str, float] = {}

    def suppress_paths(self, *paths: str, ttl_seconds: float = 2.0) -> None:
        expires_at = time.monotonic() + ttl_seconds
        for path in paths:
            self._suppress_until[path] = expires_at

    def is_suppressed(self, filename: str) -> bool:
        expires_at = self._suppress_until.get(filename)
        if expires_at is None:
            return False
        if time.monotonic() >= expires_at:
            self._suppress_until.pop(filename, None)
            return False
        return True

    def status_event_payload(self) -> dict[str, Any]:
        response = result_to_response(get_last_rule_integrity_status())
        payload = response.model_dump()
        payload["type"] = "rule_integrity_status"
        return payload

    def _fingerprint(self, payload: dict[str, Any]) -> tuple[Any, ...]:
        return (
            payload.get("ok"),
            payload.get("status"),
            payload.get("rules_disabled"),
            payload.get("auto_repair_in_progress"),
            payload.get("auto_repair_completed"),
            payload.get("auto_repair_timeout_retry"),
            payload.get("auto_repair_abandoned"),
            payload.get("tamper_banner_cycle_active"),
        )

    async def publish_status_if_changed(self, source: str) -> bool:
        payload = self.status_event_payload()
        fingerprint = self._fingerprint(payload)
        if fingerprint == self._last_sse_fingerprint:
            return False
        self._last_sse_fingerprint = fingerprint
        payload["source"] = source
        await self.sse_hub.publish(payload)
        return True

    async def run_verify_and_react(self, *, source: str) -> RuleIntegrityResult:
        async with self._verify_lock:
            tick_auto_repair_display()
            result = await asyncio.to_thread(verify_default_builtin_rule_files)
            if rule_integrity_lockdown_active():
                await maybe_run_auto_repair(
                    retry_after_abandon=(source == "watchdog"),
                )
            await self.publish_status_if_changed(source)
            return result

    async def run_startup_check(self) -> RuleIntegrityResult:
        logger.info("rule_integrity_startup_check begin")
        result = await self.run_verify_and_react(source="startup")
        logger.info(
            "rule_integrity_startup_check finished ok=%s status=%s",
            result.ok,
            result.status,
        )
        return result


@lru_cache(maxsize=1)
def get_rule_integrity_runtime() -> RuleIntegrityRuntime:
    return RuleIntegrityRuntime()
