# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Inbox notification policy for ReMe memory jobs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.agents.memory.reme_inbox import build_payload, emit_job_result


def _manager() -> ReMeLightMemoryManager:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    manager._load_memory_config = lambda: SimpleNamespace(
        auto_memory_inbox_push_enabled=True,
        auto_dream_inbox_push_enabled=True,
        auto_fin_inbox_push_enabled=True,
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
            "auto_fin",
            SimpleNamespace(
                success=True,
                answer="No related CLS news",
                metadata={"skipped": True},
            ),
            False,
        ),
        (
            "auto_fin",
            SimpleNamespace(
                success=True,
                answer="Financial research generated",
                metadata={"digest_path": "memory/2026-08-31/auto_fin.md"},
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("success", "expected_status", "expected_body"),
    [
        (
            True,
            "success",
            "Daily Paper completed with no returned content.",
        ),
        (
            False,
            "error",
            (
                "Daily Paper failed with no returned error details. "
                "Check the application logs for more information."
            ),
        ),
    ],
)
async def test_empty_result_body_matches_job_status(
    success,
    expected_status,
    expected_body,
) -> None:
    append_event = AsyncMock(return_value={"id": "event-1"})

    emitted = await emit_job_result(
        agent_id="agent-1",
        memory_config=SimpleNamespace(
            daily_paper_inbox_push_enabled=True,
        ),
        name="daily_paper",
        response=SimpleNamespace(
            success=success,
            answer="",
            metadata={},
        ),
        kwargs={},
        append_event=append_event,
    )

    assert emitted is True
    assert append_event.await_args.kwargs["status"] == expected_status
    assert append_event.await_args.kwargs["body"] == expected_body


def test_auto_fin_payload_separates_requested_and_effective_topics() -> None:
    payload = build_payload(
        "auto_fin",
        {
            "date": "",
            "topics": "黄金, 机器人，黄金",
            "window_hours": 12,
        },
        {
            "date": "2026-08-31",
            "topics": ["黄金", "机器人"],
            "window_hours": 24,
            "digest_path": "memory/2026-08-31/auto_fin.md",
            "selected_news_count": 2,
            "relevant_news_count": 2,
        },
    )

    assert payload["date"] == "2026-08-31"
    assert payload["topics"] == "黄金, 机器人，黄金"
    assert payload["effective_topics"] == ["黄金", "机器人"]
    assert payload["window_hours"] == 12
    assert payload["digest_path"] == "memory/2026-08-31/auto_fin.md"
    assert payload["selected_news_count"] == 2
    assert payload["relevant_news_count"] == 2


def test_auto_fin_payload_preserves_an_explicit_request_date() -> None:
    payload = build_payload(
        "auto_fin",
        {"date": "2026-08-30", "topics": "黄金", "window_hours": 24},
        {"date": "2026-08-31", "topics": ["黄金"]},
    )

    assert payload["date"] == "2026-08-30"
