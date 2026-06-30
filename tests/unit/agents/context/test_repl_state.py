# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""recall_history_python's final ToolChunk must reflect the subprocess exit.

The run has finished by the time the tool returns, so a RUNNING state would
leave it looking perpetually in-flight to tool coordination, persisted
tool_state, and the model. Exit 0 -> SUCCESS, non-zero -> ERROR; the no-sandbox
refusal still -> DENIED.

These exercise the unsandboxed subprocess path (allow_unsandboxed=True), so no
sandbox backend is needed.
"""

import pytest
from agentscope.message import ToolResultState

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.repl import make_recall_history_python


@pytest.fixture
def run(tmp_path):
    # The recall preamble opens history.db read-only, so it must exist first —
    # HistoryStore creates and initialises it (mirrors the real wiring).
    db_path = tmp_path / "history.db"
    HistoryStore(db_path)
    fn = make_recall_history_python(
        history_db_path=str(db_path),
        session_id="s1",
        agent_id="ag1",
        scratch_root=str(tmp_path / ".scroll"),
        allow_unsandboxed=True,
    )
    return fn


async def test_zero_exit_is_success(run):
    chunk = await run("print('hi')")
    assert chunk.state == ToolResultState.SUCCESS


async def test_nonzero_exit_is_error(run):
    chunk = await run("import sys; sys.exit(3)")
    assert chunk.state == ToolResultState.ERROR


async def test_uncaught_exception_is_error(run):
    chunk = await run("raise ValueError('boom')")
    assert chunk.state == ToolResultState.ERROR


async def test_no_sandbox_refusal_is_denied(tmp_path):
    fn = make_recall_history_python(
        history_db_path=str(tmp_path / "history.db"),
        session_id="s1",
        scratch_root=str(tmp_path / ".scroll"),
        allow_unsandboxed=False,
    )
    chunk = await fn("print('hi')", sandbox_config=None)
    assert chunk.state == ToolResultState.DENIED
