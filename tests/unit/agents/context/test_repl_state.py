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


# -- a failed or silent recall must never read as "history is empty" --------


def _text(chunk) -> str:
    block = chunk.content[0]
    return block["text"] if isinstance(block, dict) else block.text


async def test_failure_banner_leads_the_observation(run):
    """A crashed cell leads with an explicit RECALL FAILED banner, so the
    traceback cannot be misread as an empty history."""
    chunk = await run("raise ValueError('boom')")
    text = _text(chunk)
    assert text.startswith("RECALL FAILED")
    assert "NOT read" in text
    assert "ValueError: boom" in text  # the traceback still follows


async def test_partial_output_crash_is_incomplete_not_failed(run):
    """A cell that printed real hits and THEN crashed must not claim the
    history was not read — the model would discard the valid rows sitting
    right below the banner."""
    chunk = await run(
        "print('hit: flight AA231')\nraise ValueError('late boom')",
    )
    text = _text(chunk)
    assert text.startswith("RECALL INCOMPLETE")
    assert "hit: flight AA231" in text  # the partial output is preserved
    assert "NOT read" not in text  # no false claim above real data


async def test_silent_success_is_not_evidence_of_absence(run):
    chunk = await run("x = 1  # prints nothing")
    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "no output" in text
    assert "not evidence" in text


async def test_successful_output_carries_no_banner(run):
    chunk = await run("print('hit: flight AA231')")
    text = _text(chunk)
    assert "RECALL FAILED" not in text
    assert "hit: flight AA231" in text
