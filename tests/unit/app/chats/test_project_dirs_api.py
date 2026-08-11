# -*- coding: utf-8 -*-
"""HTTP surface for per-chat project-directory LIST overrides.

Covers the plural ``/chats/{id}/project-dirs`` endpoints and the
deprecated singular wrappers, including payload validation (U10):
empty lists, oversized lists and unknown fields are all rejected with
422 before anything is persisted.
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.chats.api import get_chat_manager, get_workspace, router
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository


@pytest.fixture
def manager(tmp_path: Path) -> ChatManager:
    return ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))


@pytest.fixture
def workspace(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="no-such-agent",
        workspace_dir=tmp_path / "workspace",
    )


@pytest.fixture
def client(manager: ChatManager, workspace: SimpleNamespace) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace] = lambda: workspace
    app.dependency_overrides[get_chat_manager] = lambda: manager
    return TestClient(app)


async def _seed(manager: ChatManager) -> ChatSpec:
    return await manager.create_chat(
        ChatSpec(
            session_id="console:u1",
            user_id="u1",
            name="Chat",
        ),
    )


@pytest.mark.asyncio
async def test_put_binds_list_and_get_returns_it(
    client,
    manager,
    tmp_path,
):
    chat = await _seed(manager)
    main = tmp_path / "main"
    extra = tmp_path / "extra"
    main.mkdir()
    extra.mkdir()

    response = client.put(
        f"/chats/{chat.id}/project-dirs",
        json={
            "project_dirs": [
                {"path": str(main), "label": "backend"},
                {"path": str(extra)},
            ],
            "project_name": "My Project",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [entry["path"] for entry in body["project_dirs"]] == [
        str(main.resolve()),
        str(extra.resolve()),
    ]
    assert body["source"] == "session"
    assert body["project_name"] == "My Project"
    assert body["project_name_is_custom"] is True

    fetched = client.get(f"/chats/{chat.id}/project-dirs")
    assert fetched.status_code == 200
    again = fetched.json()
    assert [entry["path"] for entry in again["project_dirs"]] == [
        str(main.resolve()),
        str(extra.resolve()),
    ]
    # Labels survive the round-trip.
    assert again["project_dirs"][0]["label"] == "backend"


@pytest.mark.asyncio
async def test_derived_name_falls_back_to_primary_basename(
    client,
    manager,
    tmp_path,
):
    chat = await _seed(manager)
    main = tmp_path / "the-project"
    main.mkdir()

    response = client.put(
        f"/chats/{chat.id}/project-dirs",
        json={"project_dirs": [{"path": str(main)}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["project_name"] == "the-project"
    assert body["project_name_is_custom"] is False


@pytest.mark.asyncio
async def test_empty_list_is_rejected(client, manager):
    chat = await _seed(manager)

    response = client.put(
        f"/chats/{chat.id}/project-dirs",
        json={"project_dirs": []},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_oversized_list_is_rejected(client, manager, tmp_path):
    chat = await _seed(manager)
    dirs = [{"path": str(tmp_path / f"d{i}")} for i in range(11)]
    for entry in dirs:
        Path(entry["path"]).mkdir(exist_ok=True)

    response = client.put(
        f"/chats/{chat.id}/project-dirs",
        json={"project_dirs": dirs},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_field_is_rejected(client, manager, tmp_path):
    chat = await _seed(manager)
    main = tmp_path / "main"
    main.mkdir()

    response = client.put(
        f"/chats/{chat.id}/project-dirs",
        json={
            "project_dirs": [{"path": str(main)}],
            "bogus_field": 1,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_nonexistent_directory_is_rejected(client, manager, tmp_path):
    chat = await _seed(manager)

    response = client.put(
        f"/chats/{chat.id}/project-dirs",
        json={"project_dirs": [{"path": str(tmp_path / "missing")}]},
    )
    assert response.status_code == 422
    assert "Not a directory" in response.text


@pytest.mark.asyncio
async def test_duplicate_paths_are_deduplicated(client, manager, tmp_path):
    chat = await _seed(manager)
    main = tmp_path / "main"
    main.mkdir()

    response = client.put(
        f"/chats/{chat.id}/project-dirs",
        json={
            "project_dirs": [
                {"path": str(main), "label": "first"},
                {"path": str(main), "label": "dup"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["project_dirs"]) == 1
    assert body["project_dirs"][0]["label"] == "first"


@pytest.mark.asyncio
async def test_delete_clears_the_override(client, manager, tmp_path):
    chat = await _seed(manager)
    main = tmp_path / "main"
    main.mkdir()
    client.put(
        f"/chats/{chat.id}/project-dirs",
        json={"project_dirs": [{"path": str(main)}]},
    )

    response = client.delete(f"/chats/{chat.id}/project-dirs")
    assert response.status_code == 200
    body = response.json()
    # Agent has no default configured → workspace fallback, empty list.
    assert body["project_dirs"] == []
    assert body["source"] == "workspace_fallback"


@pytest.mark.asyncio
async def test_nested_roots_are_reported_not_rejected(
    client,
    manager,
    tmp_path,
):
    chat = await _seed(manager)
    parent = tmp_path / "project"
    child = parent / "src"
    child.mkdir(parents=True)

    response = client.put(
        f"/chats/{chat.id}/project-dirs",
        json={
            "project_dirs": [
                {"path": str(parent)},
                {"path": str(child)},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["project_dirs"]) == 2
    assert body["project_dirs"][0]["nested_with"] is None
    assert body["project_dirs"][1]["nested_with"] == str(parent.resolve())


@pytest.mark.asyncio
async def test_singular_put_writes_a_one_entry_list(
    client,
    manager,
    tmp_path,
):
    chat = await _seed(manager)
    main = tmp_path / "main"
    main.mkdir()

    legacy = client.put(
        f"/chats/{chat.id}/project-dir",
        json={"project_dir": str(main)},
    )
    assert legacy.status_code == 200, legacy.text

    plural = client.get(f"/chats/{chat.id}/project-dirs")
    assert plural.status_code == 200
    body = plural.json()
    assert [entry["path"] for entry in body["project_dirs"]] == [
        str(main.resolve()),
    ]
    assert body["source"] == "session"


@pytest.mark.asyncio
async def test_missing_chat_is_404(client):
    response = client.get("/chats/nope/project-dirs")
    assert response.status_code == 404
    response = client.put(
        "/chats/nope/project-dirs",
        json={"project_dirs": [{"path": "/tmp"}]},
    )
    assert response.status_code == 404
    assert client.delete("/chats/nope/project-dirs").status_code == 404
