"""迁移或令牌失效后，只用本人有效附件登记修复历史链接。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.chats.api import _protect_history_attachment_urls
from qwenpaw.schemas import AudioContent, DataContent, FileContent, ImageContent, Message, TextContent, VideoContent


@pytest.mark.parametrize("kind,field", [(FileContent, "file_url"), (ImageContent, "image_url"), (AudioContent, "data"), (VideoContent, "video_url")])
def test_owned_old_host_attachment_uses_stable_id(kind, field):
    record = SimpleNamespace(id=uuid4(), lifecycle="saved", storage_key="old-file", agent_id=agent_database_id("reporter"))
    old = f"https://previous.invalid/api/agents/reporter/console/attachments/{record.id}?token=expired"
    messages = [Message(content=[kind(**{field: old})])]
    _protect_history_attachment_urls(messages, [record], hide_unowned_local_urls=False)
    assert getattr(messages[0].content[0], field) == f"/api/console/attachments/{record.id}"


def test_nested_attachment_links_are_normalized_without_mutating_persisted_facts():
    record = SimpleNamespace(id=uuid4(), lifecycle="temporary", storage_key="old-file", agent_id=agent_database_id("reporter"))
    old = f"https://previous.invalid/api/console/attachments/{record.id}?token=expired"
    output = [{"source": {"url": old}}]
    messages = [Message(content=[TextContent(text=f"[附件]({old})"), DataContent(data={"output": output})])]
    _protect_history_attachment_urls(messages, [record], hide_unowned_local_urls=False)
    expected = f"/api/console/attachments/{record.id}"
    assert messages[0].content[0].text == f"[附件]({expected})"
    assert messages[0].content[1].data["output"][0]["source"]["url"] == expected
    assert output[0]["source"]["url"] == old


@pytest.mark.parametrize("case", ["unowned", "deleted", "wrong_agent"])
def test_attachment_rebinding_never_infers_missing_ownership(case):
    record = SimpleNamespace(id=uuid4(), lifecycle="deleted" if case == "deleted" else "saved", storage_key="old-file", agent_id=agent_database_id("reporter"))
    old = f"https://previous.invalid/api/agents/{'other' if case == 'wrong_agent' else 'reporter'}/console/attachments/{record.id}?token=expired"
    messages = [Message(content=[FileContent(file_url=old)])]
    _protect_history_attachment_urls(messages, [] if case == "unowned" else [record], hide_unowned_local_urls=False)
    assert messages[0].content[0].file_url == old


@pytest.mark.asyncio
async def test_deferred_tool_output_keeps_the_same_owned_attachment_link_rules(monkeypatch):
    from qwenpaw.app.chats import api, history
    user_id, conversation_id, message_id = uuid4(), uuid4(), uuid4()
    attachment = SimpleNamespace(id=uuid4(), lifecycle="saved", storage_key="old-file", agent_id=agent_database_id("reporter"))
    old = f"https://previous.invalid/api/console/attachments/{attachment.id}?token=expired"
    message = Message(type="plugin_call_output", content=[DataContent(data={"output": [{"source": {"url": old}}]})])
    repo = SimpleNamespace(get_message=AsyncMock(return_value=SimpleNamespace(conversation_id=conversation_id)), list_attachments=AsyncMock(return_value=[attachment]))
    repo.with_user = lambda _: repo
    monkeypatch.setattr(api, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(api, "load_cutover_policy", lambda: SimpleNamespace(read_uses_postgres=lambda _: True))
    monkeypatch.setattr(api, "get_actor", lambda _: SimpleNamespace(user_id=user_id))
    monkeypatch.setattr(api, "_require_readable_chat", AsyncMock(return_value=(None, SimpleNamespace(conversation=SimpleNamespace(owner_user_id=user_id), read_only=True))))
    monkeypatch.setattr(history, "project_history_messages", AsyncMock(return_value=[message]))
    result = await api.get_chat_tool_output(str(conversation_id), str(message_id), SimpleNamespace(),
        mgr=SimpleNamespace(conversation_repository=repo), session=None, workspace=SimpleNamespace(agent_id="reporter"))
    assert result.content[0].data["output"][0]["source"]["url"] == f"/api/console/attachments/{attachment.id}"
