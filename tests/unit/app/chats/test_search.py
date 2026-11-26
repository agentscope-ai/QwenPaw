# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Search over transcripts and durable history respects read boundaries."""

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.app.chats import search
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.search import (
    ChatSearchRequest,
    keyword_search,
    load_search_corpus,
    visible_text,
)
from qwenpaw.app.chats.session import session_filename
from qwenpaw.constant import QWENPAW_USER_CONTENT_KEY


def make_chat(chat_id="one", *, name="Generated title", minutes=0):
    return ChatSpec(
        id=chat_id,
        name=name,
        session_id=f"session-{chat_id}",
        user_id="user",
        channel="console",
        updated_at=datetime(2026, 10, 22, tzinfo=timezone.utc)
        + timedelta(minutes=minutes),
    )


def make_workspace(tmp_path):
    return SimpleNamespace(
        agent_id="agent-one",
        workspace_dir=tmp_path,
        session=SimpleNamespace(save_dir=str(tmp_path / "sessions")),
        config=SimpleNamespace(
            running=SimpleNamespace(
                light_context_config=SimpleNamespace(
                    scroll_config=SimpleNamespace(db_filename="history.db"),
                ),
            ),
        ),
    )


def write_snapshot(workspace, chat, messages, *, legacy=False):
    from pathlib import Path

    root = Path(workspace.session.save_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / session_filename(chat.session_id, chat.user_id)
    agent = (
        {"memory": {"content": [[item, []] for item in messages]}}
        if legacy
        else {"state": {"context": messages}}
    )
    path.write_text(json.dumps({"agent": agent}), encoding="utf-8")
    return path


@pytest.mark.parametrize("legacy", [False, True])
async def test_body_search_supports_current_and_legacy_without_migration(
    tmp_path,
    legacy,
):
    workspace = make_workspace(tmp_path)
    chat = make_chat()
    path = write_snapshot(
        workspace,
        chat,
        [
            {
                "id": "user-1",
                "role": "user",
                "content": "部署 Kubernetes 测试",
            },
            {
                "id": "reply",
                "role": "assistant",
                "content": "Use API_TOKEN=abc",
            },
        ],
        legacy=legacy,
    )
    before = path.stat().st_mtime_ns
    corpus = await load_search_corpus(workspace, [chat])
    result = keyword_search(corpus, ChatSearchRequest(query="api_TOKEN"))
    assert result.total == 1
    assert result.results[0].role == "assistant"
    assert result.results[0].message_id == "reply"
    assert "API_TOKEN" in result.results[0].snippet
    assert corpus.search("部署")[0].role == "user"
    assert not corpus.partial
    assert not (path.parent / "console").exists()
    assert not (tmp_path / "history.db").exists()
    assert path.stat().st_mtime_ns == before


@pytest.mark.parametrize(
    "message",
    [
        {"role": "system", "content": "secret"},
        {"role": "tool", "content": "secret"},
        {"role": "user", "content": "secret", "name": "visual_history"},
        {
            "role": "user",
            "content": "secret",
            "metadata": {"qwenpaw_tag": "auto_continue"},
        },
        {
            "role": "assistant",
            "content": "secret",
            "metadata": {"qwenpaw_tag": "scroll_memory"},
        },
        {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "secret"}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_result",
                    "output": [{"type": "text", "text": "secret"}],
                },
            ],
        },
    ],
)
def test_internal_messages_are_not_searchable(message):
    assert visible_text(message) is None


def test_visible_text_restores_user_input_and_strips_injected_skill():
    item = visible_text(
        {
            "role": "user",
            "content": "injected filesystem path and file hint",
            "metadata": {
                QWENPAW_USER_CONTENT_KEY: [
                    {"type": "text", "text": "Summarize this report"},
                ],
            },
        },
    )
    assert item.text == "Summarize this report"
    item = visible_text(
        {
            "role": "user",
            "content": "Use this skill\n<skill>hidden instructions</skill>",
        },
    )
    assert item.text == "Use this skill"


async def test_literal_unicode_title_matching_and_stable_pagination(tmp_path):
    workspace = make_workspace(tmp_path)
    chats = [
        make_chat(str(i), name="Straße 100%_.*", minutes=i) for i in range(4)
    ]
    corpus = await load_search_corpus(workspace, chats)
    first = keyword_search(corpus, ChatSearchRequest(query="STRASSE", limit=2))
    second = keyword_search(
        corpus,
        ChatSearchRequest(query="100%_.*", limit=2, offset=2),
    )
    assert [item.chat.id for item in first.results] == ["3", "2"]
    assert first.total == 4 and first.has_more
    assert [item.chat.id for item in second.results] == ["1", "0"]
    assert not second.has_more
    assert corpus.search("^Stra") == []


async def test_durable_history_finds_evicted_and_imported_messages_with_scope(
    tmp_path,
):
    workspace = make_workspace(tmp_path)
    chat = make_chat()
    history = HistoryStore(tmp_path / "history.db")
    for session_id, agent_id, kind, text in [
        (chat.session_id, "agent-one", "context_msg", "old deadline Tuesday"),
        (chat.session_id, "agent-two", "context_msg", "other agent secret"),
        ("deleted-session", "agent-one", "context_msg", "deleted secret"),
        (chat.session_id, "agent-one", "tool_result", "tool secret"),
        (chat.session_id, "agent-one", "beam_chat_turn", "imported topic"),
    ]:
        history.append(
            session_id=session_id,
            entry=LogEntry(kind=kind, role="user", content=text),
            agent_id=agent_id,
        )
    history.close()
    corpus = await load_search_corpus(workspace, [chat])
    assert corpus.search("deadline")[0].snippet == "old deadline Tuesday"
    assert corpus.search("imported")[0].snippet == "imported topic"
    assert corpus.search("secret") == []
    assert not corpus.partial


@pytest.mark.parametrize("file_only", [False, True])
async def test_snapshot_message_identity_overrides_model_facing_history(
    tmp_path,
    file_only,
):
    workspace = make_workspace(tmp_path)
    chat = make_chat()
    write_snapshot(
        workspace,
        chat,
        [
            {
                "id": "same-message",
                "role": "user",
                "content": "private injected file hint",
                "metadata": {
                    QWENPAW_USER_CONTENT_KEY: [
                        (
                            {"type": "file", "filename": "report.txt"}
                            if file_only
                            else {"type": "text", "text": "visible request"}
                        ),
                    ],
                },
            },
        ],
    )
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id=chat.session_id,
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="private injected file hint",
        ),
        agent_id=workspace.agent_id,
        dedup_key="same-message",
    )
    history.close()
    corpus = await load_search_corpus(workspace, [chat])
    assert corpus.search("private") == []
    if not file_only:
        assert corpus.search("visible")[0].message_id == "same-message"


async def test_bad_or_oversized_snapshot_does_not_hide_other_matches(
    tmp_path,
    monkeypatch,
):
    workspace = make_workspace(tmp_path)
    bad, huge, good = [make_chat(name) for name in ("bad", "huge", "good")]
    path = write_snapshot(workspace, bad, [])
    path.write_text("{broken", encoding="utf-8")
    write_snapshot(workspace, huge, [{"role": "user", "content": "x" * 1000}])
    write_snapshot(workspace, good, [{"role": "user", "content": "find me"}])
    monkeypatch.setattr(search, "MAX_SESSION_BYTES", 500)
    corpus = await load_search_corpus(workspace, [bad, huge, good])
    assert corpus.partial
    assert [item.chat.id for item in corpus.search("find")] == [good.id]


async def test_history_size_limit_is_bytes_and_skips_media_before_fetch(
    tmp_path,
    monkeypatch,
):
    workspace = make_workspace(tmp_path)
    chat = make_chat()
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id=chat.session_id,
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="old match",
        ),
        agent_id=workspace.agent_id,
    )
    history.append(
        session_id=chat.session_id,
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="中" * 300,
        ),
        agent_id=workspace.agent_id,
    )
    history.close()
    monkeypatch.setattr(search, "MAX_SESSION_BYTES", 500)
    corpus = await load_search_corpus(workspace, [chat])
    assert corpus.partial
    assert corpus.search("中") == []
    assert corpus.search("old")[0].chat.id == chat.id


async def test_session_symlink_cannot_escape_agent_directory(tmp_path):
    workspace = make_workspace(tmp_path)
    chat = make_chat()
    path = write_snapshot(workspace, chat, [])
    external = tmp_path / "another-agent.json"
    external.write_text(
        json.dumps(
            {
                "agent": {
                    "state": {
                        "context": [
                            {"role": "user", "content": "outside secret"},
                        ],
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    path.unlink()
    path.symlink_to(external)
    corpus = await load_search_corpus(workspace, [chat])
    assert corpus.search("secret") == []


@pytest.mark.parametrize(
    "payload",
    [
        {"query": " "},
        {"query": "x" * 501},
        {"query": "x", "limit": 51},
        {"query": "x", "offset": -1},
        {"query": "x", "mode": "agent", "offset": 1},
    ],
)
def test_search_request_rejects_invalid_boundaries(payload):
    with pytest.raises(ValidationError):
        ChatSearchRequest(**payload)


def test_interrupted_history_scan_keeps_retrieved_matches(
    tmp_path,
    monkeypatch,
):
    chat = make_chat()
    corpus = search.SearchCorpus(chats=[chat])
    path = tmp_path / "history.db"
    path.touch()

    def rows():
        yield {
            "session_id": chat.session_id,
            "role": "user",
            "name": "user",
            "dedup_key": "old-message",
            "content": "retrieved before interruption",
            "blocks": None,
            "metadata": None,
            "row_bytes": 30,
        }
        raise sqlite3.OperationalError("interrupted")

    connection = SimpleNamespace(
        row_factory=None,
        set_progress_handler=lambda *_args: None,
        execute=lambda *_args: rows(),
        close=lambda: None,
    )
    monkeypatch.setattr(
        search.sqlite3,
        "connect",
        lambda *_args, **_kwargs: connection,
    )
    search._read_history(corpus, path, "agent-one", search._ScanBudget())
    assert corpus.partial
    assert corpus.search("retrieved")[0].message_id == "old-message"
