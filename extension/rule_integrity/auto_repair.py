# -*- coding: utf-8 -*-
"""Automatic repair when built-in rule integrity verification fails."""
from __future__ import annotations

import asyncio
import logging

from .constants import (
    MAX_CONSECUTIVE_TIMEOUT_RETRIES,
    REPAIR_TIMEOUT_RETRY_DELAY_SECONDS,
)
from .enforcement import (
    auto_repair_abandoned,
    mark_auto_repair_abandoned,
    mark_auto_repair_finished,
    mark_auto_repair_started,
    mark_auto_repair_timeout_retry,
    reload_tool_guard_engine_rules,
    rule_integrity_lockdown_active,
)
from .models import RuleIntegrityRepairResult
from .repair import repair_default_builtin_rule_file

logger = logging.getLogger(__name__)

_repair_lock = asyncio.Lock()


async def run_trusted_source_repair(
    *,
    retry_after_abandon: bool = False,
) -> RuleIntegrityRepairResult | None:
    """Repair from GitHub with timeout retries while lockdown is active."""

    if not rule_integrity_lockdown_active():
        return None
    if auto_repair_abandoned() and not retry_after_abandon:
        return None

    async with _repair_lock:
        if not rule_integrity_lockdown_active():
            return None
        if auto_repair_abandoned() and not retry_after_abandon:
            return None

        from .runtime import get_rule_integrity_runtime

        runtime = get_rule_integrity_runtime()
        mark_auto_repair_started()
        succeeded = False
        consecutive_timeouts = 0
        last_result: RuleIntegrityRepairResult | None = None
        try:
            while True:
                result = await asyncio.to_thread(repair_default_builtin_rule_file)
                last_result = result
                if result.ok and result.integrity.ok:
                    succeeded = True
                    logger.info("Built-in tool guard rules auto-repaired successfully")
                    reload_tool_guard_engine_rules()
                    break

                if not result.connection_timeout:
                    logger.warning(
                        "Built-in tool guard rule auto-repair did not restore "
                        "integrity: %s",
                        result.message,
                    )
                    break

                consecutive_timeouts += 1
                mark_auto_repair_timeout_retry(consecutive_timeouts)
                await runtime.publish_status_if_changed("repair_timeout_retry")
                logger.warning(
                    "Built-in tool guard rule auto-repair timed out "
                    "retry=%s/%s",
                    consecutive_timeouts,
                    MAX_CONSECUTIVE_TIMEOUT_RETRIES,
                )

                if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUT_RETRIES:
                    mark_auto_repair_abandoned()
                    await runtime.publish_status_if_changed("repair_abandoned")
                    logger.error(
                        "Built-in tool guard rule auto-repair abandoned after "
                        "%s consecutive timeouts",
                        MAX_CONSECUTIVE_TIMEOUT_RETRIES,
                    )
                    break

                await asyncio.sleep(REPAIR_TIMEOUT_RETRY_DELAY_SECONDS)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Built-in tool guard rule auto-repair failed")
            succeeded = False
        finally:
            if not auto_repair_abandoned():
                mark_auto_repair_finished(succeeded=succeeded)
            if succeeded:
                await runtime.publish_status_if_changed("repair")

        return last_result


async def maybe_run_auto_repair(*, retry_after_abandon: bool = False) -> None:
    """Attempt trusted-source repair when lockdown is active."""

    await run_trusted_source_repair(retry_after_abandon=retry_after_abandon)
