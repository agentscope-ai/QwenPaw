# -*- coding: utf-8 -*-
"""ADBPG 私有检索不得回退或混入旧 shared 数据。"""

from __future__ import annotations

import httpx
import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.memory.adbpg_client import ADBPGConfig, ADBPGMemoryClient
from qwenpaw.agents.memory.adbpg_memory_manager import ADBPGMemoryManager


@pytest.mark.asyncio
async def test_private_search_payload_excludes_legacy_shared_identity(
    tmp_path,
) -> None:
    """私有搜索若发送 shared/空过滤条件，模拟服务会泄露旧共享记录。"""
    requests: list[dict] = []
    records = [
        {
            "content": "legacy shared secret",
            "score": 0.99,
            "agent_id": "shared",
            "user_id": "shared",
        },
        {
            "content": "user-a private memory",
            "score": 0.90,
            "agent_id": "agent-a",
            "user_id": "user-a",
        },
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        requests.append(body)
        if request.url.path.endswith("/memories/add/"):
            return httpx.Response(200, json={"ok": True})
        filters = body.get("filters") or {}
        matched = [
            record
            for record in records
            if all(record.get(key) == value for key, value in filters.items())
        ]
        return httpx.Response(200, json={"results": matched})

    client = ADBPGMemoryClient(
        ADBPGConfig(
            rest_base_url="https://adbpg.test",
            rest_api_key="test-only-key",
        ),
    )
    await client._http_client.aclose()  # pylint: disable=protected-access
    client._http_client = httpx.AsyncClient(  # pylint: disable=protected-access
        transport=httpx.MockTransport(handler),
    )
    manager = ADBPGMemoryManager(str(tmp_path), "agent-a")
    manager._client = client  # pylint: disable=protected-access
    view = manager.for_request(
        {"user_id": "user-a", "agent_id": "agent-a", "run_id": "run-a"},
    )

    await view.auto_memory(
        [
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text="remember me")],
            ),
        ],
    )
    await __import__("asyncio").gather(
        *manager._pending_add_tasks,  # pylint: disable=protected-access
    )
    result = await view.memory_search("memory")
    text = manager._tool_chunk_text(result)  # pylint: disable=protected-access

    assert "user-a private memory" in text
    assert "legacy shared secret" not in text
    assert requests == [
        {
            "messages": [{"role": "user", "content": "remember me"}],
            "agent_id": "agent-a",
            "user_id": "user-a",
            "run_id": "run-a",
        },
        {
            "query": "memory",
            "filters": {"agent_id": "agent-a", "user_id": "user-a"},
            "run_id": "run-a",
            "top_k": 5,
        },
    ]
    await client.close()
