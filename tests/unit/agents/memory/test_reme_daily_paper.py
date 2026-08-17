# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Focused tests for the embedded ReMe Daily Paper entry point."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


@pytest.mark.asyncio
async def test_daily_paper_runs_with_qwenpaw_model_and_defaults() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._run_reme_job = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="done"),
    )
    manager.get_memory_config = lambda: SimpleNamespace(
        daily_paper_use_hf_mirror=False,
        daily_paper_topics="",
    )

    await manager.daily_paper()

    manager._run_reme_job.assert_awaited_once_with(
        "daily_paper",
        needs_llm=True,
        raise_on_error=True,
        date="",
        force=False,
        use_hf_mirror=False,
        topics="",
    )


@pytest.mark.asyncio
async def test_daily_paper_passes_configured_source_preferences() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._run_reme_job = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="done"),
    )
    manager.get_memory_config = lambda: SimpleNamespace(
        daily_paper_use_hf_mirror=True,
        daily_paper_topics="agent memory",
    )

    await manager.daily_paper()

    manager._run_reme_job.assert_awaited_once_with(
        "daily_paper",
        needs_llm=True,
        raise_on_error=True,
        date="",
        force=False,
        use_hf_mirror=True,
        topics="agent memory",
    )


@pytest.mark.asyncio
async def test_daily_paper_fails_when_reme_is_unavailable() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._run_reme_job = AsyncMock(return_value=None)
    manager.get_memory_config = lambda: SimpleNamespace(
        daily_paper_use_hf_mirror=False,
        daily_paper_topics="",
    )

    with pytest.raises(RuntimeError, match="ReMe is not started"):
        await manager.daily_paper()


@pytest.mark.asyncio
async def test_daily_paper_reports_the_real_execution_failure() -> None:
    """An unreachable source must not be reported as "ReMe is not started"."""
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._reme = SimpleNamespace(
        is_started=True,
        run_job=AsyncMock(side_effect=ConnectionError("mirror unreachable")),
    )
    manager._lifecycle_condition = asyncio.Condition()
    manager._lifecycle_operation = None
    manager._active_reme_jobs = 0
    manager._update_qwenpaw_model = AsyncMock()
    manager.get_memory_config = lambda: SimpleNamespace(
        daily_paper_use_hf_mirror=True,
        daily_paper_topics="",
    )

    with pytest.raises(ConnectionError, match="mirror unreachable"):
        await manager.daily_paper()


@pytest.mark.asyncio
async def test_daily_paper_result_is_delivered_to_inbox() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    manager.get_memory_config = lambda: SimpleNamespace(
        daily_paper_inbox_push_enabled=True,
    )
    response = SimpleNamespace(
        success=True,
        answer="Generated daily paper brief",
        metadata={
            "digest_path": "memory/2026-08-08/每日论文简报.md",
            "selected_arxiv_ids": ["2608.00001"],
        },
    )

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager."
        "append_inbox_event",
        new_callable=AsyncMock,
        return_value={"id": "event-1"},
    ) as append_event:
        emitted = await manager._append_reme_job_result_to_inbox(
            "daily_paper",
            response=response,
            kwargs={"date": "2026-08-08", "force": False},
        )

    assert emitted is True
    call_kwargs = append_event.await_args.kwargs
    assert call_kwargs["source_id"] == "daily_paper"
    assert call_kwargs["title"] == "Daily Paper result"
    assert call_kwargs["payload"]["digest_path"].endswith("每日论文简报.md")
    assert call_kwargs["payload"]["selected_arxiv_ids"] == ["2608.00001"]


def test_memory_search_tool_exposure_has_an_independent_switch() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.get_memory_config = lambda: SimpleNamespace(
        memory_search_enabled=False,
    )

    assert not manager.list_memory_tools()

    manager.get_memory_config = lambda: SimpleNamespace(
        memory_search_enabled=True,
    )
    assert manager.list_memory_tools() == [manager.memory_search]


def test_memory_prompt_omits_disabled_search_tool() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    agent_config = SimpleNamespace(
        language="en",
        running=SimpleNamespace(
            reme_light_memory_config=SimpleNamespace(
                memory_search_enabled=False,
            ),
        ),
    )

    config_loader = (
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config"
    )
    with patch(
        config_loader,
        return_value=agent_config,
    ):
        prompt = manager.get_memory_prompt()

    assert "memory_search" not in prompt
    assert prompt == ""


def test_memory_prompt_includes_enabled_search_tool() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    agent_config = SimpleNamespace(
        language="en",
        running=SimpleNamespace(
            reme_light_memory_config=SimpleNamespace(
                memory_search_enabled=True,
            ),
        ),
    )

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=agent_config,
    ):
        prompt = manager.get_memory_prompt()

    assert "memory_search" in prompt
    assert "personal knowledge base" in prompt


def test_reme_declares_its_enabled_cron_jobs() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._reme = SimpleNamespace(is_started=True)
    manager.get_memory_config = lambda: SimpleNamespace(
        dream_cron_enabled=True,
        dream_cron="0 23 * * *",
        daily_paper_cron_enabled=True,
        daily_paper_cron="0 9 * * *",
    )

    jobs = manager.list_cron_jobs()

    assert [job.key for job in jobs] == ["dream", "daily-paper"]
    assert jobs[0].callback.__self__ is manager
    assert jobs[0].callback.__func__ is ReMeLightMemoryManager.dream
    assert jobs[0].jitter_seconds == 60
    assert jobs[1].callback.__self__ is manager
    assert jobs[1].callback.__func__ is ReMeLightMemoryManager.daily_paper


@pytest.mark.asyncio
async def test_automatic_search_works_when_agent_tool_is_hidden() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    manager._build_query = lambda _messages: "project decision"
    manager._build_auto_memory_search_msg = lambda **_kwargs: "search-msg"
    manager._run_reme_job = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="remembered"),
    )
    memory_config = SimpleNamespace(
        memory_search_enabled=False,
        auto_memory_search_config=SimpleNamespace(
            enabled=True,
            max_results=2,
        ),
    )
    agent_config = SimpleNamespace(
        running=SimpleNamespace(reme_light_memory_config=memory_config),
    )
    manager.get_memory_config = lambda: memory_config

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager."
        "load_agent_config_async",
        AsyncMock(return_value=agent_config),
    ):
        result = await manager.auto_memory_search([object()])

    assert not manager.list_memory_tools()
    assert result is not None
    manager._run_reme_job.assert_awaited_once_with(
        "search",
        query="project decision",
        limit=2,
        min_score=0,
    )
