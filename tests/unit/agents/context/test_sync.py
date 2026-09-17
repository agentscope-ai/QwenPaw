# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Unit tests for the ``sessions/*.json`` → ``history.db`` startup sync.

Pins the rollout-critical guarantees: non-destructive (source files untouched),
idempotent (re-runs and the DB UNIQUE index insert nothing new), faithful (rows
land under the registered canonical ``session_id`` and match the live writer),
and robust (empty dir / corrupt file never raise).
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolResultBlock

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll import sync as sync_mod
from qwenpaw.agents.context.scroll.sync import (
    MANIFEST_NAME,
    sync_all_scroll_agents,
    sync_sessions_to_history,
)
from qwenpaw.agents.context.types import LogEntry


def _sample_msgs() -> list[Msg]:
    return [
        Msg(
            name="u",
            role="user",
            content=[TextBlock(type="text", text="please do X")],
        ),
        Msg(
            name="a",
            role="assistant",
            content=[
                TextBlock(type="text", text="working\n⟦ did the work ⟧"),
                ToolCallBlock(
                    type="tool_call",
                    id="c1",
                    name="grep",
                    input="{}",
                ),
                ToolResultBlock(
                    type="tool_result",
                    id="c1",
                    name="grep",
                    output=[TextBlock(type="text", text="found it")],
                ),
            ],
        ),
    ]


def _write_session_2x(
    sessions_dir: Path,
    filename: str,
    session_id: str,
    msgs: list[Msg],
) -> Path:
    """Write a 2.0-format SafeJSONSession file: {"agent": {"state": {...}}}."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / filename
    state = {
        "session_id": session_id,
        "summary": "",
        "context": [m.to_dict() for m in msgs],
    }
    path.write_text(
        json.dumps({"agent": {"state": state}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _write_session_1x(
    sessions_dir: Path,
    filename: str,
    msgs: list[Msg],
) -> Path:
    """Write a 1.x legacy SafeJSONSession file (agent.memory format)."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / filename
    memory = {
        "content": [[m.to_dict(), []] for m in msgs],
        "_compressed_summary": "",
    }
    path.write_text(
        json.dumps({"agent": {"memory": memory}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _write_chats(path: Path, chats: list[dict]) -> Path:
    path.write_text(
        json.dumps({"version": 1, "chats": chats}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _chat(session_id: str, *, channel: str = "", user_id: str = "") -> dict:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "channel": channel,
    }


def _sync_registered(
    history: HistoryStore,
    sessions_dir: Path,
    chats: list[dict],
    **kwargs,
):
    chats_path = _write_chats(sessions_dir.parent / "chats.json", chats)
    return sync_sessions_to_history(
        history=history,
        sessions_dir=sessions_dir,
        chats_path=chats_path,
        **kwargs,
    )


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    h = HistoryStore(tmp_path / "history.db")
    yield h
    h.close()


def test_syncs_session_under_registered_id(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(
        sessions,
        "canonical-sid.json",
        "internal-state-id",
        _sample_msgs(),
    )
    report = _sync_registered(store, sessions, [_chat("canonical-sid")])
    assert report.rows_inserted > 0
    assert report.sessions == 1
    assert store.count("canonical-sid") == report.rows_inserted
    assert store.count("internal-state-id") == 0
    # Faithful: the tool result is recallable by its call id.
    rows = store._conn.execute(
        "SELECT content FROM conversation_history "
        "WHERE tool_call_id='c1' AND kind='tool_result'",
    ).fetchall()
    assert rows and rows[0]["content"] == "found it"


def test_legacy_1x_session_requires_registered_id(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_1x(sessions, "old.json", _sample_msgs())
    report = _sync_registered(store, sessions, [_chat("old")])
    assert report.rows_inserted > 0
    assert store.count("old") == report.rows_inserted


def test_legacy_1x_session_uses_canonical_id_from_chat_registry(
    store,
    tmp_path: Path,
):
    sessions = tmp_path / "sessions"
    _write_session_1x(
        sessions / "console",
        "default_legacy-session.json",
        _sample_msgs(),
    )
    chats = _write_chats(
        tmp_path / "chats.json",
        [
            {
                "session_id": "legacy-session",
                "user_id": "default",
                "channel": "console",
            },
        ],
    )

    report = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        chats_path=chats,
    )

    assert report.rows_inserted > 0
    assert store.count("legacy-session") == report.rows_inserted
    assert store.count("sync:default_legacy-session") == 0


def test_chat_registry_overrides_internal_2x_agent_state_id(
    store,
    tmp_path: Path,
):
    sessions = tmp_path / "sessions"
    _write_session_2x(
        sessions / "console",
        "default_request-session.json",
        "internal-agent-state-id",
        _sample_msgs(),
    )
    chats = _write_chats(
        tmp_path / "chats.json",
        [
            {
                "session_id": "request-session",
                "user_id": "default",
                "channel": "console",
            },
        ],
    )

    sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        chats_path=chats,
    )

    assert store.count("request-session") > 0
    assert store.count("internal-agent-state-id") == 0


def test_existing_synthetic_manifest_is_rekeyed_to_canonical_session(
    store,
    tmp_path: Path,
):
    sessions = tmp_path / "sessions"
    path = _write_session_1x(
        sessions / "console",
        "default_legacy-session.json",
        _sample_msgs(),
    )
    first = sync_mod._sync_file(
        store,
        path,
        "console/default_legacy-session.json",
        agent_id=None,
        dry_run=False,
        session_id="sync:default_legacy-session",
    )
    assert first.rows_inserted > 0
    sync_mod._save_manifest(
        sessions / MANIFEST_NAME,
        {
            "version": 1,
            "files": {
                "console/default_legacy-session.json": {
                    "sha256": sync_mod._sha256(path),
                    "session_id": "sync:default_legacy-session",
                    "messages": first.messages,
                    "aged_out": first.aged_out,
                    "rows_processed": first.rows_processed,
                    "rows_inserted": first.rows_inserted,
                },
            },
        },
    )
    source_before = store._conn.execute(
        "SELECT seq FROM conversation_history "
        "WHERE session_id='sync:default_legacy-session' ORDER BY seq",
    ).fetchall()
    source_seqs = [row["seq"] for row in source_before]

    chats = _write_chats(
        tmp_path / "chats.json",
        [
            {
                "session_id": "legacy-session",
                "user_id": "default",
                "channel": "console",
            },
        ],
    )
    second = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        chats_path=chats,
    )

    assert second.rows_inserted == 0
    # A v1 manifest is deliberately re-read once under manifest v2 so the
    # source can be imported under the canonical registry ID.
    assert not any(result.skipped for result in second.files)
    assert store.count("sync:default_legacy-session") == 0
    after = store._conn.execute(
        "SELECT seq FROM conversation_history "
        "WHERE session_id='legacy-session' ORDER BY seq",
    ).fetchall()
    canonical_seqs = [row["seq"] for row in after]
    assert canonical_seqs == source_seqs
    manifest = json.loads(
        (sessions / MANIFEST_NAME).read_text(encoding="utf-8"),
    )
    assert (
        manifest["files"]["console/default_legacy-session.json"]["session_id"]
        == "legacy-session"
    )
    assert manifest["version"] == 2


def test_changed_synthetic_manifest_rekeys_then_adds_new_history(
    store,
    tmp_path: Path,
):
    sessions = tmp_path / "sessions"
    rel_name = "console/default_changed-session.json"
    messages = _sample_msgs()
    path = _write_session_1x(
        sessions / "console",
        "default_changed-session.json",
        messages,
    )
    first = sync_mod._sync_file(
        store,
        path,
        rel_name,
        agent_id=None,
        dry_run=False,
        session_id="sync:default_changed-session",
    )
    sync_mod._save_manifest(
        sessions / MANIFEST_NAME,
        {
            "version": 1,
            "files": {
                rel_name: {
                    "sha256": sync_mod._sha256(path),
                    "session_id": "sync:default_changed-session",
                    "messages": first.messages,
                    "aged_out": first.aged_out,
                    "rows_processed": first.rows_processed,
                    "rows_inserted": first.rows_inserted,
                },
            },
        },
    )
    original_seqs = {
        row["seq"]
        for row in store._conn.execute(
            "SELECT seq FROM conversation_history "
            "WHERE session_id='sync:default_changed-session'",
        )
    }

    messages.append(
        Msg(
            name="u",
            role="user",
            content=[TextBlock(type="text", text="new message")],
        ),
    )
    _write_session_1x(
        sessions / "console",
        "default_changed-session.json",
        messages,
    )
    chats = _write_chats(
        tmp_path / "chats.json",
        [
            {
                "session_id": "changed-session",
                "user_id": "default",
                "channel": "console",
            },
        ],
    )

    second = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        chats_path=chats,
    )

    assert second.rows_inserted == 1
    assert store.count("sync:default_changed-session") == 0
    canonical_seqs = {
        row["seq"]
        for row in store._conn.execute(
            "SELECT seq FROM conversation_history "
            "WHERE session_id='changed-session'",
        )
    }
    assert len(canonical_seqs) == first.rows_inserted + 1
    assert original_seqs.issubset(canonical_seqs)


def test_ambiguous_chat_filename_is_reported_as_orphan(
    store,
    tmp_path: Path,
):
    sessions = tmp_path / "sessions"
    _write_session_1x(sessions, "default_a--b.json", _sample_msgs())
    chats = _write_chats(
        tmp_path / "chats.json",
        [
            {"session_id": "a:b", "user_id": "default", "channel": ""},
            {"session_id": "a?b", "user_id": "default", "channel": ""},
        ],
    )

    report = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        chats_path=chats,
    )

    assert report.orphaned_files == 1
    assert report.rows_inserted == 0
    assert report.files[0].orphaned
    assert store.count("sync:default_a--b") == 0
    assert store.count("a:b") == 0
    assert store.count("a?b") == 0


def test_empty_registry_blocks_legacy_sessions_explicitly(
    store,
    tmp_path: Path,
    caplog,
):
    sessions = tmp_path / "sessions"
    _write_session_2x(
        sessions / "console",
        "default_deleted-session.json",
        "internal-agent-state-id",
        _sample_msgs(),
    )
    _write_session_1x(sessions, "legacy-orphan.json", _sample_msgs())
    chats = _write_chats(tmp_path / "chats.json", [])

    with caplog.at_level(logging.ERROR, logger=sync_mod.logger.name):
        report = sync_sessions_to_history(
            history=store,
            sessions_dir=sessions,
            chats_path=chats,
        )

    assert report.registry_error
    assert report.orphaned_files == 0
    assert report.synced_files == 0
    assert report.rows_inserted == 0
    assert "migration blocked" in report.summary()
    assert "2 session file(s) left untouched" in report.summary()
    assert all(result.blocked for result in report.files)
    assert store.count("internal-agent-state-id") == 0
    assert not (sessions / MANIFEST_NAME).exists()
    blocked_errors = [
        record
        for record in caplog.records
        if "migration was not performed" in record.getMessage()
    ]
    assert len(blocked_errors) == 1
    assert "found 2 legacy session file(s)" in blocked_errors[0].getMessage()


def test_sync_is_idempotent_via_manifest(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "sid.json", "sid", _sample_msgs())
    _sync_registered(store, sessions, [_chat("sid")])
    total = store.count("sid")
    assert (sessions / MANIFEST_NAME).exists()

    second = _sync_registered(store, sessions, [_chat("sid")])
    assert second.rows_inserted == 0
    assert all(f.skipped for f in second.files)
    assert store.count("sid") == total


def test_manifest_skip_self_heals_when_db_was_reset(tmp_path: Path):
    """A surviving manifest must NOT skip a session missing from a fresh DB.

    Simulates HistoryStore quarantine/recovery: the manifest in sessions/ lives
    on, but history.db is recreated empty. The verified skip must re-sync.
    """
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "sid.json", "sid", _sample_msgs())

    db_path = tmp_path / "history.db"
    h1 = HistoryStore(db_path)
    try:
        _sync_registered(h1, sessions, [_chat("sid")])
        assert h1.count("sid") > 0
        assert (sessions / MANIFEST_NAME).exists()  # manifest claims synced
    finally:
        h1.close()

    # DB reset (corruption recovery / manual delete); manifest is untouched.
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()

    h2 = HistoryStore(db_path)  # fresh, empty
    try:
        assert h2.count("sid") == 0
        report = _sync_registered(h2, sessions, [_chat("sid")])
        # Verified skip detected the empty session and re-synced it.
        assert report.rows_inserted > 0
        assert h2.count("sid") > 0
    finally:
        h2.close()


def test_idempotent_even_without_manifest(store, tmp_path: Path):
    """Without the manifest, the DB UNIQUE index still blocks duplicates."""
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "sid.json", "sid", _sample_msgs())
    _sync_registered(
        store,
        sessions,
        [_chat("sid")],
        use_manifest=False,
    )
    total = store.count("sid")
    _sync_registered(
        store,
        sessions,
        [_chat("sid")],
        use_manifest=False,
    )
    assert store.count("sid") == total
    assert not (sessions / MANIFEST_NAME).exists()


@pytest.mark.parametrize("chats_path", [None, "missing"])
def test_unavailable_chat_registry_blocks_import_explicitly(
    store,
    tmp_path: Path,
    chats_path,
):
    sessions = tmp_path / "sessions"
    _write_session_1x(sessions, "old.json", _sample_msgs())
    supplied_path = (
        None if chats_path is None else tmp_path / "missing-chats.json"
    )

    report = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        chats_path=supplied_path,
    )

    assert report.registry_error
    assert report.synced_files == 0
    assert len(report.files) == 1
    assert report.files[0].blocked
    assert "migration blocked" in report.summary()
    assert store.count("sync:old") == 0
    assert not (sessions / MANIFEST_NAME).exists()


@pytest.mark.parametrize("use_manifest", [True, False])
def test_synthetic_rows_rekey_without_manifest_provenance(
    store,
    tmp_path: Path,
    use_manifest: bool,
):
    sessions = tmp_path / "sessions"
    path = _write_session_1x(sessions, "old.json", _sample_msgs())
    seeded = sync_mod._sync_file(
        store,
        path,
        "old.json",
        session_id="sync:old",
    )
    before = [
        row["seq"]
        for row in store._conn.execute(
            "SELECT seq FROM conversation_history "
            "WHERE session_id = 'sync:old' ORDER BY seq",
        )
    ]
    assert seeded.rows_inserted
    (sessions / MANIFEST_NAME).unlink(missing_ok=True)

    report = _sync_registered(
        store,
        sessions,
        [_chat("old")],
        use_manifest=use_manifest,
    )

    assert report.rows_inserted == 0
    assert store.count("sync:old") == 0
    after = [
        row["seq"]
        for row in store._conn.execute(
            "SELECT seq FROM conversation_history "
            "WHERE session_id = 'old' ORDER BY seq",
        )
    ]
    assert after == before


def test_embedded_2x_id_rekeys_without_manifest(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    path = _write_session_2x(
        sessions,
        "canonical.json",
        "old-embedded-id",
        _sample_msgs(),
    )
    seeded = sync_mod._sync_file(
        store,
        path,
        "canonical.json",
        session_id="old-embedded-id",
    )
    assert seeded.rows_inserted

    report = _sync_registered(
        store,
        sessions,
        [_chat("canonical")],
        use_manifest=False,
    )

    assert report.rows_inserted == 0
    assert store.count("old-embedded-id") == 0
    assert store.count("canonical") == seeded.rows_inserted


def test_v1_manifest_rekeys_arbitrary_legacy_id(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    path = _write_session_1x(sessions, "canonical.json", _sample_msgs())
    seeded = sync_mod._sync_file(
        store,
        path,
        "canonical.json",
        session_id="legacy-arbitrary-id",
    )
    assert seeded.rows_inserted
    (sessions / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "version": 1,
                "files": {
                    "canonical.json": {
                        "sha256": sync_mod._sha256(path),
                        "session_id": "legacy-arbitrary-id",
                        "rows_processed": seeded.rows_processed,
                        "rows_inserted": seeded.rows_inserted,
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    report = _sync_registered(store, sessions, [_chat("canonical")])

    assert report.rows_inserted == 0
    assert store.count("legacy-arbitrary-id") == 0
    assert store.count("canonical") == seeded.rows_inserted
    manifest = json.loads(
        (sessions / MANIFEST_NAME).read_text(encoding="utf-8"),
    )
    assert manifest["version"] == 2


def test_manifest_skip_claims_legacy_null_agent_rows(
    store,
    tmp_path: Path,
):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "sid.json", "sid", _sample_msgs())
    first = _sync_registered(store, sessions, [_chat("sid")], agent_id=None)
    assert first.rows_inserted
    assert store._conn.execute(
        "SELECT COUNT(*) FROM conversation_history WHERE agent_id IS NULL",
    ).fetchone()[0]

    second = _sync_registered(store, sessions, [_chat("sid")], agent_id="ag1")

    assert all(result.skipped for result in second.files)
    assert (
        store._conn.execute(
            "SELECT COUNT(*) FROM conversation_history "
            "WHERE session_id = 'sid' AND agent_id = 'ag1'",
        ).fetchone()[0]
        == first.rows_inserted
    )
    assert (
        store._conn.execute(
            "SELECT COUNT(*) FROM conversation_history "
            "WHERE session_id = 'sid' AND agent_id IS NULL",
        ).fetchone()[0]
        == 0
    )


def test_sync_never_touches_source_files(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    path = _write_session_2x(sessions, "sid.json", "sid", _sample_msgs())
    before = path.read_bytes()
    _sync_registered(store, sessions, [_chat("sid")])
    assert path.read_bytes() == before  # byte-for-byte unchanged


def test_channel_subdir_sessions_are_covered(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(
        sessions / "discord",
        "chan-sid.json",
        "chan-sid",
        _sample_msgs(),
    )
    report = _sync_registered(
        store,
        sessions,
        [_chat("chan-sid", channel="discord")],
    )
    assert store.count("chan-sid") > 0
    assert any(f.filename == "discord/chan-sid.json" for f in report.files)


def test_dotted_archive_dirs_are_skipped(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "sid.json", "sid", _sample_msgs())
    # A .weixin-legacy archive copy must NOT be re-imported.
    _write_session_2x(
        sessions / ".weixin-legacy",
        "conv.json",
        "archived-sid",
        _sample_msgs(),
    )
    _sync_registered(store, sessions, [_chat("sid")])
    assert store.count("sid") > 0
    assert store.count("archived-sid") == 0


def test_dry_run_inserts_nothing_and_writes_no_manifest(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "sid.json", "sid", _sample_msgs())
    report = _sync_registered(
        store,
        sessions,
        [_chat("sid")],
        dry_run=True,
    )
    assert store.count("sid") == 0
    assert not (sessions / MANIFEST_NAME).exists()
    assert report.rows_inserted == 0


def test_missing_sessions_dir_is_a_noop(store, tmp_path: Path):
    report = _sync_registered(store, tmp_path / "nope", [])
    assert not report.files
    assert report.summary() == "no sessions to sync"


def test_empty_sessions_dir_is_a_noop(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    report = _sync_registered(store, sessions, [])
    assert not report.files
    assert report.summary() == "no sessions to sync"


def test_corrupt_session_file_is_skipped_not_fatal(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "good-sid.json", "good-sid", _sample_msgs())
    (sessions / "bad.json").write_text("{ not valid json", encoding="utf-8")
    report = _sync_registered(
        store,
        sessions,
        [_chat("good-sid"), _chat("bad")],
    )
    assert report.errored_files == 1
    assert store.count("good-sid") > 0  # the good file still landed


def test_unparseable_message_counted_not_fatal(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    good = _sample_msgs()[0].to_dict()
    state = {
        "session_id": "sid",
        "context": [good, "not a message at all"],
    }
    (sessions / "sid.json").write_text(
        json.dumps({"agent": {"state": state}}),
        encoding="utf-8",
    )
    report = _sync_registered(store, sessions, [_chat("sid")])
    assert report.unparseable >= 1
    assert store.count("sid") >= 1  # the good message still landed


def _write_session_dated(
    sessions_dir: Path,
    filename: str,
    session_id: str,
    dated_msgs: list[tuple[Msg, str]],
) -> Path:
    """Write a 2.0 session whose messages carry explicit ``created_at``."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    ctx = []
    for msg, ts in dated_msgs:
        d = msg.to_dict()
        d["created_at"] = ts
        ctx.append(d)
    state = {"session_id": session_id, "summary": "", "context": ctx}
    path = sessions_dir / filename
    path.write_text(
        json.dumps({"agent": {"state": state}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_retention_skips_messages_older_than_window(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=40)).isoformat()
    recent = (now - timedelta(days=1)).isoformat()
    u, a = _sample_msgs()
    _write_session_dated(
        sessions,
        "sid.json",
        "sid",
        [(u, old), (a, recent)],
    )
    report = _sync_registered(
        store,
        sessions,
        [_chat("sid")],
        retention_days=30,
    )
    assert report.aged_out == 1  # the 40-day-old user turn was skipped
    assert store.count("sid") > 0  # the recent assistant turn landed
    # The aged-out message's content must NOT be in the DB.
    rows = store._conn.execute(
        "SELECT 1 FROM conversation_history "
        "WHERE content LIKE '%please do X%'",
    ).fetchall()
    assert rows == []


def test_retention_zero_keeps_everything(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    ancient = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    u, a = _sample_msgs()
    _write_session_dated(
        sessions,
        "sid.json",
        "sid",
        [(u, ancient), (a, ancient)],
    )
    report = _sync_registered(
        store,
        sessions,
        [_chat("sid")],
        retention_days=0,
    )
    assert report.aged_out == 0
    assert store.count("sid") > 0  # 0 = keep forever, nothing filtered


def test_fully_aged_session_imports_nothing_and_skips_on_rerun(
    store,
    tmp_path: Path,
):
    """A session entirely past the window imports 0 rows; the manifest then
    lets later boots skip it — no re-import/re-purge churn each startup."""
    sessions = tmp_path / "sessions"
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    u, a = _sample_msgs()
    _write_session_dated(sessions, "sid.json", "sid", [(u, old), (a, old)])

    r1 = _sync_registered(
        store,
        sessions,
        [_chat("sid")],
        retention_days=30,
    )
    assert r1.rows_inserted == 0
    assert r1.aged_out == 2
    assert store.count("sid") == 0

    # File unchanged → manifest skip, not re-read (no churn).
    r2 = _sync_registered(
        store,
        sessions,
        [_chat("sid")],
        retention_days=30,
    )
    assert all(f.skipped for f in r2.files)
    assert r2.rows_inserted == 0


def _stub_config_loaders(
    monkeypatch,
    workspace: Path,
    *,
    retention_days: int = 0,
) -> None:
    """Point the startup sync at one scroll agent under *workspace*.

    ``agent_config.workspace_dir`` is deliberately a bogus path: the sync must
    resolve the workspace from the *profile ref*, not from the agent.json body
    (which is stale for cloned workspaces). If a regression reuses
    ``agent_config.workspace_dir``, the bogus path has no sessions/ and the
    first-run notice never fires — failing the test.
    """
    agent_config = SimpleNamespace(
        workspace_dir="/nonexistent/must-not-be-used",
        running=SimpleNamespace(
            light_context_config=SimpleNamespace(
                strategy="scroll",
                scroll_config=SimpleNamespace(
                    db_filename="history.db",
                    history_retention_days=retention_days,
                ),
            ),
        ),
    )
    profiles = {"a1": SimpleNamespace(workspace_dir=str(workspace))}
    config = SimpleNamespace(agents=SimpleNamespace(profiles=profiles))
    import qwenpaw.config as cfg
    import qwenpaw.config.config as cfgcfg

    monkeypatch.setattr(cfg, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(
        cfgcfg,
        "load_agent_config",
        lambda _id: agent_config,
        raising=False,
    )


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_first_run_emits_console_notice_then_stays_quiet(
    monkeypatch,
    caplog,
    tmp_path: Path,
):
    workspace = tmp_path / "ws"
    _write_session_2x(
        workspace / "sessions",
        "sid.json",
        "sid",
        _sample_msgs(),
    )
    _write_chats(
        workspace / "chats.json",
        [{"session_id": "sid", "user_id": "sid", "channel": ""}],
    )
    _stub_config_loaders(monkeypatch, workspace)

    # First boot: a WARNING-level one-time migration notice precedes the work.
    with caplog.at_level(logging.WARNING, logger=sync_mod.logger.name):
        sync_all_scroll_agents()
    first_run_notices = [
        r for r in caplog.records if "first run" in r.getMessage()
    ]
    assert len(first_run_notices) == 1
    assert first_run_notices[0].levelno == logging.WARNING
    assert (workspace / "sessions" / MANIFEST_NAME).exists()

    # Second boot: manifest present → no first-run notice.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=sync_mod.logger.name):
        sync_all_scroll_agents()
    assert not [r for r in caplog.records if "first run" in r.getMessage()]


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_startup_blocks_auto_created_empty_chat_registry(
    monkeypatch,
    caplog,
    tmp_path: Path,
):
    """Startup creates an empty chats.json before history migration runs."""
    workspace = tmp_path / "ws"
    _write_session_1x(
        workspace / "sessions",
        "legacy.json",
        _sample_msgs(),
    )
    _write_chats(workspace / "chats.json", [])
    _stub_config_loaders(monkeypatch, workspace)

    with caplog.at_level(logging.ERROR, logger=sync_mod.logger.name):
        sync_all_scroll_agents()

    assert not (workspace / "sessions" / MANIFEST_NAME).exists()
    assert any(
        "has no registered chats" in record.getMessage()
        for record in caplog.records
    )
    assert not (workspace / "history.db").exists()


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_blocked_registry_does_not_purge_existing_history(
    monkeypatch,
    tmp_path: Path,
):
    workspace = tmp_path / "ws"
    _write_session_1x(
        workspace / "sessions",
        "legacy.json",
        _sample_msgs(),
    )
    _write_chats(workspace / "chats.json", [])
    history = HistoryStore(workspace / "history.db")
    history.append(
        session_id="existing",
        dedup_key="old",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="must survive blocked migration",
            created_at="2000-01-01T00:00:00+00:00",
        ),
    )
    history.close()
    _stub_config_loaders(monkeypatch, workspace, retention_days=30)

    sync_all_scroll_agents()

    conn = sqlite3.connect(workspace / "history.db")
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM conversation_history "
            "WHERE session_id = 'existing'",
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_blocked_registry_does_not_quarantine_corrupt_history(
    monkeypatch,
    tmp_path: Path,
):
    workspace = tmp_path / "ws"
    _write_session_1x(
        workspace / "sessions",
        "legacy.json",
        _sample_msgs(),
    )
    _write_chats(workspace / "chats.json", [])
    db_path = workspace / "history.db"
    original = b"not a sqlite database" * 50
    db_path.write_bytes(original)
    _stub_config_loaders(monkeypatch, workspace)

    sync_all_scroll_agents()

    assert db_path.read_bytes() == original
    assert not list(workspace.glob("history.db.corrupt-*"))
