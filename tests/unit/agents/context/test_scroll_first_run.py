# -*- coding: utf-8 -*-
# pylint: disable=too-few-public-methods,protected-access
"""The scroll first-run notice.

Scroll became the DEFAULT context strategy, so agents that never set
``strategy`` are switched to it silently and get a durable ``history.db`` in
their workspace. ``build_scroll_components`` must log a one-time notice the
first time it wires scroll in a workspace (the db file's absence is the
signal), and must stay silent on every later run.
"""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import qwenpaw.agents.context as context_mod
from qwenpaw.agents.context import build_scroll_components
from qwenpaw.config.config import LightContextConfig


class _DummyModel:
    """A stand-in model; scroll only stores it, never calls it at wiring."""


def _agent_config(strategy: str = "scroll") -> SimpleNamespace:
    lcc = LightContextConfig(strategy=strategy)
    return SimpleNamespace(running=SimpleNamespace(light_context_config=lcc))


def _build(workspace: Path):
    return build_scroll_components(
        agent_config=_agent_config(),
        workspace_dir=str(workspace),
        model=_DummyModel(),
        session_id="s1",
        agent_id="ag1",
    )


def _notice_records(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "DEFAULT context strategy" in r.msg
    ]


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_first_run_logs_notice_once(tmp_path: Path, caplog):
    db = tmp_path / "history.db"
    assert not db.exists()

    with caplog.at_level(logging.WARNING, logger="qwenpaw.agents.context"):
        components = _build(tmp_path)
    # Scroll actually wired and created the durable store.
    assert components is not None
    assert db.exists()
    # Exactly one notice, and it points at the rollback path.
    records = _notice_records(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    assert str(db) in msg
    assert "native" in msg


def test_notice_does_not_repeat_when_db_exists(tmp_path: Path, caplog):
    # Pre-create the store so this looks like a second startup.
    _build(tmp_path)
    assert (tmp_path / "history.db").exists()

    caplog.clear()  # drop the first run's notice; only watch the second
    with caplog.at_level(logging.WARNING, logger="qwenpaw.agents.context"):
        _build(tmp_path)
    assert _notice_records(caplog) == []


def _size_records(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "history_retention_days" in r.msg
    ]


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_large_existing_db_warns_about_retention(tmp_path: Path, caplog):
    # First build creates a small store (no size warning, just first-run).
    _build(tmp_path)
    db = tmp_path / "history.db"
    assert db.exists()

    # Drop the warn threshold below the tiny db so the next build trips it,
    # and clear the process-level dedupe set so the test is order-independent.
    monkey = db.stat().st_size - 1
    context_mod._DB_SIZE_WARNED.discard(str(db))
    orig = context_mod._DB_SIZE_WARN_BYTES
    context_mod._DB_SIZE_WARN_BYTES = monkey
    try:
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="qwenpaw.agents.context"):
            _build(tmp_path)
            records = _size_records(caplog)
            assert len(records) == 1
            assert "history_retention_days" in records[0].getMessage()
            # Deduped: a second build in the same process does not re-warn.
            caplog.clear()
            _build(tmp_path)
            assert _size_records(caplog) == []
    finally:
        context_mod._DB_SIZE_WARN_BYTES = orig
        context_mod._DB_SIZE_WARNED.discard(str(db))


def test_no_notice_when_strategy_is_native(tmp_path: Path, caplog):
    with caplog.at_level(logging.WARNING, logger="qwenpaw.agents.context"):
        components = build_scroll_components(
            agent_config=_agent_config("native"),
            workspace_dir=str(tmp_path),
            model=_DummyModel(),
            session_id="s1",
            agent_id="ag1",
        )
    # Native is unaffected: nothing wired, no db, no notice.
    assert components is None
    assert not (tmp_path / "history.db").exists()
    assert _notice_records(caplog) == []
