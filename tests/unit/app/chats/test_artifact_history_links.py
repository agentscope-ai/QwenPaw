"""本人历史产物链接应绑定登记 ID，而非短期令牌或机器绝对目录。"""
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.schemas import AudioContent, DataContent, FileContent, Message, TextContent


def artifact(owner, conversation, agent="designer", **changes):
    return SimpleNamespace(
        id=changes.get("id", uuid4()), owner_user_id=owner,
        agent_id=agent_database_id(agent), conversation_id=conversation,
        relative_path="artifacts/.registered/archive/防水简报.pdf",
        original_name="防水简报.pdf", status=changes.get("status", "active"),
        created_at=datetime.now(UTC),
    )


def test_registered_owner_history_links_survive_old_host_token_and_archive_paths(tmp_path):
    from qwenpaw.app.chats.artifact_history import normalize_owned_artifact_history

    owner, conversation = uuid4(), uuid4()
    record = artifact(owner, conversation)
    path = tmp_path / "user_workspaces" / str(owner) / "designer" / record.relative_path
    expected = f"/api/console/artifacts/{record.id}/download"
    old_url = f"https://old-host.invalid/api/console/artifacts/{record.id}/download?token=expired"
    output = [{"type": "data", "name": record.original_name, "source": {"type": "url", "url": path.as_uri()}}]
    messages = [Message(content=[
        FileContent(file_url=path.as_uri()), FileContent(file_url=old_url),
        TextContent(text=f"[下载简报]({old_url})"),
        DataContent(data={"output": output}),
    ])]
    normalize_owned_artifact_history(messages, [record], owner_user_id=owner,
        agent_key="designer", conversation_id=conversation, working_dir=tmp_path)
    assert [item.file_url for item in messages[0].content[:2]] == [expected, expected]
    assert messages[0].content[0].filename == "防水简报.pdf"
    assert messages[0].content[2].text == f"[下载简报]({expected})"
    assert messages[0].content[3].data["output"][0]["source"]["url"] == expected
    assert output[0]["source"]["url"] == path.as_uri(), "不能改写原始消息事实"


@pytest.mark.parametrize("scope", ["other_user", "other_agent", "other_conversation", "deleted"])
def test_only_matching_live_artifact_metadata_can_rewrite_a_reference(tmp_path, scope):
    from qwenpaw.app.chats.artifact_history import normalize_owned_artifact_history

    owner, conversation = uuid4(), uuid4()
    record = artifact(uuid4() if scope == "other_user" else owner,
        uuid4() if scope == "other_conversation" else conversation,
        agent="other-agent" if scope == "other_agent" else "designer",
        status="deleted" if scope == "deleted" else "active")
    old_url = f"https://old-host.invalid/api/console/artifacts/{record.id}/download?token=expired"
    messages = [Message(content=[FileContent(file_url=old_url), AudioContent(data=old_url)])]
    normalize_owned_artifact_history(messages, [record], owner_user_id=owner,
        agent_key="designer", conversation_id=conversation, working_dir=tmp_path)
    assert messages[0].content[0].file_url == old_url
    assert messages[0].metadata["qwenpaw_file_reference_status"][0]["code"] == "artifact_reference_unavailable"


def test_same_filename_is_not_proof_of_a_registered_file(tmp_path):
    from qwenpaw.app.chats.artifact_history import normalize_owned_artifact_history

    owner, conversation = uuid4(), uuid4()
    record = artifact(owner, conversation)
    source = tmp_path / "unrelated" / record.original_name
    messages = [Message(content=[FileContent(file_url=source.as_uri())])]
    normalize_owned_artifact_history(messages, [record], owner_user_id=owner,
        agent_key="designer", conversation_id=conversation, working_dir=tmp_path)
    assert messages[0].content[0].file_url == source.as_uri()


def test_legacy_send_file_projection_keeps_data_block_name_and_stable_delivery_link(tmp_path):
    import json
    from agentscope.message import Msg
    from qwenpaw.app.chats.artifact_history import normalize_owned_artifact_history
    from qwenpaw.app.chats.utils import agentscope_msg_to_message

    identifier = uuid4()
    owner, conversation = uuid4(), uuid4()
    registered = artifact(owner, conversation, id=identifier)
    expected = f"/api/console/artifacts/{identifier}/download"
    message = Msg(name="assistant", role="assistant", content=[{
        "type": "tool_result", "id": "send-report", "name": "send_file_to_user",
        "output": [
            {"type": "data", "name": "防水简报.pdf", "source": {"type": "url", "url": "file:///old-machine/report.pdf", "media_type": "application/pdf"}},
            {"type": "text", "text": f"File sent successfully. Download link: {expected}\nUse this exact relative URL."},
        ],
    }])
    restored = Msg.model_validate_json(message.model_dump_json())
    messages = agentscope_msg_to_message([restored])
    normalize_owned_artifact_history(messages, [registered], owner_user_id=owner,
        agent_key="designer", conversation_id=conversation, working_dir=tmp_path)
    blocks = json.loads(messages[0].content[0].data["output"])
    assert blocks[0]["source"]["url"] == expected
    assert blocks[0]["name"] == "防水简报.pdf"
    assert "qwenpaw_file_reference_status" not in (messages[0].metadata or {})


def test_registered_attachment_is_not_misdiagnosed_as_missing_artifact(tmp_path):
    from qwenpaw.app.chats.artifact_history import normalize_owned_artifact_history
    owner, conversation = uuid4(), uuid4()
    source = tmp_path / "original.pdf"
    messages = [Message(content=[FileContent(file_url=source.as_posix())])]
    normalize_owned_artifact_history(messages, [], owner_user_id=owner, agent_key="designer",
        conversation_id=conversation, working_dir=tmp_path,
        attachments=[SimpleNamespace(lifecycle="temporary", storage_key=str(source))])
    assert "qwenpaw_file_reference_status" not in (messages[0].metadata or {})


@pytest.mark.asyncio
@pytest.mark.parametrize("access_kind", ["owner", "readonly_owner", "viewer"])
async def test_history_endpoint_only_uses_current_conversation_owners_artifact_registry(monkeypatch, access_kind):
    from unittest.mock import AsyncMock
    from qwenpaw.app.chats import api
    from qwenpaw.app.chats.models import ChatSpec

    owner, conversation = uuid4(), uuid4()
    actor = uuid4() if access_kind == "viewer" else owner
    registered = artifact(owner, conversation)
    old_url = f"https://old-host.invalid/api/console/artifacts/{registered.id}/download?token=expired"
    messages = [Message(content=[FileContent(file_url=old_url), AudioContent(data=old_url)])]
    access = SimpleNamespace(conversation=SimpleNamespace(owner_user_id=owner),
        read_only=access_kind != "owner", access_role="viewer" if access_kind == "viewer" else "owner",
        shared_by_username=None)
    chat = ChatSpec(id=str(conversation), session_id=str(conversation), user_id=str(owner), channel="console", name="history")
    conversation_repo = SimpleNamespace(list_attachments=AsyncMock(return_value=[]))
    conversation_repo.with_user = lambda user_id: conversation_repo
    artifact_repo = SimpleNamespace(list_active=AsyncMock(return_value=[registered]))
    constructor = lambda **kwargs: artifact_repo
    monkeypatch.setattr(api, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(api, "get_actor", lambda request: SimpleNamespace(user_id=actor))
    monkeypatch.setattr(api, "load_cutover_policy", lambda: SimpleNamespace(read_uses_postgres=lambda _: True))
    monkeypatch.setattr(api, "_require_readable_chat", AsyncMock(return_value=(chat, access)))
    monkeypatch.setattr(api, "_load_postgres_history_messages", AsyncMock(return_value=messages))
    monkeypatch.setattr("qwenpaw.identity.runtime.get_identity_schema", lambda: "test")
    monkeypatch.setattr("qwenpaw.artifacts.repository.PostgresArtifactRepository", constructor)
    result = await api.get_chat(str(conversation), SimpleNamespace(),
        mgr=SimpleNamespace(conversation_repository=conversation_repo), session=None,
        workspace=SimpleNamespace(agent_id="designer", task_tracker=SimpleNamespace(get_status=AsyncMock(return_value="idle"))),
        page_size=None, before_sequence=None)
    if access_kind == "viewer":
        artifact_repo.list_active.assert_not_awaited()
        conversation_repo.list_attachments.assert_not_awaited()
    else:
        artifact_repo.list_active.assert_awaited_once_with(owner_user_id=owner, agent_id=agent_database_id("designer"))
        assert result.messages[0].content[0].file_url == f"/api/console/artifacts/{registered.id}/download"
        assert result.messages[0].content[1].data == f"/api/console/artifacts/{registered.id}/download"


@pytest.mark.asyncio
async def test_artifact_registry_failure_keeps_the_owners_conversation_readable(monkeypatch):
    from unittest.mock import AsyncMock
    from qwenpaw.app.chats import api

    owner, conversation = uuid4(), uuid4()
    messages = [Message(content=[TextContent(text="原来的对话内容"), FileContent(file_url=f"/api/console/artifacts/{uuid4()}/download")])]
    repository = SimpleNamespace(list_active=AsyncMock(side_effect=RuntimeError("registry unavailable")))
    monkeypatch.setattr("qwenpaw.artifacts.repository.PostgresArtifactRepository", lambda **kwargs: repository)
    monkeypatch.setattr("qwenpaw.identity.runtime.get_identity_schema", lambda: "test")
    await api._protect_owned_history_artifact_urls(messages, user_id=owner, agent_key="designer", conversation_id=conversation)
    assert messages[0].content[0].text == "原来的对话内容"
    assert messages[0].metadata["qwenpaw_file_reference_status"][0]["code"] == "artifact_reference_lookup_unavailable"
