# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.chats.session``.

Covers:
- ``_safe_json_loads`` recovery from corrupted JSON
- ``sanitize_filename`` Windows-illegal-character replacement
- ``SafeJSONSession`` save / load / update / get round-trip
- ``SafeJSONSession`` cross-channel migration helper
- ``migrate_legacy_weixin_session_files`` weixin -> wechat rename
- ``AgentStateError`` raised for missing-file ``allow_not_exist=False``
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path

import pytest

import qwenpaw.app.chats.session as session_mod
from qwenpaw.app.chats.session import (
    DatabaseSession,
    SafeJSONSession,
    _safe_json_loads,
    migrate_legacy_weixin_session_files,
    sanitize_filename,
    session_filename,
    session_relative_paths,
)
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.exceptions import AgentStateError


class _StateModule:
    """Minimal state module compatible with SessionBase APIs."""

    def __init__(self, state: dict) -> None:
        self._state = dict(state)

    def state_dict(self) -> dict:
        return dict(self._state)

    def load_state_dict(self, state: dict) -> None:
        self._state = dict(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("repeat_user", ["", "session"])
async def test_json_migration_imports_recall_once(
    tmp_path: Path,
    repeat_user: str,
) -> None:
    """Legacy recall follows the JSON import and stable message identity."""
    legacy_dir = tmp_path / "sessions"
    legacy_dir.mkdir()
    state = {
        "agent": {
            "state": {
                "context": [
                    {
                        "id": "old-message",
                        "name": "user",
                        "role": "user",
                        "content": [{"type": "text", "text": "hello"}],
                    },
                ],
            },
        },
    }
    (legacy_dir / "session.json").write_text(
        json.dumps(state),
        encoding="utf-8",
    )
    harness_dir = tmp_path / "harnesses"
    harness_dir.mkdir()
    (harness_dir / "codex_sessions.json").write_text(
        json.dumps({"session": "native-thread-id"}),
        encoding="utf-8",
    )
    source = HistoryStore(tmp_path / "history.db")
    try:
        source.append(
            session_id="session",
            entry=LogEntry(kind="model_turn", content="hello"),
            dedup_key="old-message",
        )
        source.append(
            session_id="session",
            entry=LogEntry(kind="context_msg", content="unmatched"),
        )
    finally:
        source.close()

    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(legacy_dir),
    )
    try:
        await session.ensure_legacy_migrated(
            session_id="session",
            user_id="",
            channel="",
        )
        await session.ensure_legacy_migrated(
            session_id="session",
            user_id=repeat_user,
            channel="",
        )
        assert len(list((tmp_path / "transcripts").glob("*.db"))) == 1
        db_path = (
            tmp_path
            / "transcripts"
            / (
                catalog.storage_id_for(
                    session_id="session",
                    user_id="",
                    channel="",
                )
                + ".db"
            )
        )
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(
                "SELECT seq, turn_id FROM event_log "
                "WHERE event_type = 'recall.entry_committed' "
                "ORDER BY seq",
            ).fetchall()
            runtime_seq = connection.execute(
                "SELECT seq FROM event_log "
                "WHERE event_type = 'runtime.committed' "
                "ORDER BY seq DESC LIMIT 1",
            ).fetchone()[0]
        assert [row[1] for row in rows] == ["legacy:1", None]
        assert rows[-1][0] < runtime_seq
        provider = catalog.read_provider_state(
            session_id="session",
            user_id="",
            channel="",
        )
        assert provider["binding"] == {
            "provider": "codex",
            "external_session_id": "native-thread-id",
        }
        assert provider["boundaries"] == {}
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_database_session_imports_json_once_and_resets_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_dir = tmp_path / "sessions"
    legacy_dir.mkdir()
    legacy_path = legacy_dir / "u_session-1.json"
    legacy_path.write_text(
        json.dumps(
            {
                "agent": {
                    "state": {
                        "context": [
                            {
                                "name": "assistant",
                                "role": "assistant",
                                "content": [
                                    {"type": "text", "text": "hello"},
                                ],
                                "metadata": {
                                    "qwenpaw_turn_usage": {
                                        "usage": {"total_tokens": 4},
                                        "context_usage": {
                                            "estimated_tokens": 2,
                                            "max_input_length": 100,
                                            "context_usage_ratio": 2,
                                        },
                                    },
                                },
                            },
                        ],
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(legacy_dir),
    )
    import_count = 0
    import_legacy = session._migrate_legacy_snapshot

    async def track_import(
        *,
        session_id: str,
        user_id: str,
        channel: str,
        snapshot,
    ) -> bool:
        nonlocal import_count
        import_count += 1
        return await import_legacy(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            snapshot=snapshot,
        )

    monkeypatch.setattr(session, "_migrate_legacy_snapshot", track_import)

    state = await session.get_session_state_dict(
        "session-1",
        "u",
        "console",
    )
    assert state["_context_generation"] == 0
    assert legacy_path.exists()
    legacy_state = await SafeJSONSession(
        save_dir=str(legacy_dir),
    ).get_session_state_dict("session-1", "u")
    assert legacy_state == {"agent": state["agent"]}
    await session.get_session_state_dict("session-1", "u", "console")
    assert import_count == 1
    _, migrated_usage = await session.get_current_usage(
        session_id="session-1",
        user_id="u",
        channel="console",
    )
    assert migrated_usage == {
        "usage": {"total_tokens": 4},
        "context_usage": {
            "estimated_tokens": 2,
            "max_input_length": 100,
            "context_usage_ratio": 2,
        },
    }
    anchor = catalog.read_turn_context(
        session_id="session-1",
        user_id="u",
        channel="console",
        turn_id="legacy:1",
    )
    assert anchor is not None
    assert anchor.state == {"agent": state["agent"]}

    await session.set_current_usage(
        session_id="session-1",
        user_id="u",
        channel="console",
        usage={"total_tokens": 5},
        context_usage={
            "estimated_tokens": 3,
            "max_input_length": 100,
            "context_usage_ratio": 3,
        },
    )
    generation = await session.reset_session_state(
        "session-1",
        "u",
        "console",
        agent=_StateModule({"state": {"context": []}}),
    )
    restored = await session.get_session_state_dict(
        "session-1",
        "u",
        "console",
    )
    current_generation, current_usage = await session.get_current_usage(
        session_id="session-1",
        user_id="u",
        channel="console",
    )

    assert generation == 1
    assert restored["_context_generation"] == 1
    assert current_generation == 1
    assert current_usage == {
        "usage": None,
        "context_usage": {
            "estimated_tokens": 0,
            "max_input_length": 100,
            "context_usage_ratio": 0,
        },
    }
    loaded = _StateModule({})
    await session.load_session_state(
        "session-1",
        "u",
        "console",
        agent=loaded,
    )
    assert loaded._state["_context_generation"] == 1
    catalog.close()


# ---------------------------------------------------------------------------
# _safe_json_loads
# ---------------------------------------------------------------------------


def test_safe_json_loads_valid_json():
    assert _safe_json_loads('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_safe_json_loads_recovers_trailing_garbage():
    # A common concurrent-write artefact: a complete object followed by
    # an unrelated tail.  ``raw_decode`` should pull out the first object.
    content = '{"k": "v"}garbage'

    assert _safe_json_loads(content) == {"k": "v"}


def test_safe_json_loads_recovers_leading_whitespace_and_trailing_garbage():
    # Pretty-printed or hand-edited files may include whitespace before the
    # recoverable object while still retaining unrelated trailing bytes.
    content = '\n  {"k": "v"}garbage'

    assert _safe_json_loads(content) == {"k": "v"}


def test_safe_json_loads_completely_corrupted_returns_empty_dict():
    # Contract: unparseable content returns {} rather than raising. The
    # function also logs a warning, but the warning message is an
    # implementation detail not worth asserting against.
    assert _safe_json_loads("this is not json", filepath="bad.json") == {}


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("normal-name", "normal-name"),
        ("discord:dm:12345", "discord--dm--12345"),
        # Each unsafe character (\\, /, :, *, ?, ", <, >, |) is replaced.
        ('a/b\\c:d*e?f"g<h>i|j', "a--b--c--d--e--f--g--h--i--j"),
        # Safe characters are preserved.
        ("user_42@host", "user_42@host"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


# ---------------------------------------------------------------------------
# SafeJSONSession — save / load round-trip
# ---------------------------------------------------------------------------


@pytest.fixture
def session(tmp_path: Path) -> SafeJSONSession:
    return SafeJSONSession(save_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_save_and_load_round_trip(session, tmp_path: Path):
    state = _StateModule({"value": 7})

    await session.save_session_state(
        session_id="sess-1",
        user_id="user-1",
        agent=state,
    )

    target = tmp_path / "user-1_sess-1.json"
    assert target.exists(), "session file should be written"
    saved = json.loads(target.read_text("utf-8"))
    assert saved == {"agent": {"value": 7}}

    restored = _StateModule({})
    await session.load_session_state(
        session_id="sess-1",
        user_id="user-1",
        agent=restored,
    )
    assert restored.state_dict() == {"value": 7}


@pytest.mark.asyncio
async def test_load_missing_session_allow_not_exist(session):
    state = _StateModule({"untouched": True})

    # Should NOT raise — and should leave the state untouched.
    await session.load_session_state(
        session_id="missing",
        user_id="u",
        agent=state,
        allow_not_exist=True,
    )
    assert state.state_dict() == {"untouched": True}


@pytest.mark.asyncio
async def test_database_session_imports_legacy_before_partial_update(
    tmp_path: Path,
) -> None:
    legacy_dir = tmp_path / "sessions"
    legacy_dir.mkdir()
    legacy_path = legacy_dir / session_filename("pawapp--example", "")
    legacy_path.write_text(
        json.dumps({"existing_setting": "must survive"}),
        encoding="utf-8",
    )
    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(legacy_dir),
    )

    await session.update_session_state(
        session_id="pawapp--example",
        key="new_setting",
        value="new",
    )

    state = await session.get_session_state_dict("pawapp--example")
    assert state["existing_setting"] == "must survive"
    assert state["new_setting"] == "new"
    assert json.loads(legacy_path.read_text(encoding="utf-8")) == {
        "existing_setting": "must survive",
    }
    catalog.close()


@pytest.mark.asyncio
async def test_concurrent_legacy_imports_return_the_same_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_dir = tmp_path / "sessions"
    legacy_dir.mkdir()
    legacy_path = legacy_dir / session_filename("session-1", "u")
    legacy_path.write_text(
        json.dumps({"agent": {"marker": "persisted-context"}}),
        encoding="utf-8",
    )
    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(legacy_dir),
    )
    original_read = catalog.read_runtime_state
    first_reads = 0
    first_reads_lock = threading.Lock()
    first_reads_ready = threading.Barrier(2)

    def synchronized_read(
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ):
        nonlocal first_reads
        snapshot = original_read(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        should_wait = False
        if snapshot is None:
            with first_reads_lock:
                if first_reads < 2:
                    first_reads += 1
                    should_wait = True
        if should_wait:
            first_reads_ready.wait(timeout=5)
        return snapshot

    monkeypatch.setattr(catalog, "read_runtime_state", synchronized_read)
    results = await asyncio.gather(
        session.get_session_state_dict("session-1", "u", "console"),
        session.get_session_state_dict("session-1", "u", "console"),
    )

    expected = {
        "agent": {"marker": "persisted-context"},
        "_context_generation": 0,
    }
    assert results == [expected, expected]
    catalog.close()


@pytest.mark.asyncio
async def test_delete_waits_for_migration_and_removes_both_legacy_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_dir = tmp_path / "sessions"
    legacy_dir.mkdir()
    filename = session_filename("session-1", "u")
    root_path = legacy_dir / filename
    root_path.write_text(json.dumps({"agent": {"marker": "private"}}))
    channel_path = Path(
        SafeJSONSession(str(legacy_dir))._get_save_path(
            "session-1",
            "u",
            "console",
        ),
    )
    assert root_path.exists() and channel_path.exists()

    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(legacy_dir),
    )
    snapshot = await session.get_legacy_snapshot(
        session_id="session-1",
        user_id="u",
        channel="console",
    )
    assert snapshot is not None
    started = asyncio.Event()
    resume = asyncio.Event()
    migrate = session._migrate_legacy_snapshot

    async def paused_migration(**kwargs):
        started.set()
        await resume.wait()
        return await migrate(**kwargs)

    monkeypatch.setattr(session, "_migrate_legacy_snapshot", paused_migration)
    migration = asyncio.create_task(
        session.start_legacy_migration(
            session_id="session-1",
            user_id="u",
            channel="console",
            snapshot=snapshot,
            wait_for_projection=True,
        ),
    )
    await started.wait()
    deletion = asyncio.create_task(
        session.delete_session_state("session-1", "u", "console"),
    )
    await asyncio.sleep(0)
    assert not deletion.done()
    resume.set()
    await migration
    assert await deletion
    assert not root_path.exists() and not channel_path.exists()
    assert not catalog.has_session(
        session_id="session-1",
        user_id="u",
        channel="console",
    )
    assert (
        await session.get_legacy_snapshot(
            session_id="session-1",
            user_id="u",
            channel="console",
        )
        is None
    )
    assert not await session.start_legacy_migration(
        session_id="session-1",
        user_id="u",
        channel="console",
        snapshot=snapshot,
    )
    catalog.close()


@pytest.mark.asyncio
async def test_delete_keeps_root_legacy_used_by_another_channel(
    tmp_path: Path,
) -> None:
    legacy_dir = tmp_path / "sessions"
    legacy_dir.mkdir()
    root_path = legacy_dir / session_filename("session-1", "u")
    root_path.write_text(json.dumps({"agent": {"marker": "shared"}}))
    (tmp_path / "chats.json").write_text(
        json.dumps(
            {
                "chats": [
                    {
                        "session_id": "session-1",
                        "user_id": "u",
                        "channel": channel,
                    }
                    for channel in ("console", "feishu")
                ],
            },
        ),
    )
    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(legacy_dir),
    )

    await session.delete_session_state("session-1", "u", "console")

    assert root_path.exists()
    snapshot = await session.get_legacy_snapshot(
        session_id="session-1",
        user_id="u",
        channel="feishu",
    )
    assert snapshot is not None
    assert snapshot.state["agent"]["marker"] == "shared"
    for channel in ("console", "feishu"):
        await session.delete_session_state(
            "session-1",
            "u",
            channel,
            deleting_channels=("console", "feishu"),
        )
    assert not root_path.exists()
    restarted = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(legacy_dir),
    )
    assert (
        await restarted.get_legacy_snapshot(
            session_id="session-1",
            user_id="u",
            channel="console",
        )
        is None
    )
    catalog.close()


@pytest.mark.asyncio
async def test_legacy_path_probe_runs_off_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(tmp_path / "sessions"),
    )
    loop_thread = threading.get_ident()
    probe_threads: list[int] = []
    original_exists = Path.exists

    def tracked_exists(path: Path) -> bool:
        if path.name == "u_missing.json":
            probe_threads.append(threading.get_ident())
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", tracked_exists)
    state = await session.get_session_state_dict(
        "missing",
        "u",
        "console",
    )

    assert state == {}
    assert probe_threads
    assert all(thread_id != loop_thread for thread_id in probe_threads)
    catalog.close()


@pytest.mark.asyncio
async def test_get_current_usage_does_not_decode_runtime_state(
    tmp_path: Path,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    catalog.write_runtime_state(
        session_id="session-1",
        user_id="u",
        channel="console",
        state={"agent": {"state": {"context": ["large state"]}}},
    )
    catalog.set_current_usage(
        session_id="session-1",
        usage={"total_tokens": 42},
        context_usage={"estimated_tokens": 21},
    )
    row = catalog._catalog_row(
        session_id="session-1",
        user_id="u",
        channel="console",
    )
    assert row is not None
    database_path = catalog._store_path(str(row["storage_id"]))
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE session_runtime SET state_json = ? "
            "WHERE session_id = ?",
            ("invalid runtime state", "session-1"),
        )

    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(tmp_path / "sessions"),
    )
    generation, usage = await session.get_current_usage(
        session_id="session-1",
        user_id="u",
        channel="console",
    )

    assert generation == 0
    assert usage == {
        "usage": {"total_tokens": 42},
        "context_usage": {"estimated_tokens": 21},
    }
    catalog.close()


@pytest.mark.asyncio
async def test_load_missing_session_raises_when_not_allowed(session):
    with pytest.raises(AgentStateError):
        await session.load_session_state(
            session_id="missing",
            user_id="u",
            allow_not_exist=False,
            agent=_StateModule({}),
        )


# ---------------------------------------------------------------------------
# update_session_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_session_state_creates_file(session, tmp_path: Path):
    await session.update_session_state(
        session_id="sess-2",
        key="agent.memory.x",
        value=[1, 2, 3],
        user_id="u",
    )

    saved = json.loads((tmp_path / "u_sess-2.json").read_text("utf-8"))
    assert saved == {"agent": {"memory": {"x": [1, 2, 3]}}}


@pytest.mark.asyncio
async def test_update_session_state_appends_to_existing(
    session,
    tmp_path: Path,
):
    path = tmp_path / "u_sess-3.json"
    path.write_text(
        json.dumps({"agent": {"memory": {"x": "old"}, "other": 1}}),
        encoding="utf-8",
    )

    await session.update_session_state(
        session_id="sess-3",
        key=("agent", "memory", "x"),
        value="new",
        user_id="u",
    )

    saved = json.loads(path.read_text("utf-8"))
    assert saved == {"agent": {"memory": {"x": "new"}, "other": 1}}


@pytest.mark.asyncio
async def test_update_session_state_serializes_across_instances(
    tmp_path: Path,
    monkeypatch,
):
    """Two session objects must not lose updates to the same file."""
    first_session = SafeJSONSession(save_dir=str(tmp_path))
    second_session = SafeJSONSession(save_dir=str(tmp_path))
    first_write_started = asyncio.Event()
    release_first_write = asyncio.Event()
    original_write = session_mod.write_json_atomic_async

    async def delayed_write(path, payload, **kwargs):
        if payload == {"first": 1}:
            first_write_started.set()
            await release_first_write.wait()
        await original_write(path, payload, **kwargs)

    monkeypatch.setattr(
        session_mod,
        "write_json_atomic_async",
        delayed_write,
    )

    first_update = asyncio.create_task(
        first_session.update_session_state(
            session_id="shared",
            key="first",
            value=1,
            user_id="u",
        ),
    )
    await first_write_started.wait()
    second_update = asyncio.create_task(
        second_session.update_session_state(
            session_id="shared",
            key="second",
            value=2,
            user_id="u",
        ),
    )
    await asyncio.sleep(0.05)
    release_first_write.set()
    await asyncio.gather(first_update, second_update)

    saved = json.loads(
        (tmp_path / "u_shared.json").read_text(encoding="utf-8"),
    )
    assert saved == {"first": 1, "second": 2}


@pytest.mark.asyncio
async def test_update_session_state_missing_file_disallowed(session):
    with pytest.raises(AgentStateError):
        await session.update_session_state(
            session_id="ghost",
            key="agent.x",
            value=1,
            user_id="u",
            create_if_not_exist=False,
        )


@pytest.mark.asyncio
async def test_update_session_state_empty_key_path_rejected(session, tmp_path):
    # Empty sequence ``key`` triggers the "key path is empty" guard.
    # Create the file so the empty-key check runs *after* the file-exists
    # branch (the guard is reached either way, but we keep the path
    # exercise deterministic).
    (tmp_path / "u_sess-4.json").write_text("{}", encoding="utf-8")

    from qwenpaw.exceptions import ConfigurationException

    with pytest.raises(ConfigurationException):
        await session.update_session_state(
            session_id="sess-4",
            key=[],  # empty path
            value="anything",
            user_id="u",
        )


# ---------------------------------------------------------------------------
# get_session_state_dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_state_dict_empty_when_missing(session):
    result = await session.get_session_state_dict(
        session_id="nope",
        user_id="u",
    )

    assert result == {}


@pytest.mark.asyncio
async def test_get_session_state_dict_raises_when_required(session):
    with pytest.raises(AgentStateError):
        await session.get_session_state_dict(
            session_id="nope",
            user_id="u",
            allow_not_exist=False,
        )


@pytest.mark.asyncio
async def test_get_session_state_dict_recovers_from_corruption(
    session,
    tmp_path: Path,
):
    # File contains a recoverable object followed by trailing garbage.
    (tmp_path / "u_sess-5.json").write_text(
        '{"agent": {"a": 1}}garbage',
        encoding="utf-8",
    )

    result = await session.get_session_state_dict(
        session_id="sess-5",
        user_id="u",
    )

    assert result == {"agent": {"a": 1}}


# ---------------------------------------------------------------------------
# Channel sub-directory + cross-channel migration
# ---------------------------------------------------------------------------


def test_get_save_path_uses_channel_subdir(session, tmp_path: Path):
    path = session._get_save_path(
        session_id="sess",
        user_id="u",
        channel="console",
    )

    assert Path(path) == tmp_path / "console" / "u_sess.json"
    assert (tmp_path / "console").is_dir()


def test_session_path_helpers_match_save_layout():
    assert session_filename("console:sid", "user") == "user_console--sid.json"
    assert session_relative_paths(
        "console:sid",
        "user",
        "console",
    ) == {
        "user_console--sid.json",
        "console/user_console--sid.json",
    }


def test_session_path_helpers_reject_parent_channel(session):
    with pytest.raises(ValueError, match="invalid session channel"):
        session_relative_paths("sid", "user", "..")
    with pytest.raises(ValueError, match="invalid session channel"):
        session._get_save_path("sid", "user", "..")


def test_get_save_path_migrates_legacy_session_into_channel(
    session,
    tmp_path: Path,
):
    legacy = tmp_path / "u_old-sess.json"
    legacy.write_text('{"legacy": true}', encoding="utf-8")

    path = session._get_save_path(
        session_id="old-sess",
        user_id="u",
        channel="discord",
    )

    target = tmp_path / "discord" / "u_old-sess.json"
    assert Path(path) == target
    assert target.exists(), "legacy session should be copied into channel dir"
    assert json.loads(target.read_text("utf-8")) == {"legacy": True}


# ---------------------------------------------------------------------------
# migrate_legacy_weixin_session_files
# ---------------------------------------------------------------------------


def test_migrate_legacy_weixin_session_files_renames_and_archives(
    tmp_path: Path,
):
    # ``user_42_weixin--sid@im.wechat.json`` is the legacy form.
    legacy_name = "user_42_weixin--sid@im.wechat.json"
    canonical_name = "user_42_wechat--sid@im.wechat.json"
    (tmp_path / legacy_name).write_text('{"v": 1}', encoding="utf-8")

    migrate_legacy_weixin_session_files(str(tmp_path))

    assert (tmp_path / canonical_name).exists()
    archive = tmp_path / ".weixin-legacy" / legacy_name
    assert archive.exists(), "original legacy file should be archived"
    # Live file should NOT remain at the legacy path.
    assert not (tmp_path / legacy_name).exists()


def test_migrate_legacy_weixin_session_files_archives_only_when_present(
    tmp_path: Path,
):
    legacy_name = "u_weixin--sid.json"
    canonical_name = "u_wechat--sid.json"
    legacy = tmp_path / legacy_name
    legacy.write_text('{"legacy": true}', encoding="utf-8")
    # Canonical already exists with different content — must stay intact.
    (tmp_path / canonical_name).write_text(
        '{"live": true}',
        encoding="utf-8",
    )

    migrate_legacy_weixin_session_files(str(tmp_path))

    canonical = json.loads(
        (tmp_path / canonical_name).read_text("utf-8"),
    )
    assert canonical == {
        "live": True,
    }, "live canonical file must not be overwritten"
    assert (tmp_path / ".weixin-legacy" / legacy_name).exists()
    assert not legacy.exists()


def test_migrate_legacy_weixin_session_files_noop_on_missing_dir():
    # Must not raise when the directory does not exist.
    migrate_legacy_weixin_session_files("/path/that/does/not/exist/xyz")


def test_migrate_legacy_weixin_session_files_noop_when_no_legacy(
    tmp_path: Path,
):
    (tmp_path / "u_wechat--sid.json").write_text("{}", encoding="utf-8")

    migrate_legacy_weixin_session_files(str(tmp_path))

    # No archive dir created when there is nothing to migrate.
    assert not (tmp_path / ".weixin-legacy").exists()


# ---------------------------------------------------------------------------
# Module exports — defensive check for the migration constant.
# ---------------------------------------------------------------------------


def test_archive_dir_constant_excluded_from_session_scans():
    # Callers list ``*.json`` non-recursively; the archive dir lives one
    # level down so it must not start with a dot-stripped name that
    # collides with session files.
    assert session_mod._WEIXIN_LEGACY_ARCHIVE_DIR.startswith(".")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["runtime", "binding"])
async def test_interrupted_compressed_migration_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Resume partial import without losing compacted state or turn anchors."""
    legacy_dir = tmp_path / "sessions"
    legacy_dir.mkdir()
    history = HistoryStore(tmp_path / "history.db")
    messages = []
    for index in range(1, 6):
        message = {
            "id": f"message-{index}",
            "role": "user",
            "name": "user",
            "content": [{"type": "text", "text": f"turn {index}"}],
        }
        messages.append(message)
        history.append(
            session_id="session",
            entry=LogEntry(
                kind="context_msg",
                role="user",
                content=f"turn {index}",
                blocks=message["content"],
            ),
            dedup_key=message["id"],
        )
    history.close()
    state = {
        "agent": {
            "state": {"context": messages[-2:]},
            "scroll": {
                "continuation_summary": "summary of turns 1 to 3",
                "index": {"tiers": [[{"seq_hi": 3}]]},
            },
        },
    }
    (legacy_dir / "session.json").write_text(
        json.dumps(state),
        encoding="utf-8",
    )
    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(catalog=catalog, legacy_save_dir=str(legacy_dir))
    original_write = catalog.write_runtime_state
    original_binding = session._import_legacy_provider_binding

    def interrupted_write(**kwargs):
        if failure == "runtime" and kwargs.get("turn_id") == "legacy:2":
            raise RuntimeError("interrupted runtime")
        return original_write(**kwargs)

    def interrupted_binding(**kwargs):
        if failure == "binding":
            raise RuntimeError("interrupted binding")
        return original_binding(**kwargs)

    monkeypatch.setattr(catalog, "write_runtime_state", interrupted_write)
    monkeypatch.setattr(
        session,
        "_import_legacy_provider_binding",
        interrupted_binding,
    )
    identity = dict(session_id="session", user_id="", channel="")
    try:
        with pytest.raises(session_mod.LegacyMigrationError):
            await session.ensure_legacy_migrated(**identity)
        assert not session._migration_complete(**identity)
        first = catalog.read_turn_context(**identity, turn_id="legacy:1")
        assert first is not None
        monkeypatch.setattr(catalog, "write_runtime_state", original_write)
        session = DatabaseSession(
            catalog=catalog,
            legacy_save_dir=str(legacy_dir),
        )
        restored = await session.get_session_state_dict(**identity)
        assert restored == {**state, "_context_generation": 0}
        assert session._migration_complete(**identity)
        assert (
            catalog.read_turn_context(
                **identity,
                turn_id="legacy:1",
            )
            == first
        )
        for index in range(1, 6):
            assert (
                catalog.read_turn_context(
                    **identity,
                    turn_id=f"legacy:{index}",
                )
                is not None
            )
        assert not await session.ensure_legacy_migrated(**identity)
        page = catalog.get_page(**identity)
        assert page is not None
        assert len(page.messages) == 5
        catalog.write_runtime_state(**identity, state={"continued": True})
        assert not await session.start_legacy_migration(**identity)
        assert await session.get_session_state_dict(**identity) == {
            "continued": True,
            "_context_generation": 0,
        }
    finally:
        catalog.close()
