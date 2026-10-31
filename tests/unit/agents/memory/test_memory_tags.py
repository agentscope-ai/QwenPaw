# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tag discovery, optional filters, and prompts follow host configuration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.prompts import build_memory_guidance_prompt
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.config.config import ReMeLightMemoryConfig


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("search_enabled", [False, True])
def test_tools_and_prompts_follow_tag_and_search_switches(
    enabled,
    search_enabled,
):
    config = ReMeLightMemoryConfig(
        memory_search_enabled=search_enabled,
        auto_memory_generate_tags=enabled,
    )
    manager = object.__new__(ReMeLightMemoryManager)
    manager._load_memory_config = lambda: config
    tools = {tool.__name__ for tool in manager.list_memory_tools()}
    assert ("memory_search" in tools) is search_enabled
    assert ("memory_list_tags" in tools) is (enabled and search_enabled)
    for language in ("zh", "en"):
        prompt = build_memory_guidance_prompt(
            language,
            memory_search_enabled=search_enabled,
            memory_tags_enabled=enabled,
        )
        assert ("memory_list_tags" in prompt) is (enabled and search_enabled)


@pytest.mark.asyncio
@pytest.mark.parametrize("tags", [None, [], ["赵六", "Orion"]])
async def test_search_tags_are_optional_and_forwarded_before_reranking(tags):
    manager = object.__new__(ReMeLightMemoryManager)
    manager._get_reranker_config = AsyncMock(return_value=None)
    manager._rerank_and_cap_response = AsyncMock()
    manager._run_reme_job = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="found"),
    )
    await manager.memory_search("Orion", tags=tags)
    forwarded = manager._run_reme_job.await_args.kwargs
    if tags is None:
        assert "tags" not in forwarded
    else:
        assert forwarded["tags"] == tags


@pytest.mark.asyncio
async def test_tag_tool_uses_read_only_paginated_action():
    manager = object.__new__(ReMeLightMemoryManager)
    manager.run_action = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            answer={"items": [["赵六", 2]]},
        ),
    )
    response = await manager.memory_list_tags(page=2, page_size=10)
    manager.run_action.assert_awaited_once_with(
        "list_tags",
        page=2,
        page_size=10,
    )
    assert "赵六" in response.content[0].text
