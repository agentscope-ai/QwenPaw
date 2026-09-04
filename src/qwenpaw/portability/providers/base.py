# -*- coding: utf-8 -*-
"""Read-only boundary for external Agent Harness migration sources."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ..models import ProviderInventory, SourceSession

ProgressReporter = Callable[[str], Awaitable[None]]
logger = logging.getLogger(__name__)

MAX_SESSION_HISTORY_ITEMS = 20_000
MAX_SESSION_HISTORY_BYTES = 64 * 1024 * 1024
MAX_TOTAL_SESSION_HISTORY_ITEMS = 100_000
MAX_TOTAL_SESSION_HISTORY_BYTES = 128 * 1024 * 1024


@dataclass
class SessionReadBudget:
    """Bound histories retained by one provider inventory."""

    items: int = 0
    bytes: int = 0
    exhausted: bool = False

    def add(self, session: SourceSession) -> str | None:
        item_count = len(session.history)
        byte_count = sum(
            len(item.model_dump_json().encode("utf-8", errors="replace"))
            for item in session.history
        )
        if item_count > MAX_SESSION_HISTORY_ITEMS:
            return (
                f"Session {session.source_id} exceeds the "
                f"{MAX_SESSION_HISTORY_ITEMS:,} history item limit."
            )
        if byte_count > MAX_SESSION_HISTORY_BYTES:
            return (
                f"Session {session.source_id} exceeds the 64 MiB "
                "history limit."
            )
        if (
            self.items + item_count > MAX_TOTAL_SESSION_HISTORY_ITEMS
            or self.bytes + byte_count > MAX_TOTAL_SESSION_HISTORY_BYTES
        ):
            self.exhausted = True
            return (
                "Session scan reached the 100,000 item / 128 MiB "
                "aggregate history limit."
            )
        self.items += item_count
        self.bytes += byte_count
        return None


async def report_progress(
    progress: ProgressReporter | None,
    message: str,
) -> None:
    """Treat presentation failures as non-fatal to migration work."""
    if progress is None:
        return
    try:
        await progress(message)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Migration progress reporter failed", exc_info=True)


async def report_result(
    progress: ProgressReporter | None,
    kind: str,
    *values: Any,
) -> None:
    await report_progress(
        progress,
        f"\x1e{kind}\t" + "\t".join(map(str, values)),
    )


def progress_milestone(index: int, total: int) -> bool:
    step = max(1, total // 20)
    return total <= 20 or index in {1, total} or index % step == 0


def make_inventory(
    provider_id: str,
    **values: Any,
) -> ProviderInventory:
    return ProviderInventory(
        provider_id=provider_id,
        provider_name=provider_id.title(),
        **values,
    )


class MigrationProvider(Protocol):
    """A source adapter may inspect external state but never mutate it."""

    provider_id: str

    async def inventory(
        self,
        *,
        limit: int,
        progress: ProgressReporter | None = None,
        include_sessions: bool = True,
        session_ids: set[str] | None = None,
    ) -> ProviderInventory:
        """Return a bounded, normalized inventory from the source."""
