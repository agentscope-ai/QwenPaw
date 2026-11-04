# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Opt-in acceptance against a disposable PowerContext HTTP server.

Set ``POWERCONTEXT_TEST_URL`` to an isolated, unauthenticated test server.
These tests create durable Scopes and memories; discard that server's database
afterward. They never connect to a configured QwenPaw or PowerContext service.
Both the legacy Memory and current Atomic Memory response contracts are valid.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
import pytest
from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from plugins.memory.powercontext.backend.config import PowerContextMemoryConfig
from plugins.memory.powercontext.backend.manager import (
    PowerContextMemoryManager,
)
from plugins.memory.powercontext.backend.prompts import (
    POWERCONTEXT_UNTRUSTED_HISTORY_NOTICE,
)
from qwenpaw.memory import MemoryBackendContext, NO_RELEVANT_MEMORIES

pytestmark = pytest.mark.integration


@pytest.fixture(name="server")
async def disposable_server() -> AsyncIterator[httpx.AsyncClient]:
    """Require an explicit opt-in URL instead of using any user's settings."""
    base_url = os.environ.get("POWERCONTEXT_TEST_URL", "").strip()
    if not base_url:
        pytest.skip("POWERCONTEXT_TEST_URL must point to a disposable server")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or any(
            (
                parsed.username is not None,
                parsed.password is not None,
                parsed.query,
                parsed.fragment,
            ),
        )
    ):
        pytest.fail("POWERCONTEXT_TEST_URL must be an HTTP server URL")
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=10,
        trust_env=False,
    ) as client:
        response = await client.get("/health/live")
        response.raise_for_status()
        yield client


def _message(role: str, text: str) -> Msg:
    return Msg(
        name=role,
        role=role,
        content=[TextBlock(type="text", text=text)],
    )


def _text(result: ToolChunk) -> str:
    return "\n".join(
        str(getattr(block, "text", "")) for block in result.content or []
    )


@asynccontextmanager
async def _running_manager(
    server: httpx.AsyncClient,
    host_root: Path,
    *,
    agent_id: str = "default",
    scope_id: str = "",
    recall_mode: str | None = None,
) -> AsyncIterator[PowerContextMemoryManager]:
    host_root.mkdir(parents=True, exist_ok=True)
    workspace = host_root / "workspaces" / agent_id
    workspace.mkdir(parents=True, exist_ok=True)
    manager = PowerContextMemoryManager(
        MemoryBackendContext(
            agent_id=agent_id,
            working_dir=workspace,
            host_working_dir=host_root,
            backend_config=PowerContextMemoryConfig(
                base_url=str(server.base_url).rstrip("/"),
                scope_id=scope_id,
                auto_memory_search_config={
                    "mode": recall_mode
                    or os.environ.get(
                        "POWERCONTEXT_TEST_RECALL_MODE",
                        "prepare",
                    ),
                },
            ).model_dump(),
        ),
    )
    try:
        await manager.start()
        yield manager
    finally:
        assert (
            await manager.close()
        ), "The real HTTP backend must close cleanly"


async def _scope_ids(server: httpx.AsyncClient) -> set[str]:
    response = await server.get("/v1/scopes")
    response.raise_for_status()
    return {item["scope_id"] for item in response.json()["items"]}


async def _wire_hits(
    server: httpx.AsyncClient,
    scope_id: str,
    query: str,
) -> list[dict]:
    response = await server.post(
        "/v1/memory/search",
        json={"scope_id": scope_id, "query": query, "limit": 5},
    )
    response.raise_for_status()
    return response.json()["hits"]


def _assert_exact_citation(rendered: str, hit: dict, scope_id: str) -> None:
    """Compare manager output with actual server evidence, in either format."""
    if "memory" in hit:
        record = hit["memory"]
        reference = record["artifact"]
        assert f"state_version: {record['state_version']}" in rendered
        assert "entry_id:" not in rendered
        assert "entry_version_id:" not in rendered
        assert record["text"] in rendered
    else:
        citation = hit["citation"]
        reference = citation["memory_ref"]
        assert f"entry_id: {citation['entry_id']}" in rendered
        assert f"entry_version_id: {citation['entry_version_id']}" in rendered
        assert hit["text"] in rendered
    assert f"family: {reference['family']}" in rendered
    assert f"artifact_id: {reference['artifact_id']}" in rendered
    assert f"revision: {reference['revision']}" in rendered
    assert f"scope: {scope_id}" in rendered


@pytest.mark.asyncio
async def test_default_scope_and_explicit_memory_roundtrip(server, tmp_path):
    marker = "roundtrip" + uuid.uuid4().hex
    async with _running_manager(server, tmp_path / "host") as manager:
        assert {"memory_search", "memory_remember"} <= {
            tool.__name__ for tool in manager.list_memory_tools()
        }
        # Inspect the resolved identity only to address the real server below;
        # assertions concern persisted registration and public tool results.
        scope_id = manager._scope_id()
        response = await server.get(
            f"/v1/scopes/{quote(scope_id, safe='')}",
        )
        response.raise_for_status()
        assert response.json()["scope_id"] == scope_id

        saved = await manager.memory_remember(
            "preference",
            f"{marker} remembers the selected blue notebook.",
        )
        assert saved.state == ToolResultState.SUCCESS, _text(saved)
        result = await manager.memory_search(marker)
        assert result.state == ToolResultState.SUCCESS, _text(result)
        rendered = _text(result)
        assert marker in rendered
        assert POWERCONTEXT_UNTRUSTED_HISTORY_NOTICE in rendered

        hits = await _wire_hits(server, scope_id, marker)
        assert len(hits) == 1
        _assert_exact_citation(rendered, hits[0], scope_id)


@pytest.mark.asyncio
async def test_queued_auto_memory_drains_and_reopens_with_recall(
    server,
    tmp_path,
):
    host_root = tmp_path / "host"
    first_marker = "queuedfirst" + uuid.uuid4().hex
    second_marker = "queuedsecond" + uuid.uuid4().hex
    async with _running_manager(server, host_root) as manager:
        assert manager.list_memory_tools()
        scope_id = manager._scope_id()
        task_ids = {
            manager.submit_auto_memory(
                [
                    _message(
                        "user",
                        f"Remember {first_marker} for the next visit.",
                    ),
                    _message("assistant", "The selected notebook is blue."),
                ],
            ),
            manager.submit_auto_memory(
                [
                    _message(
                        "user",
                        f"Remember {second_marker} as the delivery code.",
                    ),
                    _message(
                        "assistant",
                        "The delivery must arrive on Tuesday.",
                    ),
                ],
            ),
        }
        # Leave immediately: close must drain both real HTTP writes.
    tasks = {
        task["task_id"]: task for task in manager.list_auto_memory_tasks()
    }
    assert set(tasks) == task_ids
    assert all(task["status"] == "completed" for task in tasks.values()), tasks
    scopes_before_reopen = await _scope_ids(server)

    async with _running_manager(server, host_root) as reopened:
        assert reopened.list_memory_tools()
        reopened_scope = reopened._scope_id()
        assert reopened_scope == scope_id
        assert await _scope_ids(server) == scopes_before_reopen
        for marker in (first_marker, second_marker):
            recalled = await reopened.memory_search(marker)
            assert recalled.state == ToolResultState.SUCCESS, _text(recalled)
            assert marker in _text(recalled)
            assert len(await _wire_hits(server, scope_id, marker)) == 1

        incoming = _message("user", first_marker)
        injected = await reopened.auto_memory_search([incoming])
        assert injected is not None
        assert injected["query"] == first_marker
        assert first_marker in injected["text"]
        assert "untrusted" in injected["text"].lower()
        assert injected["msg"][0] is incoming
        assert len(injected["msg"]) == 2
        assert first_marker in str(injected["msg"][-1].content)


@pytest.mark.asyncio
async def test_agents_and_installations_keep_separate_memories(
    server,
    tmp_path,
):
    marker = "isolated" + uuid.uuid4().hex
    async with _running_manager(server, tmp_path / "host-a") as owner:
        saved = await owner.memory_remember("preference", marker)
        assert saved.state == ToolResultState.SUCCESS, _text(saved)
        owner_scope = owner._scope_id()

        async with _running_manager(
            server,
            tmp_path / "host-a",
            agent_id="other-agent",
        ) as other_agent:
            async with _running_manager(
                server,
                tmp_path / "host-b",
            ) as other_installation:
                scope_ids = {
                    manager._scope_id()
                    for manager in (owner, other_agent, other_installation)
                }
                assert len(scope_ids) == 3
                for manager in (other_agent, other_installation):
                    assert manager.list_memory_tools()
                    result = await manager.memory_search(marker)
                    assert result.state == ToolResultState.SUCCESS, _text(
                        result,
                    )
                    assert _text(result) == NO_RELEVANT_MEMORIES
                    assert (
                        await manager.auto_memory_search(
                            [
                                _message("user", marker),
                            ],
                        )
                        is None
                    )
        assert len(await _wire_hits(server, owner_scope, marker)) == 1


@pytest.mark.asyncio
async def test_explicit_scope_reuses_identity_and_missing_scope_stays_disabled(
    server,
    tmp_path,
):
    response = await server.post(
        "/v1/scopes",
        json={
            "title": "Explicit adapter acceptance scope",
            "summary": "Disposable scope for explicit binding acceptance.",
            "idempotency_key": "adapter-acceptance:" + uuid.uuid4().hex,
        },
    )
    response.raise_for_status()
    explicit_id = response.json()["scope_id"]
    scopes_before_start = await _scope_ids(server)
    marker = "explicit" + uuid.uuid4().hex
    async with _running_manager(
        server,
        tmp_path / "host",
        scope_id=explicit_id,
    ) as manager:
        assert manager.list_memory_tools()
        bound_scope = manager._scope_id()
        assert bound_scope == explicit_id
        saved = await manager.memory_remember("preference", marker)
        assert saved.state == ToolResultState.SUCCESS, _text(saved)
        found = await manager.memory_search(marker)
        assert found.state == ToolResultState.SUCCESS, _text(found)
        assert marker in _text(found)
        assert await _scope_ids(server) == scopes_before_start

    missing_id = "missing-acceptance-" + uuid.uuid4().hex
    async with _running_manager(
        server,
        tmp_path / "missing-host",
        scope_id=missing_id,
    ) as unavailable:
        assert unavailable.list_memory_tools() == []
        assert unavailable.get_memory_prompt() == ""
        assert unavailable.get_auto_memory_interval() == 0
        result = await unavailable.memory_remember("preference", marker)
        assert result.state == ToolResultState.ERROR
        assert await _scope_ids(server) == scopes_before_start
