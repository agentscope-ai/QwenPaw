# -*- coding: utf-8 -*-
"""Application lifecycle hooks for rule integrity."""
from __future__ import annotations

import asyncio
import logging

from .enforcement import tick_auto_repair_display
from .runtime import (
    DISPLAY_TICK_SECONDS,
    WATCHDOG_INTERVAL_SECONDS,
    get_rule_integrity_runtime,
)
from .watch_service import RuleIntegrityWatchService

logger = logging.getLogger(__name__)


async def run_rule_integrity_startup_check() -> None:
    """Run verify/repair once during QwenPaw startup before agents load."""

    runtime = get_rule_integrity_runtime()
    await runtime.run_startup_check()


async def run_rule_integrity_runtime(
    *,
    watchdog_interval_seconds: float = WATCHDOG_INTERVAL_SECONDS,
    display_tick_seconds: float = DISPLAY_TICK_SECONDS,
) -> None:
    """Background runtime: filesystem watch, display ticks, and slow watchdog."""

    runtime = get_rule_integrity_runtime()
    watch = RuleIntegrityWatchService(runtime)
    await watch.start()
    next_watchdog_at = asyncio.get_running_loop().time() + watchdog_interval_seconds
    try:
        while True:
            tick_auto_repair_display()
            await runtime.publish_status_if_changed("display_tick")
            loop = asyncio.get_running_loop()
            now = loop.time()
            sleep_for = min(display_tick_seconds, max(0.0, next_watchdog_at - now))
            await asyncio.sleep(sleep_for)
            now = loop.time()
            if now < next_watchdog_at:
                continue
            try:
                await runtime.run_verify_and_react(source="watchdog")
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "rule_integrity_watchdog_verify_failed",
                    exc_info=True,
                )
            next_watchdog_at = now + watchdog_interval_seconds
    finally:
        await watch.stop()
        await runtime.sse_hub.close_all()


# Backward-compatible alias for host bridge imports.
periodic_rule_integrity_check = run_rule_integrity_runtime
