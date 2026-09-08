# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Focused tests for scheduled ReMe actions and memory guidance."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.prompts import build_memory_guidance_prompt
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


@pytest.mark.asyncio
async def test_daily_paper_runs_with_qwenpaw_model_and_defaults() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.run_action = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="done"),
    )
    manager._load_memory_config = lambda: SimpleNamespace(
        daily_paper_use_hf_mirror=False,
        daily_paper_topics="",
    )

    await manager._run_scheduled_action("daily_paper")

    manager.run_action.assert_awaited_once_with(
        "daily_paper",
        date="",
        force=False,
        use_hf_mirror=False,
        topics="",
    )


@pytest.mark.asyncio
async def test_daily_paper_passes_configured_source_preferences() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.run_action = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="done"),
    )
    manager._load_memory_config = lambda: SimpleNamespace(
        daily_paper_use_hf_mirror=True,
        daily_paper_topics="agent memory",
    )

    await manager._run_scheduled_action("daily_paper")

    manager.run_action.assert_awaited_once_with(
        "daily_paper",
        date="",
        force=False,
        use_hf_mirror=True,
        topics="agent memory",
    )


@pytest.mark.asyncio
async def test_auto_fin_passes_configured_topics_and_window() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.run_action = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="done"),
    )
    manager._load_memory_config = lambda: SimpleNamespace(
        auto_fin_topics="黄金,AI",
        auto_fin_window_hours=12,
    )

    await manager._run_scheduled_action("auto_fin")

    manager.run_action.assert_awaited_once_with(
        "auto_fin",
        date="",
        topics="黄金,AI",
        window_hours=12.0,
    )


@pytest.mark.asyncio
async def test_daily_paper_fails_when_reme_is_unavailable() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.run_action = AsyncMock(return_value=None)
    manager._load_memory_config = lambda: SimpleNamespace(
        daily_paper_use_hf_mirror=False,
        daily_paper_topics="",
    )

    with pytest.raises(RuntimeError, match="is unavailable"):
        await manager._run_scheduled_action("daily_paper")


@pytest.mark.asyncio
async def test_daily_paper_reports_the_real_execution_failure() -> None:
    """An execution failure must not be reported as action unavailability."""
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._reme = SimpleNamespace(
        is_started=True,
        run_job=AsyncMock(side_effect=ConnectionError("mirror unreachable")),
        context=SimpleNamespace(
            jobs={
                "daily_paper": SimpleNamespace(
                    enable_serve=True,
                    parameters={
                        "properties": {
                            "date": {"type": "string"},
                            "force": {"type": "boolean"},
                            "use_hf_mirror": {"type": "boolean"},
                            "topics": {"type": "string"},
                        },
                    },
                ),
            },
        ),
    )
    manager._lifecycle_condition = asyncio.Condition()
    manager._lifecycle_operation = None
    manager._active_reme_jobs = 0
    manager._update_qwenpaw_model = AsyncMock()
    manager._load_memory_config = lambda: SimpleNamespace(
        daily_paper_use_hf_mirror=True,
        daily_paper_topics="",
    )

    with pytest.raises(ConnectionError, match="mirror unreachable"):
        await manager._run_scheduled_action("daily_paper")


@pytest.mark.asyncio
async def test_daily_paper_result_is_delivered_to_inbox() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    manager._load_memory_config = lambda: SimpleNamespace(
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
    manager._load_memory_config = lambda: SimpleNamespace(
        memory_search_enabled=False,
    )

    assert not manager.list_memory_tools()

    manager._load_memory_config = lambda: SimpleNamespace(
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
    assert "`MEMORY.md` is your core long-term memory" in prompt
    assert "`memory/YYYY-MM-DD.md`" in prompt


def test_memory_prompt_includes_enabled_search_tool() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    agent_config = SimpleNamespace(
        language="en",
        running=SimpleNamespace(
            reme_light_memory_config=SimpleNamespace(
                memory_search_enabled=True,
                daily_dir="daily-notes",
                digest_dir="knowledge",
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
    assert "`MEMORY.md` is your core long-term memory" in prompt
    assert "`daily-notes` and `knowledge`" in prompt
    assert "`daily-notes/YYYY-MM-DD/{topic}.md`" in prompt
    assert "background asynchronous task" in prompt


def test_zh_memory_prompt_describes_the_four_memory_surfaces() -> None:
    prompt = build_memory_guidance_prompt(
        "zh",
        daily_dir="daily-notes",
        digest_dir="knowledge",
    )

    assert "`MEMORY.md` 是你的核心长期记忆" in prompt
    assert "`daily-notes/YYYY-MM-DD.md` 是你的日记本和每日笔记" in prompt
    assert "`daily-notes/YYYY-MM-DD/{topic}.md`" in prompt
    assert "`daily-notes` 和 `knowledge` 下的所有 Markdown 文件" in prompt
    assert "先使用 `memory_search`" in prompt
    assert "再使用 `read_file` 按路径渐进式展开" in prompt


def test_reme_declares_its_enabled_cron_jobs() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._reme = SimpleNamespace(is_started=True)
    manager._load_memory_config = lambda: SimpleNamespace(
        dream_cron_enabled=True,
        dream_cron="0 23 * * *",
        daily_paper_cron_enabled=True,
        daily_paper_cron="0 9 * * *",
        auto_fin_cron_enabled=True,
        auto_fin_cron="0 18 * * *",
    )

    jobs = manager.list_cron_jobs()

    assert [job.key for job in jobs] == ["dream", "daily-paper", "auto-fin"]
    assert jobs[0].callback.func.__self__ is manager
    assert jobs[0].callback.func.__func__ is (
        ReMeLightMemoryManager._run_scheduled_action
    )
    assert jobs[0].callback.args == ("auto_dream",)
    assert jobs[0].jitter_seconds == 60
    assert jobs[1].callback.args == ("daily_paper",)
    assert jobs[2].callback.args == ("auto_fin",)


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
    manager._load_memory_config = lambda: memory_config

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
