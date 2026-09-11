# -*- coding: utf-8 -*-
"""Retry local publication of an already materialized provider result."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from services.runtime_files.errors import LockTimeoutError
from utils.logger import setup_logger

logger = setup_logger(__name__)
_Result = TypeVar("_Result")
MAX_PUBLICATION_ATTEMPTS = 5


async def commit_with_lock_retry(
    commit_if_live: Callable[[], _Result],
    *,
    project_id: str,
    task_id: str,
) -> _Result:
    """Retry lock contention without repeating provider work.

    The callback must recheck durable cancellation, input freshness, and
    whether its stable transaction already committed on every attempt.
    No lock is retained during the cancellable backoff. Other failures
    retain their existing failure/quarantine behavior.
    """
    for attempt in range(MAX_PUBLICATION_ATTEMPTS):
        try:
            return await asyncio.to_thread(commit_if_live)
        except LockTimeoutError:
            if attempt + 1 == MAX_PUBLICATION_ATTEMPTS:
                raise
            logger.warning(
                "media publication lock busy; retrying local commit "
                "project=%s task=%s attempt=%s/%s",
                project_id,
                task_id,
                attempt + 1,
                MAX_PUBLICATION_ATTEMPTS,
            )
            await asyncio.sleep(min(0.25 * 2**attempt, 2.0))
    raise AssertionError("Publication retry budget exhausted")
