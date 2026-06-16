# -*- coding: utf-8 -*-
"""Filesystem watch for bundled tool guard rule assets."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchfiles import awatch

from .paths import default_rules_dir
from .runtime import WATCHED_RULE_FILES, RuleIntegrityRuntime

logger = logging.getLogger(__name__)

_DEBOUNCE_MS = 300


class RuleIntegrityWatchService:
    def __init__(self, runtime: RuleIntegrityRuntime) -> None:
        self._runtime = runtime
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._watch_loop(),
            name="rule-integrity-watch",
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _watch_loop(self) -> None:
        rules_dir = default_rules_dir()
        rules_dir.mkdir(parents=True, exist_ok=True)
        logger.info("rule_integrity_watch_started dir=%s", rules_dir)
        try:
            async for changes in awatch(
                rules_dir,
                debounce=_DEBOUNCE_MS,
                recursive=False,
            ):
                if self._stop_event.is_set():
                    break
                if not self._should_handle_changes(changes):
                    continue
                logger.info(
                    "rule_integrity_watch_change detected files=%s",
                    sorted({Path(path).name for _change, path in changes}),
                )
                try:
                    await self._runtime.run_verify_and_react(source="watch")
                except Exception:  # pylint: disable=broad-except
                    logger.exception("rule_integrity_watch_verify_failed")
        except asyncio.CancelledError:
            raise
        except Exception:  # pylint: disable=broad-except
            logger.exception("rule_integrity_watch_loop_failed")
        finally:
            logger.info("rule_integrity_watch_stopped dir=%s", rules_dir)

    def _should_handle_changes(self, changes) -> bool:
        for _change, abs_path in changes:
            filename = Path(abs_path).name
            if filename not in WATCHED_RULE_FILES:
                continue
            if self._runtime.is_suppressed(filename):
                continue
            return True
        return False
