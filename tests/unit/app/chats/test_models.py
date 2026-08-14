# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError

from qwenpaw.app.chats.models import (
    ChatGroup,
    ChatGroupKind,
    ChatGroupUpdate,
    ChatSpec,
    ChatUpdate,
    ChatsFile,
    CRON_CHAT_GROUP_ID,
    DEFAULT_CHAT_GROUP_ID,
    SessionSource,
    SUBAGENT_CHAT_GROUP_ID,
)


# ---------------------------------------------------------------------------
# SessionSource enum
# ---------------------------------------------------------------------------


def test_session_source_values():
    assert SessionSource.chat == "chat"
    assert SessionSource.cron == "cron"
    assert SessionSource.subagent == "subagent"


# ---------------------------------------------------------------------------
# ChatSpec defaults
# ---------------------------------------------------------------------------


def test_chat_spec_auto_generates_uuid():
    spec = ChatSpec(session_id="console:u1", user_id="u1")
    assert spec.id  # non-empty UUID string
    assert len(spec.id) == 36  # standard UUID format


def test_chat_spec_default_values():
    spec = ChatSpec(session_id="console:u1", user_id="u1")
    assert spec.name == "New Chat"
    assert spec.pinned is False
    assert spec.source == SessionSource.chat
    assert spec.status == "idle"
    assert spec.meta == {}
    assert spec.group_id is None
    assert spec.parent_session_id is None
    assert spec.root_session_id is None


def test_chat_spec_requires_session_id_and_user_id():
    with pytest.raises(ValidationError):
        ChatSpec()
    with pytest.raises(ValidationError, match="session_id"):
        ChatSpec(user_id="u1")


def test_chat_spec_two_instances_get_different_ids():
    a = ChatSpec(session_id="s1", user_id="u1")
    b = ChatSpec(session_id="s1", user_id="u1")
    assert a.id != b.id


# ---------------------------------------------------------------------------
# ChatUpdate
# ---------------------------------------------------------------------------


def test_chat_update_allows_partial_fields():
    update = ChatUpdate(name="Renamed")
    assert update.name == "Renamed"
    assert update.pinned is None
    assert update.group_id is None


def test_chat_update_forbids_extra_fields():
    with pytest.raises(ValidationError):
        ChatUpdate(name="x", bogus=True)


def test_chat_update_all_null_means_no_change():
    update = ChatUpdate()
    assert update.name is None
    assert update.pinned is None


def test_chat_group_update_requires_a_field():
    with pytest.raises(ValidationError, match="At least one group field"):
        ChatGroupUpdate()


# ---------------------------------------------------------------------------
# ChatsFile
# ---------------------------------------------------------------------------


def test_chats_file_default_empty():
    cf = ChatsFile()
    assert cf.version == 1
    assert cf.chats == []
    assert [group.id for group in cf.groups] == [
        DEFAULT_CHAT_GROUP_ID,
        CRON_CHAT_GROUP_ID,
        SUBAGENT_CHAT_GROUP_ID,
    ]
    assert [group.kind for group in cf.groups] == [
        ChatGroupKind.default,
        ChatGroupKind.cron,
        ChatGroupKind.subagents,
    ]
    assert all(group.pinned is False for group in cf.groups)


def test_chats_file_restores_missing_system_groups():
    custom = ChatGroup(name="Work", order=0, kind=ChatGroupKind.custom)

    restored = ChatsFile.model_validate(
        {"version": 1, "chats": [], "groups": [custom.model_dump()]},
    )

    assert {group.id for group in restored.groups} == {
        custom.id,
        DEFAULT_CHAT_GROUP_ID,
        CRON_CHAT_GROUP_ID,
        SUBAGENT_CHAT_GROUP_ID,
    }


def test_chats_file_round_trip():
    spec = ChatSpec(session_id="console:u1", user_id="u1")
    cf = ChatsFile(version=1, chats=[spec])
    data = cf.model_dump(mode="json")
    restored = ChatsFile.model_validate(data)
    assert len(restored.chats) == 1
    assert restored.chats[0].session_id == "console:u1"
