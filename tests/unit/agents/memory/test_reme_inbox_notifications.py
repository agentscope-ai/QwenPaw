# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Inbox notification policy for ReMe memory jobs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


def _manager() -> ReMeLightMemoryManager:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    manager.get_memory_config = lambda: SimpleNamespace(
        auto_memory_inbox_push_enabled=True,
        auto_dream_inbox_push_enabled=True,
    )
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_name", "response", "expected"),
    [
        (
            "auto_memory",
            SimpleNamespace(
                success=True,
                answer="No memory change",
                metadata={"modified": False},
            ),
            False,
        ),
        (
            "auto_memory",
            SimpleNamespace(
                success=True,
                answer="Memory updated",
                metadata={"modified": True},
            ),
            True,
        ),
        (
            "auto_memory",
            SimpleNamespace(
                success=False,
                answer="Memory update failed",
                metadata={"modified": False},
            ),
            True,
        ),
        (
            "auto_dream",
            SimpleNamespace(
                success=True,
                answer="No files found",
                metadata={
                    "modified": False,
                    "dream": {
                        "changed_paths": [],
                        "deleted_paths": [],
                        "files_scanned": 0,
                    },
                },
            ),
            False,
        ),
        (
            "auto_dream",
            SimpleNamespace(
                success=True,
                answer="All files unchanged",
                metadata={
                    "modified": False,
                    "dream": {
                        "changed_paths": ["memory/2026-08-18.md"],
                        "deleted_paths": [],
                        "files_scanned": 2,
                        "files_unchanged": 2,
                    },
                },
            ),
            False,
        ),
        (
            "auto_dream",
            SimpleNamespace(
                success=True,
                answer="Memory organized",
                metadata={
                    "modified": True,
                    "dream": {
                        "changed_paths": ["memory/2026-08-18.md"],
                        "deleted_paths": [],
                    },
                },
            ),
            True,
        ),
        (
            "auto_dream",
            SimpleNamespace(
                success=True,
                answer="Memory catalog updated",
                metadata={
                    "modified": False,
                    "dream": {
                        "changed_paths": [],
                        "deleted_paths": ["memory/2026-08-17.md"],
                    },
                },
            ),
            True,
        ),
        (
            "auto_dream",
            SimpleNamespace(
                success=False,
                answer="Memory organization failed",
                metadata={
                    "modified": False,
                    "dream": {
                        "changed_paths": [],
                        "deleted_paths": [],
                    },
                },
            ),
            True,
        ),
        (
            "auto_dream",
            SimpleNamespace(
                success=True,
                answer="Result from an older ReMe version",
                metadata={},
            ),
            True,
        ),
    ],
)
async def test_memory_inbox_only_suppresses_successful_noops(
    job_name,
    response,
    expected,
) -> None:
    """Only definitive successful no-ops should stay out of the inbox."""
    manager = _manager()

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        new_callable=AsyncMock,
        return_value={"id": "event-1", "status": "success"},
    ) as append_event:
        emitted = await manager._append_reme_job_result_to_inbox(
            job_name,
            response=response,
            kwargs={},
        )

    assert emitted is expected
    assert append_event.await_count == int(expected)
