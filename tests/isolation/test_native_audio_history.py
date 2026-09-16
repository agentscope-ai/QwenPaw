"""Real native conversion/history pipeline with a controlled converter only."""
import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentscope.message import Base64Source, DataBlock, Msg
from fastapi import HTTPException, Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.agents.utils import message_processing
from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.app.chats.api import _protect_history_attachment_urls
from qwenpaw.app.chats.repo import AttachmentRecord
from qwenpaw.app.chats.utils import agentscope_msg_to_message
from qwenpaw.app.routers import console
from qwenpaw.config.config import Config
from qwenpaw.identity.models import PlatformRole
from qwenpaw.runtime.message_convert import _request_input_to_msgs
from qwenpaw.schemas import AudioContent


@pytest.fixture
def native_pipeline(monkeypatch, tmp_path):
    owner, conversation, attachment = uuid4(), uuid4(), uuid4()
    original, derived = tmp_path / "original.webm", tmp_path / "derived.wav"
    original.write_bytes(b"ORIGINAL_AUDIO")
    def convert(path):
        assert path == str(original)
        derived.write_bytes(b"PRIVATE_WAV_AUDIO")
        return str(derived)
    config = Config()
    config.agents.audio_mode = "native"
    monkeypatch.setattr(message_processing, "load_config", lambda: config)
    monkeypatch.setattr(message_processing, "_convert_audio_to_wav", convert)
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    now = datetime.now(UTC)
    record = AttachmentRecord(id=attachment, agent_id=agent_database_id("default"),
        conversation_id=conversation, message_id=None, owner_user_id=owner,
        storage_key=str(original), original_name=original.name, media_type="audio/webm",
        size=14, content_hash="test", created_at=now, updated_at=now)
    repo = SimpleNamespace(get_attachment=AsyncMock(return_value=record))
    repo.with_user = lambda user: repo
    workspace = SimpleNamespace(agent_id="default", chat_manager=SimpleNamespace(conversation_repository=repo))
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(user_id=owner, actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER, admin_mode=False, request_id="native-history")
    channel = ConsoleChannel(process=AsyncMock(), enabled=True, bot_prefix="")
    channel._media_dir = tmp_path
    return SimpleNamespace(record=record, workspace=workspace, request=request, channel=channel,
        original=original, derived=derived, repo=repo, url=f"/api/console/attachments/{attachment}")


async def converted_history(fixture):
    content = AudioContent(data=fixture.url)
    payload = {"content_parts": [content], "sender_id": str(fixture.record.owner_user_id),
               "channel_id": "console", "meta": {"session_id": "native-test"}}
    await console._resolve_console_attachment_refs(fixture.request, fixture.workspace, payload,
        conversation_id=str(fixture.record.conversation_id))
    payload["content_parts"] = fixture.channel._resolve_console_upload_refs(payload["content_parts"])
    request = fixture.channel.build_agent_request_from_native(payload)
    msgs = _request_input_to_msgs(request.input)
    await message_processing.process_file_and_media_blocks_in_message(msgs)
    assert isinstance(msgs[0].content[0].source, Base64Source)
    assert base64.b64decode(msgs[0].content[0].source.data) == b"PRIVATE_WAV_AUDIO"
    assert fixture.original.read_bytes() == b"ORIGINAL_AUDIO"
    assert not fixture.derived.exists()
    # Exercise the actual saved context shape, not an ad-hoc data URI.
    restored = Msg.model_validate_json(msgs[0].model_dump_json())
    return agentscope_msg_to_message([restored])


@pytest.mark.asyncio
async def test_native_owner_history_uses_original_protected_reference(native_pipeline):
    messages = await converted_history(native_pipeline)
    _protect_history_attachment_urls(messages, [native_pipeline.record], hide_unowned_local_urls=False)
    assert messages[0].content[0].data == native_pipeline.url
    assert "PRIVATE_WAV_AUDIO" not in json.dumps([m.model_dump(mode="json") for m in messages])
    assert base64.b64encode(b"PRIVATE_WAV_AUDIO").decode() not in str(messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["shared", "deleted", "moved"])
async def test_native_history_respects_current_attachment_access(native_pipeline, state):
    messages = await converted_history(native_pipeline)
    record = native_pipeline.record
    attachments = [] if state == "shared" else [record.model_copy(update={
        "lifecycle": "deleted" if state == "deleted" else "saved",
        "storage_key": str(native_pipeline.original.parent / "moved.webm"),
    })]
    _protect_history_attachment_urls(messages, attachments, hide_unowned_local_urls=state == "shared")
    assert messages[0].content[0].data == (native_pipeline.url if state == "moved" else "")


def test_legacy_inline_audio_still_converts_to_data_uri():
    msg = Msg(name="user", role="user", content=[DataBlock(source=Base64Source(
        data="TEVHQUNZ", media_type="audio/wav"))])
    assert agentscope_msg_to_message([msg])[0].content[0].data == "data:audio/wav;base64,TEVHQUNZ"


def test_unlinked_old_inline_audio_not_exposed_to_shared_viewer():
    msg = Msg(name="user", role="user", content=[DataBlock(source=Base64Source(
        data="TEVHQUNZ", media_type="audio/wav"))])
    history = agentscope_msg_to_message([msg])
    _protect_history_attachment_urls(history, [], hide_unowned_local_urls=True)
    assert history[0].content[0].data == ""


@pytest.mark.asyncio
async def test_deleted_original_download_is_revoked_even_if_file_remains(native_pipeline, monkeypatch):
    native_pipeline.repo.get_attachment.return_value = native_pipeline.record.model_copy(update={"lifecycle": "deleted"})
    monkeypatch.setattr("qwenpaw.app.chats.repo.PostgresConversationRepository", lambda **kw: native_pipeline.repo)
    monkeypatch.setattr("qwenpaw.identity.runtime.get_identity_schema", lambda: "unused")
    with pytest.raises(HTTPException) as exc:
        await console.get_console_attachment(native_pipeline.record.id, native_pipeline.request)
    assert exc.value.status_code == 404
