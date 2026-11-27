# -*- coding: utf-8 -*-
"""Report actual run lifetimes across transport reconnects."""

from __future__ import annotations

import asyncio


class RelayRuns:
    """Keep completion reports until the current Relay acknowledges them."""

    def __init__(self) -> None:
        self._running: dict[str, asyncio.Future] = {}
        self._finished: set[str] = set()
        self.changed = asyncio.Event()

    def select_node(self, node_id: str) -> None:
        """Drop reports belonging to a previous binding or account."""
        prefix = f"{node_id}."
        self._running = {
            key: task
            for key, task in self._running.items()
            if key.startswith(prefix)
        }
        self._finished = {
            key for key in self._finished if key.startswith(prefix)
        }

    def track(self, run_id: str, task: asyncio.Future | None) -> None:
        """Observe execution, independently of its HTTP subscribers."""
        if task is None:
            self._finished.add(run_id)
            self.changed.set()
            return
        if self._running.get(run_id) is task:
            return
        self._running[run_id] = task
        self._finished.discard(run_id)

        def finished(current: asyncio.Future) -> None:
            if self._running.get(run_id) is current:
                self._running.pop(run_id, None)
                self._finished.add(run_id)
                self.changed.set()

        task.add_done_callback(finished)
        self.changed.set()

    def report(self) -> dict[str, list[str]]:
        """Return a bounded snapshot without consuming completions."""
        return {
            "runs": [
                key for key, task in self._running.items() if not task.done()
            ],
            "finished": sorted(self._finished)[:128],
        }

    def acknowledge(self, finished: list[str]) -> None:
        """Forget only completions confirmed by the Relay."""
        self._finished.difference_update(finished)
        if self._finished:
            self.changed.set()
