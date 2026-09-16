"""A dedicated override update preserves conversation fields and Agent scope."""

from datetime import UTC, datetime
from uuid import uuid4
import pytest
from qwenpaw.app.chats.repo.conversation import ConversationRecord
from qwenpaw.app.chats.repo.json_conversation_repo import JsonConversationRepository


@pytest.mark.asyncio
async def test_override_clear_and_wrong_agent_preserve_conversation(tmp_path):
    repo = JsonConversationRepository(tmp_path / "chats.json")
    now = datetime.now(UTC)
    record = ConversationRecord(
        id=uuid4(),
        agent_id=uuid4(),
        owner_user_id=uuid4(),
        title="Keep",
        status="active",
        created_at=now,
        updated_at=now,
    )
    await repo.create_conversation(record)
    model = uuid4()
    result = await repo.set_model_override(
        record.id,
        expected_agent_id=record.agent_id,
        model_override_id=model,
        updated_at=now,
    )
    assert result.title == "Keep" and result.model_override_id == model
    assert (
        await repo.set_model_override(
            record.id, expected_agent_id=uuid4(), model_override_id=None, updated_at=now
        )
        is None
    )
    assert (await repo.get_conversation(record.id)).model_override_id == model
    assert (
        await repo.set_model_override(
            record.id,
            expected_agent_id=record.agent_id,
            model_override_id=None,
            updated_at=now,
        )
    ).model_override_id is None


@pytest.mark.asyncio
async def test_legacy_real_manager_persists_only_private_model(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from qwenpaw.app.chats.manager import ChatManager
    from qwenpaw.app.chats.repo import JsonChatRepository
    from qwenpaw.app.chats.models import ChatSpec
    from qwenpaw.models.runtime import persist_selection

    monkeypatch.setattr("qwenpaw.models.runtime.is_multi_user_enabled", lambda: False)
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "legacy.json"))
    chat = await manager.create_chat(
        ChatSpec(session_id="one", user_id="alice", meta={"keep": True})
    )

    class Service:
        async def require_model(self, *args):
            return {"id": str(uuid4())}

    await persist_selection(
        Service(),
        None,
        SimpleNamespace(chat_manager=manager, agent_id="a"),
        chat,
        {"provider_id": "p", "model": "m"},
    )
    stored = await manager.get_chat(chat.id)
    assert stored.meta == {
        "keep": True,
        "model_override": {"provider_id": "p", "model": "m"},
    }
    await persist_selection(
        Service(),
        None,
        SimpleNamespace(chat_manager=manager, agent_id="a"),
        stored,
        None,
    )
    assert (await manager.get_chat(chat.id)).meta == {
        "keep": True,
        "model_override": None,
    }
