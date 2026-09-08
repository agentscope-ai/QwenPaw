# -*- coding: utf-8 -*-
"""Tests for ADBPG memory manager behavior."""

# pylint: disable=protected-access

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from plugins.memory.adbpg.backend.config import ADBPGMemoryConfig
from plugins.memory.adbpg.backend.manager import ADBPGMemoryManager
from qwenpaw.memory import MemoryBackendContext
from qwenpaw.constant import AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY


def _manager(
    tmp_path,
    agent_id: str = "agent-1",
    config: ADBPGMemoryConfig | None = None,
) -> ADBPGMemoryManager:
    return ADBPGMemoryManager(
        MemoryBackendContext(
            agent_id=agent_id,
            working_dir=tmp_path,
            host_working_dir=tmp_path,
            backend_config=(config or ADBPGMemoryConfig()).model_dump(),
        ),
    )


def _user_msg(text: str) -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


@pytest.mark.asyncio
async def test_adbpg_auto_memory_search_injects_tool_messages(tmp_path):
    manager = _manager(
        tmp_path,
        config=ADBPGMemoryConfig(
            auto_memory_search_config={"enabled": True, "max_results": 2},
        ),
    )
    manager._client = object()
    manager.memory_search = AsyncMock(
        return_value=ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text="[1] (adbpg, score: 0.88)\n喜欢猫",
                ),
            ],
        ),
    )

    result = await manager.auto_memory_search(
        [_user_msg("我喜欢什么动物")],
        agent_name="Agent One",
    )

    assert result is not None
    assert result["query"] == "我喜欢什么动物"
    assert result["text"] == "[1] (adbpg, score: 0.88)\n喜欢猫"
    assert len(result["msg"]) == 2

    memory_msg = result["msg"][1]
    assert memory_msg.role == "assistant"
    assert memory_msg.name == "memory_search"
    assert memory_msg.id
    assert memory_msg.created_at
    assert memory_msg.metadata[AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY] == [
        block.id for block in memory_msg.content
    ]
    assert memory_msg.content[2].name == "memory_search"
    assert '"max_results": 2' in memory_msg.content[2].input
    assert memory_msg.content[3].name == "memory_search"
    assert memory_msg.content[3].output[0].text.endswith("喜欢猫")
    manager.memory_search.assert_awaited_once_with(
        query="我喜欢什么动物",
        max_results=2,
    )


@pytest.mark.asyncio
async def test_adbpg_auto_memory_search_respects_disabled_config(tmp_path):
    manager = _manager(
        tmp_path,
        config=ADBPGMemoryConfig(
            auto_memory_search_config={"enabled": False},
        ),
    )
    manager._client = object()
    manager.memory_search = AsyncMock()

    result = await manager.auto_memory_search([_user_msg("hello")])

    assert result is None
    manager.memory_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_adbpg_auto_memory_waits_for_backend_processing(tmp_path):
    manager = _manager(tmp_path)
    client = SimpleNamespace(add_memory=AsyncMock())
    manager._client = client
    message = _user_msg("remember this")

    result = await manager.auto_memory([message])

    assert (
        result == "Processed 1 user message(s) to ADBPG for agent 'agent-1'."
    )
    client.add_memory.assert_awaited_once()
    assert message.id in manager._persisted_msg_ids


@pytest.mark.asyncio
async def test_adbpg_auto_memory_tracks_each_success_before_later_failure(
    tmp_path,
):
    manager = _manager(tmp_path)
    client = SimpleNamespace(
        add_memory=AsyncMock(
            side_effect=[None, RuntimeError("second write failed")],
        ),
    )
    manager._client = client
    first = _user_msg("first")
    second = _user_msg("second")

    with pytest.raises(RuntimeError, match="second write failed"):
        await manager.auto_memory([first, second])

    assert first.id in manager._persisted_msg_ids
    assert second.id not in manager._persisted_msg_ids


async def _rest_manager(tmp_path, handler, **config):
    manager = _manager(
        tmp_path,
        config=ADBPGMemoryConfig(
            rest_base_url="https://memory.example.test",
            rest_api_key="test-key",
            **config,
        ),
    )
    await manager.start()
    await manager._client._http_client.aclose()
    manager._client._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    )
    return manager


@pytest.mark.asyncio
async def test_rejected_write_marks_worker_failed_and_allows_retry(tmp_path):
    statuses = iter([503, 202])
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(next(statuses), json={"results": []})

    manager = await _rest_manager(tmp_path, handler)
    message = _user_msg("remember this after the service recovers")
    try:
        manager.submit_auto_memory([message])
        await asyncio.wait_for(manager._auto_memory_task_queue.join(), 1)

        first_task = manager.list_auto_memory_tasks()[0]
        assert first_task["status"] == "failed"
        assert "503" in first_task["error"]
        assert message.id not in manager._persisted_msg_ids

        manager.submit_auto_memory([message])
        await asyncio.wait_for(manager._auto_memory_task_queue.join(), 1)

        assert manager.list_auto_memory_tasks()[1]["status"] == "completed"
        assert message.id in manager._persisted_msg_ids
        assert len(requests) == 2
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_partial_rest_failure_retries_only_unaccepted_messages(tmp_path):
    statuses = iter([202, 503, 202])
    contents = []

    def handler(request):
        contents.append(json.loads(request.content)["messages"][0]["content"])
        return httpx.Response(next(statuses), json={"results": []})

    manager = await _rest_manager(tmp_path, handler)
    first, second = _user_msg("first fact"), _user_msg("second fact")
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await manager.auto_memory([first, second])

        assert first.id in manager._persisted_msg_ids
        assert second.id not in manager._persisted_msg_ids
        await manager.auto_memory([first, second])
        assert contents == ["first fact", "second fact", "second fact"]
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("isolation", [True, False])
async def test_manager_uses_same_agent_namespace_for_add_and_search(
    tmp_path,
    isolation,
):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    manager = await _rest_manager(
        tmp_path,
        handler,
        memory_isolation=isolation,
    )
    try:
        await manager.auto_memory([_user_msg("I like cats")])
        await manager.memory_search("cats")
    finally:
        await manager.close()

    expected_agent = "agent-1" if isolation else "shared"
    assert bodies[0]["agent_id"] == expected_agent
    assert bodies[1]["filters"] == {
        "agent_id": expected_agent,
        "user_id": bodies[0]["user_id"],
    }


@pytest.mark.asyncio
async def test_remote_failure_still_recalls_local_memory(tmp_path):
    (tmp_path / "MEMORY.md").write_text("I like cats", encoding="utf-8")
    manager = await _rest_manager(
        tmp_path,
        lambda request: httpx.Response(503, json={"detail": "offline"}),
    )
    try:
        result = await manager.auto_memory_search([_user_msg("cats")])
        assert result is not None
        assert "file: MEMORY.md" in result["text"]
        assert "I like cats" in result["text"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_close_drains_writes_before_closing_http_client(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        started.set()
        await release.wait()
        return httpx.Response(202, json={"results": []})

    manager = await _rest_manager(tmp_path, handler)
    client = manager._client
    manager.submit_auto_memory([_user_msg("first fact")])
    manager.submit_auto_memory([_user_msg("second fact")])
    closing = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        closing = asyncio.create_task(manager.close())
        await asyncio.sleep(0)
        assert not client._http_client.is_closed
        release.set()
        assert await asyncio.wait_for(closing, 1) is True
        assert client._http_client.is_closed
        assert [
            task["status"] for task in manager.list_auto_memory_tasks()
        ] == [
            "completed",
            "completed",
        ]
    finally:
        release.set()
        if closing is not None:
            await closing
        else:
            await manager.close()
