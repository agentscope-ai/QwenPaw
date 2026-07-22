# -*- coding: utf-8 -*-
"""The sandboxed ``recall_history_python`` recall tool.

This is raw conversation-history recall — the agent's own recorded turns
across its sessions (verbatim). The model recalls history by running Python
here, not by scrolling back. Each call runs a fresh process (Option A:
stateless cells) inside the sandbox when a ``sandbox_config`` is supplied —
mirroring ``execute_shell_command``. The cell preamble builds ``ms`` (the
durable history ATTACHed read-only + a file-backed scratch DB) from
:mod:`.memoryspace`.

Python variables do not persist across calls; derived tables do, because the
``ms`` scratch DB is file-backed under the workspace.
"""

import asyncio
import shlex
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...tools.utils import truncate_text_output  # repo-standard output bound
from ....runtime.tool_registry import ToolDescriptor

# Directory holding memoryspace.py — added to the cell's sys.path so the
# sandboxed process imports it by bare module name.
_PKG_DIR = str(Path(__file__).parent)

_DOC = """Recall conversation history via Python — the ADVANCED recall tool.

Prefer `recall_history` for ordinary expand/search/recall_tool reads. Use this
sandboxed Python tool for session listing, custom SQL counting/ranking,
scratch tables, or cross-referencing many turns programmatically.

`ms` is ALREADY DEFINED; use it directly (do not import it). Each call is a
fresh process: Python variables do NOT persist, while tables written through
`ms.sql_exec` persist in the scratch DB. Only printed stdout is returned.

KEEP STDOUT BOUNDED. This tool has no continuation cursor and large stdout is
truncated. Filter before printing, print short fields/slices, or page with SQL
`LIMIT ? OFFSET ?`; issue another call for the next page. Never print a broad
unbounded result set.

Helpers return `list[dict]`; text is always in `content` (not
`content_preview`). A trailing `{"_truncated": True}` means the row cap was
reached: narrow or page the query.

  • ms.expand(lo, hi)
    Raw turns for an inclusive seq span, oldest first.
  • ms.search(query, k=10, kind=None, all_agents=False,
              session_id=None, agent_id=None)
    Keyword/FTS search across your sessions; uppercase OR is supported.
  • ms.recall_tool(tool_call_id, all_agents=False)
    Tool call/result; saved large outputs include an artifact file pointer.
  • ms.sessions(all_agents=False, limit=50)
  • ms.session(session_id, all_agents=False, limit=1000)
  • ms.agents(limit=100)
  • ms.days_between(d1, d2, inclusive=False)
  • ms.sql_query(sql, params)
    Read-only SQL; durable history is `hist.conversation_history`.
  • ms.sql_exec(sql, params)
    Writes only the persistent scratch DB. Always bind values via `params`.

Typical flow: locate targeted seq values with `ms.search`, then read only the
needed range with `ms.expand`. For custom paging:

    rows = ms.sql_query(
        "SELECT seq, content FROM hist.conversation_history "
        "WHERE seq BETWEEN ? AND ? ORDER BY seq LIMIT ? OFFSET ?",
        (lo, hi, 20, offset),
    )
    for row in rows:
        print(row["seq"], row["content"][:2000])

Args:
    source (str): Python source to execute.
"""


def make_recall_history_python(
    *,
    history_db_path: str,
    session_id: str | None,
    agent_id: str | None = None,
    scratch_root: str,
    timeout_s: int = 300,
    allow_unsandboxed: bool = False,
):
    """Build a ``recall_history_python`` tool bound to one session's history.

    ``recall_history_python`` runs model-authored Python. The sandbox is the
    only
    isolation boundary, and ``sandbox_config`` is injected solely by
    ``PolicyGuardedTool``. When governance is degraded (e.g. the governor
    fails to start and the tool is wrapped in a plain ``GuardedFunctionTool``)
    no config is injected — so the tool **fails closed**: with ``sandbox_config
    is None`` it refuses to run unless ``allow_unsandboxed=True``. That flag is
    the resolved escape-hatch decision, NOT the raw per-agent config: the
    caller (``build_scroll_components``) only passes ``True`` when the
    deployment-layer ``QWENPAW_ALLOW_UNSANDBOXED_RECALL`` env var AND the agent
    config both opt in (see ``scroll_unsandboxed_allowed``), so an untrusted
    agent.json can never reach this branch on its own. Enabling it runs
    arbitrary host code as the agent user with zero isolation; trusted
    local/dev only.
    """
    scratch_db = str(Path(scratch_root) / "repl" / "scratch.db")
    cells_dir = Path(scratch_root) / "cells"

    def _build_cell(source: str) -> Path:
        # sqlite3.connect won't create missing parent dirs, so make the
        # scratch DB's holding dir before MemorySpace opens it.
        preamble = (
            "import sys\n"
            f"sys.path.insert(0, {_PKG_DIR!r})\n"
            "from pathlib import Path\n"
            "from memoryspace import MemorySpace\n"
            f"Path({scratch_db!r}).parent.mkdir(parents=True, exist_ok=True)\n"
            "ms = MemorySpace(\n"
            f"    history_db_path={history_db_path!r},\n"
            f"    session_id={session_id!r},\n"
            f"    agent_id={agent_id!r},\n"
            f"    scratch_db_path={scratch_db!r},\n"
            ")\n"
            # Safety net: ``ms`` is meant to be used directly, but models often
            # reflexively ``import ms``. Registering the instance as a module
            # makes that import bind ``ms`` to this same object instead of
            # raising ModuleNotFoundError.
            "sys.modules['ms'] = ms\n"
        )
        cells_dir.mkdir(parents=True, exist_ok=True)
        cell = cells_dir / f"cell_{uuid.uuid4().hex}.py"
        cell.write_text(preamble + "\n" + (source or ""), encoding="utf-8")
        return cell

    async def recall_history_python(
        source: str,
        sandbox_config: Optional[Any] = None,
    ) -> ToolChunk:
        # Fail closed: without a sandbox there is no isolation, so refuse to
        # run model-authored code unless an operator explicitly opted in.
        if sandbox_config is None and not allow_unsandboxed:
            return ToolChunk(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "recall_history_python refused: no sandbox "
                            "available "
                            "(sandbox_config is None). This tool runs "
                            "model-authored Python and only executes inside "
                            "the sandbox. The governance layer may be "
                            "degraded. To run without isolation (UNSAFE; "
                            "trusted local use only) an operator must set the "
                            "QWENPAW_ALLOW_UNSANDBOXED_RECALL env var AND "
                            "scroll_config.allow_unsandboxed=true."
                        ),
                    ),
                ],
                state=ToolResultState.DENIED,
            )
        cell = _build_cell(source)
        argv = [sys.executable, str(cell)]
        try:
            if sandbox_config is not None:
                # The sandbox runs a shell command string; quote each argv
                # element (POSIX shell inside the sandbox).
                cmd = " ".join(shlex.quote(a) for a in argv)
                stdout, stderr, code = await _run_sandboxed(
                    cmd,
                    sandbox_config,
                    timeout_s,
                    scratch_root,
                )
            else:
                # No shell: pass argv straight to the OS so quoting is
                # correct on every platform (cmd.exe rejects shlex's POSIX
                # single-quotes, which would fail the run on Windows).
                stdout, stderr, code = await _run_subprocess(
                    argv,
                    timeout_s,
                    scratch_root,
                )
        finally:
            try:
                cell.unlink()
            except OSError:
                pass

        text = _format_observation(stdout, stderr, code)
        # The subprocess has finished, so this is a terminal chunk — RUNNING
        # would leave it looking perpetually in-flight to tool coordination,
        # persisted tool_state, and the model. Reflect the actual exit.
        state = ToolResultState.SUCCESS if code == 0 else ToolResultState.ERROR
        text, metadata = truncate_text_output(text)
        return ToolChunk(
            content=[TextBlock(type="text", text=text)],
            state=state,
            metadata=metadata,
        )

    recall_history_python.__doc__ = _DOC
    # Attach the descriptor directly (not via @tool_descriptor) so the tool is
    # sandbox-capable but is NOT auto-collected into the global builtin set —
    # it exists only when the scroll strategy wires it in.
    descriptor = ToolDescriptor(
        name="recall_history_python",
        func=recall_history_python,
        requires_sandbox=("shell_exec",),
        async_execution=True,
        description=_DOC.splitlines()[0],
    )
    # pylint: disable-next=protected-access
    recall_history_python._tool_descriptor = descriptor  # type: ignore[attr-defined] # noqa: E501
    return recall_history_python


async def _run_sandboxed(
    cmd: str,
    sandbox_config: Any,
    timeout_s: int,
    cwd: str,
) -> tuple[str, str, int]:
    from ....sandbox import create_sandbox

    sandbox_config.timeout_seconds = int(timeout_s)
    async with create_sandbox(sandbox_config) as sandbox:
        result = await sandbox.execute(cmd, cwd=cwd)
    return result.stdout, result.stderr, result.exit_code


async def _run_subprocess(
    argv: list[str],
    timeout_s: int,
    cwd: str,
) -> tuple[str, str, int]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        proc.kill()
        return "", f"recall_history_python timed out after {timeout_s}s", -1
    return (
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
        proc.returncode or 0,
    )


def _format_observation(stdout: str, stderr: str, code: int) -> str:
    """Render the cell's outcome so a failure can NEVER read as an answer.

    A non-zero exit leads with an explicit banner: without it a traceback
    (or silence) after a history query is too easy to misread as "the
    history holds nothing", and the model may then answer from stale
    context instead of retrying or saying recall failed. The banner is
    derived from what actually happened — a cell that printed real hits and
    THEN crashed must not be told "the history was not read", or the model
    discards valid data sitting right below the claim. Same care for the
    exit-0-but-silent case: printing nothing is not evidence of absence.
    """
    parts: list[str] = []
    if code != 0 and stdout.strip():
        parts.append(
            f"RECALL INCOMPLETE (exit {code}) — the cell crashed AFTER "
            "printing the stdout below. That output is real, already-"
            "retrieved history: use it. Fix the code and re-run only for "
            "whatever is still missing.",
        )
    elif code != 0:
        parts.append(
            f"RECALL FAILED (exit {code}) — the history was NOT read. "
            "This is an execution error, not an empty history: fix the "
            "query and retry, or say explicitly that you could not "
            "retrieve the context. Do not answer as if the history held "
            "nothing.",
        )
    if stdout.strip():
        parts.append(f"stdout:\n{stdout.rstrip()}")
    if stderr.strip():
        parts.append(f"stderr:\n{stderr.rstrip()}")
    if not parts:
        return (
            "(no output — the cell printed nothing. This is not evidence "
            "the history is empty: print() your results, or retry with "
            "different keywords.)"
        )
    return "\n".join(parts)
