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
        assert agent_id == "datapaw"
        return self.workspace


@pytest.mark.asyncio
async def test_pawapp_dialogues_are_catalogued_and_scoped(tmp_path) -> None:
    manager = ChatManager(
        repo=JsonChatRepository(tmp_path / "chats.json"),
    )
    legacy = ChatSpec(
        session_id="pawapp:datapaw",
        user_id="default",
        channel="console",
        name="Old transcript",
    )
    foreign = ChatSpec(
        session_id="pawapp:datapaw:dialogue:foreign",
        user_id="default",
        channel="console",
        name="Another app's record",
        meta={"pawapp": {"app_id": "another", "agent_id": "datapaw"}},
    )
    await manager.create_chat(legacy)
    await manager.create_chat(foreign)
    context = PawAppContext(
        app_id="datapaw",
        agent_id="datapaw",
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
    archived = await context.archive_chat_session(created["id"])

    assert [session["id"] for session in sessions] == [legacy.id]
    adopted = await manager.get_chat(legacy.id)
    assert adopted is not None
    assert adopted.meta["pawapp"] == {
        "app_id": "datapaw",
        "agent_id": "datapaw",
    }
    assert created["session_id"].startswith("pawapp:datapaw:dialogue:")
    assert renamed is not None and renamed["name"] == "March GAAP"
    assert archived is not None and archived["archived"] is True
    assert context.is_app_session_id("pawapp:datapaw")
    assert context.is_app_session_id("pawapp:datapaw:dialogue:1")
    assert not context.is_app_session_id("pawapp:another:dialogue:1")
