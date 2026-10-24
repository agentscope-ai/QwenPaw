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


# ---------------------------------------------------------------------------
# proactive agenda push
# ---------------------------------------------------------------------------


def _agenda_item(topic_id: str, kind: str = "follow_up"):
    from qwenpaw.agents.memory.proactive.proactive_agenda import AgendaItem

    return AgendaItem(
        topic_id=topic_id,
        title=f"title-{topic_id}",
        kind=kind,
        opener=f"opener-{topic_id}",
        next_action=f"next-{topic_id}",
        due_at="2026-10-12" if kind == "reminder" else "",
    )


def _proactive_config(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(proactive_inbox_push_enabled=enabled)


@pytest.mark.asyncio
async def test_proactive_is_not_a_generic_result_job() -> None:
    """A manual ``/reme proactive`` read must never advance the inbox."""
    from qwenpaw.agents.memory.reme_inbox import RESULT_JOB_NAMES

    assert "proactive" not in RESULT_JOB_NAMES
    assert "proactive_refresh" not in RESULT_JOB_NAMES
    assert "proactive_feedback" not in RESULT_JOB_NAMES


@pytest.mark.asyncio
async def test_proactive_push_honours_the_inbox_switch() -> None:
    from qwenpaw.agents.memory.reme_inbox import emit_proactive_agenda

    append_event = AsyncMock()

    event = await emit_proactive_agenda(
        agent_id="agent-1",
        memory_config=_proactive_config(enabled=False),
        date="2026-10-11",
        items=[_agenda_item("t-1")],
        append_event=append_event,
    )

    assert event is None
    append_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_proactive_push_skips_an_empty_agenda() -> None:
    from qwenpaw.agents.memory.reme_inbox import emit_proactive_agenda

    append_event = AsyncMock()

    event = await emit_proactive_agenda(
        agent_id="agent-1",
        memory_config=_proactive_config(),
        date="2026-10-11",
        items=[],
        append_event=append_event,
    )

    assert event is None
    append_event.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel", "language", "expected_title"),
    [
        ("cron", "en", "Today's proactive agenda (2)"),
        ("idle", "en", "Proactive agenda suggestions (2)"),
        ("cron", "zh", "今日主动议程 (2)"),
        ("idle", "zh", "主动议程建议 (2)"),
    ],
)
async def test_proactive_push_shapes_the_inbox_event(
    channel: str,
    language: str,
    expected_title: str,
) -> None:
    from qwenpaw.agents.memory.reme_inbox import emit_proactive_agenda

    append_event = AsyncMock(return_value={"id": "event-7"})
    items = [_agenda_item("t-1", kind="reminder"), _agenda_item("t-2")]

    event = await emit_proactive_agenda(
        agent_id="agent-1",
        memory_config=_proactive_config(),
        date="2026-10-11",
        items=items,
        append_event=append_event,
        channel=channel,
        language=language,
    )

    assert event == {"id": "event-7"}
    kwargs = append_event.await_args.kwargs
    assert kwargs["source_type"] == "memory"
    assert kwargs["source_id"] == "proactive"
    assert kwargs["event_type"] == "proactive_agenda_result"
    assert kwargs["status"] == "success"
    assert kwargs["severity"] == "info"
    assert kwargs["title"] == expected_title
    assert kwargs["payload"]["date"] == "2026-10-11"
    assert kwargs["payload"]["channel"] == channel
    assert kwargs["payload"]["count"] == 2
    assert [item["topic_id"] for item in kwargs["payload"]["agenda"]] == [
        "t-1",
        "t-2",
    ]
    # Reading-only body: the opener and the suggested next action, no
    # affordance that would imply the inbox can execute anything.
    assert "opener-t-1" in kwargs["body"]
    assert "next-t-2" in kwargs["body"]


@pytest.mark.asyncio
async def test_proactive_push_caps_a_huge_body() -> None:
    from qwenpaw.agents.memory import reme_inbox

    append_event = AsyncMock(return_value={"id": "event-8"})
    items = [_agenda_item(f"t-{index}") for index in range(400)]

    await reme_inbox.emit_proactive_agenda(
        agent_id="agent-1",
        memory_config=_proactive_config(),
        date="2026-10-11",
        items=items,
        append_event=append_event,
    )

    body = append_event.await_args.kwargs["body"]
    assert len(body) <= reme_inbox.MAX_BODY_CHARS + 8
    assert body.endswith("...")


@pytest.mark.asyncio
async def test_proactive_push_swallows_inbox_failures() -> None:
    from qwenpaw.agents.memory.reme_inbox import emit_proactive_agenda

    append_event = AsyncMock(side_effect=RuntimeError("inbox down"))

    event = await emit_proactive_agenda(
        agent_id="agent-1",
        memory_config=_proactive_config(),
        date="2026-10-11",
        items=[_agenda_item("t-1")],
        append_event=append_event,
    )

    assert event is None


@pytest.mark.asyncio
async def test_proactive_daily_job_raises_only_when_unavailable() -> None:
    """A silent empty agenda is a success; no answer from ReMe is not."""
    from qwenpaw.agents.memory.proactive.proactive_responder import (
        AgendaRound,
    )

    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    manager.working_dir = "/ws/agent-1"
    rounds = [
        AgendaRound(available=True, skip_reason="empty"),
        AgendaRound(available=False, skip_reason="unavailable"),
    ]

    async def fake_round(**kwargs):
        assert kwargs["channel"] == "cron"
        assert kwargs["force_refresh"] is True
        return rounds.pop(0)

    with patch(
        "qwenpaw.agents.memory.proactive.proactive_responder"
        ".deliver_proactive_round",
        side_effect=fake_round,
    ):
        await manager._run_proactive_daily()
        with pytest.raises(RuntimeError, match="unavailable"):
            await manager._run_proactive_daily()
