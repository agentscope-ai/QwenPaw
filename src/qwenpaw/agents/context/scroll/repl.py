# -*- coding: utf-8 -*-
"""The sandboxed ``execute_python`` recall tool.

The model recalls evicted history by running Python here, not by scrolling
back. Each call runs a fresh process (Option A: stateless cells) inside the
sandbox when a ``sandbox_config`` is supplied — mirroring
``execute_shell_command``. The cell preamble builds ``ms`` (the durable
history ATTACHed read-only + a file-backed scratch DB) from
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

_DOC = """Run Python to recall evicted conversation history.

The persistent record reaches you through `ms`. Prefer these intent helpers
(values are bound for you — no SQL to write):
  • ms.expand(lo, hi) — full turns in the seq span [lo, hi], oldest first.
  • ms.outline(lo, hi) — headlines only in that span (zoom before expand).
  • ms.recall_tool(tool_call_id) — a tool call and its result (this agent;
    pass all_agents=True to widen).
  • ms.search(query, all_agents=False, kind=None, k=10) — FTS5. By default
    searches your whole history across past sessions; all_agents=True spans
    every agent here. Pin a specific one with session_id="cron:<job>" /
    agent_id="<other>" (these take precedence).
  • ms.sessions() — your past conversations (incl. scheduled cron/heartbeat
    runs); ms.session(session_id) reads one in full. ms.agents() lists agents.
  • ms.days_between(d1, d2, inclusive=False) — |days| between two dates
    (parses a date out of either string); use it instead of hand math.
Advanced escape hatch: ms.sql_query(sql, params) reads arbitrary SQL over the
read-only `hist.conversation_history` (for custom counting/ranking) and
ms.sql_exec(sql, params) writes a `main` scratch DB. Bind via params, never
f-string values in.
Only what you print() is returned; variables do NOT persist across calls,
but scratch tables do.

Args:
    source (str): Python source to execute.
"""


def make_execute_python(
    *,
    history_db_path: str,
    session_id: str | None,
    agent_id: str | None = None,
    scratch_root: str,
    timeout_s: int = 300,
    allow_unsandboxed: bool = False,
):
    """Build an ``execute_python`` tool bound to one session's history.

    ``execute_python`` runs model-authored Python. The sandbox is the only
    isolation boundary, and ``sandbox_config`` is injected solely by
    ``PolicyGuardedTool``. When governance is degraded (e.g. the governor
    fails to start and the tool is wrapped in a plain ``GuardedFunctionTool``)
    no config is injected — so the tool **fails closed**: with ``sandbox_config
    is None`` it refuses to run unless ``allow_unsandboxed=True`` is explicitly
    set. Enabling that opt-in runs arbitrary host code as the agent user with
    zero isolation; use it only for trusted local/dev setups.
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
        )
        cells_dir.mkdir(parents=True, exist_ok=True)
        cell = cells_dir / f"cell_{uuid.uuid4().hex}.py"
        cell.write_text(preamble + "\n" + (source or ""), encoding="utf-8")
        return cell

    async def execute_python(
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
                            "execute_python refused: no sandbox available "
                            "(sandbox_config is None). This tool runs "
                            "model-authored Python and only executes inside "
                            "the sandbox. The governance layer may be "
                            "degraded. Set scroll_config.allow_unsandboxed="
                            "true to run without isolation (UNSAFE; trusted "
                            "local use only)."
                        ),
                    ),
                ],
                state=ToolResultState.DENIED,
            )
        cell = _build_cell(source)
        cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(cell))}"
        try:
            if sandbox_config is not None:
                stdout, stderr, code = await _run_sandboxed(
                    cmd,
                    sandbox_config,
                    timeout_s,
                    scratch_root,
                )
            else:
                stdout, stderr, code = await _run_subprocess(
                    cmd,
                    timeout_s,
                    scratch_root,
                )
        finally:
            try:
                cell.unlink()
            except OSError:
                pass

        text = _format_observation(stdout, stderr, code)
        return ToolChunk(
            content=[TextBlock(type="text", text=truncate_text_output(text))],
            state=ToolResultState.RUNNING,
        )

    execute_python.__doc__ = _DOC
    # Attach the descriptor directly (not via @tool_descriptor) so the tool is
    # sandbox-capable but is NOT auto-collected into the global builtin set —
    # it exists only when the scroll strategy wires it in.
    descriptor = ToolDescriptor(
        name="execute_python",
        func=execute_python,
        requires_sandbox=("shell_exec",),
        async_execution=True,
        description=_DOC.splitlines()[0],
    )
    # pylint: disable-next=protected-access
    execute_python._tool_descriptor = descriptor  # type: ignore[attr-defined]
    return execute_python


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
    cmd: str,
    timeout_s: int,
    cwd: str,
) -> tuple[str, str, int]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
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
        return "", f"execute_python timed out after {timeout_s}s", -1
    return (
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
        proc.returncode or 0,
    )


def _format_observation(stdout: str, stderr: str, code: int) -> str:
    parts: list[str] = []
    if stdout.strip():
        parts.append(f"stdout:\n{stdout.rstrip()}")
    if stderr.strip():
        parts.append(f"stderr:\n{stderr.rstrip()}")
    if code != 0:
        parts.append(f"exit_code: {code}")
    return "\n".join(parts) if parts else "(no output)"
