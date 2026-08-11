# -*- coding: utf-8 -*-
"""Per-chat project-directory LIST overrides on ``ChatManager``.

Uses the real :class:`JsonChatRepository` so persistence is exercised
too: the override has to survive a round-trip through disk, since the
whole point is that it outlives a page reload.
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.services.project_directory import session_project_dirs_from_meta

_DEMO_LIST = [{"path": "/repos/demo", "label": None}]
_TWO_DIRS = [
    {"path": "/repos/main", "label": None},
    {"path": "/repos/extra", "label": "backend"},
]


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    return tmp_path / "chats.json"


@pytest.fixture
def manager(repo_path: Path) -> ChatManager:
    return ChatManager(repo=JsonChatRepository(repo_path))


async def _seed(manager: ChatManager, **meta: object) -> ChatSpec:
    spec = ChatSpec(
        session_id="console:u1",
        user_id="u1",
        name="Chat",
        meta=dict(meta),
    )
    return await manager.create_chat(spec)


@pytest.mark.asyncio
async def test_set_stores_in_controlled_namespace(manager: ChatManager):
    chat = await _seed(manager)

    updated = await manager.set_session_project_dirs(chat.id, _DEMO_LIST)

    assert updated is not None
    assert updated.meta["runtime_context"]["project_dirs"] == _DEMO_LIST
    assert session_project_dirs_from_meta(updated.meta) == _DEMO_LIST


@pytest.mark.asyncio
async def test_stores_multiple_dirs_with_labels(manager: ChatManager):
    chat = await _seed(manager)

    updated = await manager.set_session_project_dirs(chat.id, _TWO_DIRS)

    assert updated is not None
    assert session_project_dirs_from_meta(updated.meta) == [
        {"path": str(Path("/repos/main")), "label": None},
        {"path": str(Path("/repos/extra")), "label": "backend"},
    ]


@pytest.mark.asyncio
async def test_override_persists_across_repo_reload(
    manager: ChatManager,
    repo_path: Path,
):
    """The override must outlive the process, not just the in-memory spec."""
    chat = await _seed(manager)
    await manager.set_session_project_dirs(chat.id, _TWO_DIRS)

    reloaded = ChatManager(repo=JsonChatRepository(repo_path))
    fetched = await reloaded.get_chat(chat.id)

    assert fetched is not None
    entries = session_project_dirs_from_meta(fetched.meta)
    assert entries is not None
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_clear_removes_empty_namespace(manager: ChatManager):
    chat = await _seed(manager)
    await manager.set_session_project_dirs(chat.id, _DEMO_LIST)

    cleared = await manager.set_session_project_dirs(chat.id, None)

    assert cleared is not None
    assert session_project_dirs_from_meta(cleared.meta) is None
    # No leftover scaffolding for a chat that no longer overrides.
    assert "runtime_context" not in cleared.meta


@pytest.mark.asyncio
async def test_legacy_singular_key_is_dropped_on_write(
    manager: ChatManager,
):
    """Singular-era chats stored one path; the list supersedes it."""
    chat = await _seed(
        manager,
        runtime_context={"project_dir": "/repos/old-single"},
    )

    updated = await manager.set_session_project_dirs(chat.id, _DEMO_LIST)

    assert updated is not None
    assert "project_dir" not in updated.meta["runtime_context"]
    assert session_project_dirs_from_meta(updated.meta) == _DEMO_LIST

    # Clearing also drops the legacy key.
    cleared = await manager.set_session_project_dirs(chat.id, None)
    assert cleared is not None
    assert session_project_dirs_from_meta(cleared.meta) is None


@pytest.mark.asyncio
async def test_sibling_meta_keys_survive(manager: ChatManager):
    """Setting/clearing must not clobber unrelated system metadata."""
    chat = await _seed(manager, some_system_key="keep-me")

    await manager.set_session_project_dirs(chat.id, _DEMO_LIST)
    after_set = await manager.get_chat(chat.id)
    assert after_set is not None
    assert after_set.meta["some_system_key"] == "keep-me"

    await manager.set_session_project_dirs(chat.id, None)
    after_clear = await manager.get_chat(chat.id)
    assert after_clear is not None
    assert after_clear.meta["some_system_key"] == "keep-me"


@pytest.mark.asyncio
async def test_sibling_runtime_context_keys_survive(manager: ChatManager):
    chat = await _seed(manager, runtime_context={"other_setting": "x"})

    await manager.set_session_project_dirs(chat.id, _DEMO_LIST)
    after_set = await manager.get_chat(chat.id)
    assert after_set is not None
    assert after_set.meta["runtime_context"]["other_setting"] == "x"

    await manager.set_session_project_dirs(chat.id, None)
    after_clear = await manager.get_chat(chat.id)
    assert after_clear is not None
    # The namespace stays because a sibling key still lives there.
    assert after_clear.meta["runtime_context"] == {"other_setting": "x"}


@pytest.mark.asyncio
async def test_unknown_chat_returns_none(manager: ChatManager):
    assert await manager.set_session_project_dirs("nope", _DEMO_LIST) is None


@pytest.mark.asyncio
async def test_set_bumps_updated_at(manager: ChatManager):
    chat = await _seed(manager)

    updated = await manager.set_session_project_dirs(chat.id, _DEMO_LIST)

    assert updated is not None
    assert updated.updated_at >= chat.updated_at


@pytest.mark.asyncio
async def test_concurrent_sets_do_not_lose_updates(manager: ChatManager):
    """Read-modify-write happens under the lock, so nothing is dropped."""
    chat = await _seed(manager, some_system_key="keep-me")

    await asyncio.gather(
        *(
            manager.set_session_project_dirs(
                chat.id,
                [{"path": f"/repos/p{i}", "label": None}],
            )
            for i in range(10)
        ),
    )

    final = await manager.get_chat(chat.id)
    assert final is not None
    assert final.meta["some_system_key"] == "keep-me"
    entries = session_project_dirs_from_meta(final.meta)
    assert entries is not None
    assert len(entries) == 1
    assert entries[0]["path"] in {f"/repos/p{i}" for i in range(10)}


@pytest.mark.asyncio
async def test_clearing_a_never_set_override_is_safe(manager: ChatManager):
    chat = await _seed(manager)

    cleared = await manager.set_session_project_dirs(chat.id, None)

    assert cleared is not None
    assert "runtime_context" not in cleared.meta


@pytest.mark.asyncio
async def test_empty_list_is_treated_as_clear(manager: ChatManager):
    chat = await _seed(manager)
    await manager.set_session_project_dirs(chat.id, _DEMO_LIST)

    cleared = await manager.set_session_project_dirs(chat.id, [])

    assert cleared is not None
    assert session_project_dirs_from_meta(cleared.meta) is None


@pytest.mark.asyncio
async def test_project_name_round_trips(manager: ChatManager):
    chat = await _seed(manager)

    updated = await manager.set_session_project_dirs(
        chat.id,
        _DEMO_LIST,
        "My Project",
    )
    assert updated is not None
    assert updated.meta["runtime_context"]["project_name"] == "My Project"

    # A name without directories describes nothing — clearing the dirs
    # also drops the name.
    cleared = await manager.set_session_project_dirs(chat.id, None)
    assert cleared is not None
    assert "project_name" not in cleared.meta.get("runtime_context", {})
