# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Inbox notification policy for ReMe memory jobs."""

import asyncio
from contextlib import asynccontextmanager
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


def _action_manager() -> ReMeLightMemoryManager:
    manager = _manager()
    manager._llm_job_lock = asyncio.Lock()
    manager._reme = SimpleNamespace(
        is_started=True,
        context=SimpleNamespace(
            jobs={
                "auto_dream": SimpleNamespace(
                    enable_serve=True,
                    parameters={
                        "type": "object",
                        "properties": {"date": {"type": "string"}},
                    },
                ),
            },
        ),
        run_job=AsyncMock(),
    )

    @asynccontextmanager
    async def lease():
        yield

    manager._reme_job_lease = lease
    manager._update_qwenpaw_model = AsyncMock()
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("success", "modified", "notifications_enabled"),
    [
        (True, True, True),
        (True, False, True),
        (True, True, False),
        (False, False, True),
    ],
)
async def test_auto_dream_preserves_notification_policy(
    success,
    modified,
    notifications_enabled,
) -> None:
    """Preserve notification policy for a single digest job."""
    manager = _action_manager()
    manager._load_memory_config = lambda: SimpleNamespace(
        auto_dream_inbox_push_enabled=notifications_enabled,
    )
    response = SimpleNamespace(
        success=success,
        answer="digest result",
        metadata={"modified": modified},
    )
    manager._reme.run_job.return_value = response
    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        new_callable=AsyncMock,
        return_value={"id": "event-1"},
    ) as append_event:
        assert (
            await manager.run_action("auto_dream", date="2026-10-23")
            is response
        )

    manager._reme.run_job.assert_awaited_once_with(
        "auto_dream",
        date="2026-10-23",
    )
    manager._update_qwenpaw_model.assert_awaited_once()
    expected = notifications_enabled and (modified or not success)
    assert append_event.await_count == int(expected)
    if expected:
        event = append_event.await_args.kwargs
        assert event["source_id"] == "auto_dream"
        assert event["status"] == ("success" if success else "error")
        assert event["body"] == "digest result"
        assert event["payload"]["date"] == "2026-10-23"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [RuntimeError("dream failed"), asyncio.CancelledError()],
)
async def test_auto_dream_errors_propagate_without_success_notification(error):
    manager = _action_manager()
    manager._reme.run_job.side_effect = error
    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        new_callable=AsyncMock,
    ) as append_event:
        with pytest.raises(type(error)):
            await manager.run_action("auto_dream")
    manager._reme.run_job.assert_awaited_once_with("auto_dream")
    append_event.assert_not_awaited()


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_name", "success"),
    [
        ("auto_memory", True),
        ("auto_memory", False),
        ("daily_paper", True),
        ("auto_fin", True),
    ],
)
async def test_tag_failures_are_reported_without_losing_job_outcome(
    job_name,
    success,
):
    """Warnings retain the main outcome and expose counts for every tag job."""
    manager = _action_manager()
    manager._load_memory_config = lambda: SimpleNamespace(
        auto_memory_inbox_push_enabled=True,
        daily_paper_inbox_push_enabled=True,
        auto_fin_inbox_push_enabled=True,
    )
    counts = {"processed": 2, "succeeded": 1, "failed": 1}
    response = SimpleNamespace(
        success=success,
        answer="Saved memory" if success else "Job failed",
        metadata={
            "modified": False,
            "auto_tag": {
                **counts,
                "results": [{"path": "memory/note.md", "error": "no tags"}],
            },
        },
    )
    manager._reme.run_job.return_value = response
    manager._prepare_auto_memory_job = AsyncMock(
        return_value="auto_memory_with_tags",
    )
    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        new_callable=AsyncMock,
        return_value={"id": "tag-warning"},
    ) as append_event:
        result = await manager._run_reme_job_unlocked(
            job_name,
            needs_llm=True,
        )
        event = append_event.await_args.kwargs
        # Emitting again must not duplicate the notification or its warning.
        assert not await manager._append_reme_job_result_to_inbox(
            job_name,
            response=response,
            kwargs={},
        )

    assert result is response
    assert response.success is success
    assert response.answer.count("auto-tagging failed for 1 file(s)") == 1
    assert event["body"] == response.answer
    assert event["status"] == ("success" if success else "error")
    assert event["severity"] == ("warning" if success else "error")
    assert event["payload"]["auto_tag"] == counts
    append_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_tag_warning_remains_in_result_when_notifications_are_disabled():
    """Returned results show tag failure even with notifications disabled."""
    manager = _action_manager()
    manager._load_memory_config = lambda: SimpleNamespace(
        auto_dream_inbox_push_enabled=False,
    )
    response = SimpleNamespace(
        success=True,
        answer="Saved memory",
        metadata={"auto_tag": {"failed": 2}},
    )
    manager._reme.run_job.return_value = response
    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        new_callable=AsyncMock,
    ) as append_event:
        assert await manager.run_action("auto_dream") is response

    assert response.success is True
    assert "auto-tagging failed for 2 file(s)" in response.answer
    assert "Saved memory" in response.answer
    append_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_tag_warning_survives_inbox_body_truncation():
    """Long model output must not hide the partial-failure warning."""
    response = SimpleNamespace(
        success=True,
        answer="x" * 5000,
        metadata={"auto_tag": {"failed": 1}},
    )
    append_event = AsyncMock(return_value={"id": "tag-warning"})
    assert await emit_job_result(
        agent_id="agent-1",
        memory_config=SimpleNamespace(auto_fin_inbox_push_enabled=True),
        name="auto_fin",
        response=response,
        kwargs={},
        append_event=append_event,
    )
    assert (
        "auto-tagging failed for 1 file(s)"
        in append_event.await_args.kwargs["body"]
    )
