# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.pawapp.context import PawAppContext


class _WorkspaceRegistry:
    def __init__(self, workspace):
        self.workspace = workspace

    async def get_agent(self, agent_id: str):
        assert agent_id == "qwenpaw-data"
        return self.workspace


@pytest.mark.asyncio
async def test_pawapp_dialogues_are_catalogued_and_scoped(tmp_path) -> None:
    manager = ChatManager(
        repo=JsonChatRepository(tmp_path / "chats.json"),
    )
    # Bare app-level session under the current namespace; adopted on sight.
    bare_app = ChatSpec(
        session_id="pawapp:qwenpaw-data",
        user_id="default",
        channel="console",
        name="Bare app session",
    )
    # Pre-rename DataPaw session. The rename is a clean break: the old
    # pawapp:datapaw namespace is intentionally NOT adopted, so this record
    # must not surface in the upgraded app's session list.
    pre_rename = ChatSpec(
        session_id="pawapp:datapaw",
        user_id="default",
        channel="console",
        name="Pre-rename transcript",
        meta={"pawapp": {"app_id": "datapaw", "agent_id": "datapaw"}},
    )
    foreign = ChatSpec(
        session_id="pawapp:qwenpaw-data:dialogue:foreign",
        user_id="default",
        channel="console",
        name="Another app's record",
        meta={"pawapp": {"app_id": "another", "agent_id": "qwenpaw-data"}},
    )
    await manager.create_chat(bare_app)
    await manager.create_chat(pre_rename)
    await manager.create_chat(foreign)
    context = PawAppContext(
        app_id="qwenpaw-data",
        agent_id="qwenpaw-data",
        channel="console",
        user_id="default",
        _workspace_registry=_WorkspaceRegistry(
            SimpleNamespace(chat_manager=manager),
        ),
    )

    sessions = await context.list_chat_sessions()
    created = await context.create_chat_session(name="New analysis")
    renamed = await context.rename_chat_session(
        created["id"],
        name="March GAAP",
    )
    pinned = await context.pin_chat_session(created["id"], pinned=True)
    unpinned = await context.pin_chat_session(created["id"], pinned=False)
    archived = await context.archive_chat_session(created["id"])

    # Only the bare app session is catalogued; the pre-rename pawapp:datapaw
    # record and the foreign app's record are both out of scope.
    assert [session["id"] for session in sessions] == [bare_app.id]
    assert sessions[0]["pinned"] is False
    adopted = await manager.get_chat(bare_app.id)
    assert adopted is not None
    assert adopted.meta["pawapp"] == {
        "app_id": "qwenpaw-data",
        "agent_id": "qwenpaw-data",
    }
    # The pre-rename record is left in storage untouched, just not surfaced.
    assert await manager.get_chat(pre_rename.id) is not None
    assert created["session_id"].startswith("pawapp:qwenpaw-data:dialogue:")
    assert renamed is not None and renamed["name"] == "March GAAP"
    assert pinned is not None and pinned["pinned"] is True
    assert unpinned is not None and unpinned["pinned"] is False
    assert archived is not None and archived["archived"] is True
    assert context.is_app_session_id("pawapp:qwenpaw-data")
    assert context.is_app_session_id("pawapp:qwenpaw-data:dialogue:1")
    # Clean break: the old DataPaw namespace is rejected.
    assert not context.is_app_session_id("pawapp:datapaw")
    assert not context.is_app_session_id("pawapp:datapaw:dialogue:1")
    assert not context.is_app_session_id("pawapp:another:dialogue:1")


@pytest.mark.asyncio
async def test_pawapp_dialogue_pin_and_delete_respect_ownership(
    tmp_path,
) -> None:
    manager = ChatManager(
        repo=JsonChatRepository(tmp_path / "chats.json"),
    )
    foreign = ChatSpec(
        session_id="pawapp:qwenpaw-data:dialogue:foreign",
        user_id="default",
        channel="console",
        name="Another app's record",
        meta={"pawapp": {"app_id": "another", "agent_id": "qwenpaw-data"}},
    )
    await manager.create_chat(foreign)
    context = PawAppContext(
        app_id="qwenpaw-data",
        agent_id="qwenpaw-data",
        channel="console",
        user_id="default",
        _workspace_registry=_WorkspaceRegistry(
            SimpleNamespace(chat_manager=manager),
        ),
    )
    created = await context.create_chat_session(name="Deletable")

    assert await context.pin_chat_session(foreign.id, pinned=True) is None
    assert await context.delete_chat_session(foreign.id) is False
    assert await context.delete_chat_session(created["id"]) is True
    assert await manager.get_chat(created["id"]) is None
    assert await manager.get_chat(foreign.id) is not None
