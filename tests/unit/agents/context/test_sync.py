# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Unit tests for the ``sessions/*.json`` → ``history.db`` startup sync.

Pins the rollout-critical guarantees: non-destructive (source files untouched),
idempotent (re-runs and the DB UNIQUE index insert nothing new), faithful (rows
land under the session's embedded ``session_id`` and match the live writer),
and robust (empty dir / corrupt file never raise).
"""

import json
import logging
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


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    h = HistoryStore(tmp_path / "history.db")
    yield h
    h.close()


def test_syncs_session_into_history_under_embedded_id(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "conv.json", "real-sid-123", _sample_msgs())
    report = sync_sessions_to_history(history=store, sessions_dir=sessions)
    assert report.rows_inserted > 0
    assert report.sessions == 1
    # Rows land under the session's OWN embedded id, not the filename.
    assert store.count("real-sid-123") == report.rows_inserted
    # Faithful: the tool result is recallable by its call id.
    rows = store._conn.execute(
        "SELECT content FROM conversation_history "
        "WHERE tool_call_id='c1' AND kind='tool_result'",
    ).fetchall()
    assert rows and rows[0]["content"] == "found it"


def test_legacy_1x_session_uses_filename_fallback_id(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_1x(sessions, "old.json", _sample_msgs())
    report = sync_sessions_to_history(history=store, sessions_dir=sessions)
    assert report.rows_inserted > 0
    # No embedded id in 1.x → synthetic sync:<stem> session.
    assert store.count("sync:old") == report.rows_inserted


def test_sync_is_idempotent_via_manifest(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "conv.json", "sid", _sample_msgs())
    sync_sessions_to_history(history=store, sessions_dir=sessions)
    total = store.count("sid")
    assert (sessions / MANIFEST_NAME).exists()

    second = sync_sessions_to_history(history=store, sessions_dir=sessions)
    assert second.rows_inserted == 0
    assert all(f.skipped for f in second.files)
    assert store.count("sid") == total


def test_manifest_skip_self_heals_when_db_was_reset(tmp_path: Path):
    """A surviving manifest must NOT skip a session missing from a fresh DB.

    Simulates HistoryStore quarantine/recovery: the manifest in sessions/ lives
    on, but history.db is recreated empty. The verified skip must re-sync.
    """
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "conv.json", "sid", _sample_msgs())

    db_path = tmp_path / "history.db"
    h1 = HistoryStore(db_path)
    try:
        sync_sessions_to_history(history=h1, sessions_dir=sessions)
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
        report = sync_sessions_to_history(history=h2, sessions_dir=sessions)
        # Verified skip detected the empty session and re-synced it.
        assert report.rows_inserted > 0
        assert h2.count("sid") > 0
    finally:
        h2.close()


def test_idempotent_even_without_manifest(store, tmp_path: Path):
    """Without the manifest, the DB UNIQUE index still blocks duplicates."""
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "conv.json", "sid", _sample_msgs())
    sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        use_manifest=False,
    )
    total = store.count("sid")
    sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        use_manifest=False,
    )
    assert store.count("sid") == total
    assert not (sessions / MANIFEST_NAME).exists()


def test_sync_never_touches_source_files(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    path = _write_session_2x(sessions, "conv.json", "sid", _sample_msgs())
    before = path.read_bytes()
    sync_sessions_to_history(history=store, sessions_dir=sessions)
    assert path.read_bytes() == before  # byte-for-byte unchanged


def test_channel_subdir_sessions_are_covered(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(
        sessions / "discord",
        "conv.json",
        "chan-sid",
        _sample_msgs(),
    )
    report = sync_sessions_to_history(history=store, sessions_dir=sessions)
    assert store.count("chan-sid") > 0
    assert any(f.filename == "discord/conv.json" for f in report.files)


def test_dotted_archive_dirs_are_skipped(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "conv.json", "sid", _sample_msgs())
    # A .weixin-legacy archive copy must NOT be re-imported.
    _write_session_2x(
        sessions / ".weixin-legacy",
        "conv.json",
        "archived-sid",
        _sample_msgs(),
    )
    sync_sessions_to_history(history=store, sessions_dir=sessions)
    assert store.count("sid") > 0
    assert store.count("archived-sid") == 0


def test_dry_run_inserts_nothing_and_writes_no_manifest(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "conv.json", "sid", _sample_msgs())
    report = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        dry_run=True,
    )
    assert store.count("sid") == 0
    assert not (sessions / MANIFEST_NAME).exists()
    assert report.rows_inserted == 0


def test_missing_sessions_dir_is_a_noop(store, tmp_path: Path):
    report = sync_sessions_to_history(
        history=store,
        sessions_dir=tmp_path / "nope",
    )
    assert not report.files
    assert report.summary() == "no sessions to sync"


def test_empty_sessions_dir_is_a_noop(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    report = sync_sessions_to_history(history=store, sessions_dir=sessions)
    assert not report.files
    assert report.summary() == "no sessions to sync"


def test_corrupt_session_file_is_skipped_not_fatal(store, tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_session_2x(sessions, "good.json", "good-sid", _sample_msgs())
    (sessions / "bad.json").write_text("{ not valid json", encoding="utf-8")
    report = sync_sessions_to_history(history=store, sessions_dir=sessions)
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
    (sessions / "conv.json").write_text(
        json.dumps({"agent": {"state": state}}),
        encoding="utf-8",
    )
    report = sync_sessions_to_history(history=store, sessions_dir=sessions)
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
        "conv.json",
        "sid",
        [(u, old), (a, recent)],
    )
    report = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
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
        "conv.json",
        "sid",
        [(u, ancient), (a, ancient)],
    )
    report = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
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
    _write_session_dated(sessions, "conv.json", "sid", [(u, old), (a, old)])

    r1 = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        retention_days=30,
    )
    assert r1.rows_inserted == 0
    assert r1.aged_out == 2
    assert store.count("sid") == 0

    # File unchanged → manifest skip, not re-read (no churn).
    r2 = sync_sessions_to_history(
        history=store,
        sessions_dir=sessions,
        retention_days=30,
    )
    assert all(f.skipped for f in r2.files)
    assert r2.rows_inserted == 0


def _stub_config_loaders(monkeypatch, workspace: Path) -> None:
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
                    history_retention_days=0,
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
        "conv.json",
        "sid",
        _sample_msgs(),
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
