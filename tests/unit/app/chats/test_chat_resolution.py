# -*- coding: utf-8 -*-
"""Regression tests for ownership resolution of Console deep links."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app.chats import api as chat_api
from qwenpaw.app.chats.models import ChatSpec, ChatsFile
from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
from qwenpaw.config.config import AgentProfileRef


CHAT_A = f"11111111-1111-4111-8111-111111111111"
CHAT_B = f"22222222-2222-4222-8222-222222222222"


def _chat(chat_id, **updates):
    return ChatSpec(
        id=chat_id,
        session_id=updates.pop(f"session_id", f"console:{chat_id}"),
        user_id=f"user-{chat_id}",
        channel=f"console",
        **updates,
    )


@pytest.fixture(name=f"resolution_app")
def _resolution_app(tmp_path, monkeypatch):
    profiles = {}
    for agent_id in (f"a", f"b"):
        workspace = tmp_path / f"工作空间 {agent_id}"
        workspace.mkdir()
        profiles[agent_id] = AgentProfileRef(
            id=agent_id,
            workspace_dir=str(workspace),
        )
    config = SimpleNamespace(
        agents=SimpleNamespace(profiles=profiles, active_agent=f"a"),
    )
    monkeypatch.setattr(
        chat_api,
        f"load_config",
        lambda: config,
        raising=False,
    )
    app = FastAPI()
    app.include_router(chat_api.router, prefix=f"/api")
    app.state.multi_agent_manager = SimpleNamespace(
        get_agent=AsyncMock(side_effect=AssertionError(f"Workspace started")),
    )
    return app, config


async def _save(config, agent_id, chats):
    repository = JsonChatRepository(
        Path(config.agents.profiles[agent_id].workspace_dir) / f"chats.json",
    )
    await repository.save(ChatsFile(chats=chats))


async def _resolve(app, reference, agent_id=f"a"):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=f"http://test",
    ) as client:
        return await client.get(
            f"/api/chats/resolve",
            params={
                f"chat_id": reference,
                f"current_agent_id": agent_id,
            },
            headers={f"X-Agent-Id": agent_id},
        )


@pytest.mark.asyncio
async def test_cross_agent_link_resolves_without_starting_workspaces(
    resolution_app,
):
    app, config = resolution_app
    await _save(config, f"a", [_chat(CHAT_A)])
    target = _chat(CHAT_B, session_id=f"opaque-runtime")
    await _save(config, f"b", [target])

    response = await _resolve(app, CHAT_B)

    assert response.status_code == 200
    assert response.json() == {
        f"agent_id": f"b",
        f"chat": target.model_dump(mode=f"json"),
    }
    app.state.multi_agent_manager.get_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_agent_link_does_not_require_a_live_session_list(
    resolution_app,
):
    app, config = resolution_app
    await _save(config, f"a", [_chat(CHAT_A)])

    response = await _resolve(app, CHAT_A)

    assert response.status_code == 200
    assert response.json()[f"agent_id"] == f"a"
    app.state.multi_agent_manager.get_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_reference_is_not_a_fabricated_empty_chat(
    resolution_app,
):
    app, _ = resolution_app

    response = await _resolve(app, CHAT_B)

    assert response.status_code == 404
    assert f"Chat not found" in response.json()[f"detail"]


@pytest.mark.asyncio
async def test_duplicate_chat_ids_across_agents_are_ambiguous(resolution_app):
    app, config = resolution_app
    await _save(config, f"a", [_chat(CHAT_A)])
    await _save(config, f"b", [_chat(CHAT_A)])

    response = await _resolve(app, CHAT_A)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_runtime_alias_is_resolved_only_inside_the_current_agent(
    resolution_app,
):
    app, config = resolution_app
    await _save(config, f"a", [_chat(CHAT_A, session_id=f"shared-alias")])
    await _save(config, f"b", [_chat(CHAT_B, session_id=f"shared-alias")])

    response = await _resolve(app, f"shared-alias")

    assert response.status_code == 200
    assert response.json()[f"agent_id"] == f"a"
    assert response.json()[f"chat"][f"id"] == CHAT_A


@pytest.mark.asyncio
async def test_foreign_runtime_alias_is_not_globally_guessed(resolution_app):
    app, config = resolution_app
    await _save(config, f"b", [_chat(CHAT_B, session_id=f"foreign-alias")])

    response = await _resolve(app, f"foreign-alias")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_id_takes_priority_over_a_runtime_alias(resolution_app):
    app, config = resolution_app
    await _save(config, f"a", [_chat(CHAT_A, session_id=CHAT_B)])
    await _save(config, f"b", [_chat(CHAT_B)])

    response = await _resolve(app, CHAT_B)

    assert response.status_code == 200
    assert response.json()[f"agent_id"] == f"b"


@pytest.mark.asyncio
async def test_duplicate_runtime_aliases_in_one_agent_are_ambiguous(
    resolution_app,
):
    app, config = resolution_app
    await _save(
        config,
        f"a",
        [
            _chat(CHAT_A, session_id=f"shared-alias"),
            _chat(CHAT_B, session_id=f"shared-alias"),
        ],
    )

    response = await _resolve(app, f"shared-alias")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_archived_chat_resolves_without_modifying_its_catalog(
    resolution_app,
):
    app, config = resolution_app
    target = _chat(CHAT_B, archived_at=f"2026-10-01T00:00:00Z")
    await _save(config, f"b", [target])
    path = Path(config.agents.profiles[f"b"].workspace_dir) / f"chats.json"
    original = path.read_bytes()

    response = await _resolve(app, CHAT_B)

    assert response.status_code == 200
    assert response.json()[f"chat"][f"archived"] is True
    assert path.read_bytes() == original
    assert not (path.parent / f"agent.json").exists()


@pytest.mark.asyncio
async def test_disabled_agents_and_app_owned_chats_are_excluded(
    resolution_app,
):
    app, config = resolution_app
    config.agents.profiles[f"b"].enabled = False
    await _save(config, f"b", [_chat(CHAT_B)])
    await _save(
        config,
        f"a",
        [_chat(CHAT_A, meta={f"pawapp": {f"app_id": f"app"}})],
    )

    assert (await _resolve(app, CHAT_B)).status_code == 404
    assert (await _resolve(app, CHAT_A)).status_code == 404


@pytest.mark.asyncio
async def test_app_managed_agent_is_not_entered_through_console(
    resolution_app,
):
    app, config = resolution_app
    await _save(config, f"b", [_chat(CHAT_B)])
    profile_path = (
        Path(config.agents.profiles[f"b"].workspace_dir) / f"agent.json"
    )
    profile_path.write_text(
        json.dumps({f"template_id": f"pawapp:app"}),
        encoding=f"utf-8",
    )

    response = await _resolve(app, CHAT_B)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_catalog_reads_do_not_block_the_event_loop(
    resolution_app,
    monkeypatch,
):
    app, config = resolution_app
    await _save(config, f"b", [_chat(CHAT_B)])
    threads = []
    original = getattr(JsonChatRepository, f"_load_sync")

    def record_thread(repository):
        threads.append(threading.get_ident())
        return original(repository)

    monkeypatch.setattr(JsonChatRepository, f"_load_sync", record_thread)
    loop_thread = threading.get_ident()

    response = await _resolve(app, CHAT_B)

    assert response.status_code == 200
    assert threads
    assert all(thread != loop_thread for thread in threads)


@pytest.mark.asyncio
async def test_corrupt_catalog_is_an_error_instead_of_a_false_404(
    resolution_app,
):
    app, config = resolution_app
    path = Path(config.agents.profiles[f"a"].workspace_dir) / f"chats.json"
    path.write_text(f"invalid", encoding=f"utf-8")

    response = await _resolve(app, CHAT_B)

    assert response.status_code == 500
