"""The sandboxed ``execute_python`` recall tool.

The model recalls evicted history by running Python here, not by scrolling
back. Each call runs a fresh process (Option A: stateless cells) inside the
sandbox when a ``sandbox_config`` is supplied — mirroring
``execute_shell_command``. The cell's namespace exposes ``ms`` (the durable
history ATTACHed read-only + a file-backed scratch DB), ``SCRATCH``, ``grep``
and ``days_between`` via :mod:`._repl_helpers`.

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

# Directory holding _repl_helpers.py / memoryspace.py — added to the cell's
# sys.path so the sandboxed process imports them by bare module name.
_PKG_DIR = str(Path(__file__).parent)

_DOC = """Run Python to recall evicted conversation history.

The persistent record lives in a SQLite store reached through `ms`:
  • ms.sql_query(sql, params=None) — read; `hist.conversation_history` is the
    durable history (read-only), `main` is your read/write scratch.
  • ms.search(query, scope="session"|"task"|"all", kind=None, k=10) — FTS5.
  • ms.sql_exec(sql, params=None) — write to scratch (CREATE/INSERT/...).
Also available: SCRATCH (a Path for working files), grep(pattern, path=SCRATCH),
days_between(d1, d2). Only what you print() is returned; variables do NOT
persist across calls, but scratch tables do.

Args:
    source (str): Python source to execute.
"""


def make_execute_python(
    *,
    history_db_path: str,
    session_id: str | None,
    task_id: str | None,
    scratch_root: str,
    timeout_s: int = 300,
):
    """Build an ``execute_python`` tool bound to one session's history."""
    scratch_dir = str(Path(scratch_root) / "repl")
    scratch_db = str(Path(scratch_root) / "repl" / "scratch.db")
    cells_dir = Path(scratch_root) / "cells"

    def _build_cell(source: str) -> Path:
        preamble = (
            "import sys\n"
            f"sys.path.insert(0, {_PKG_DIR!r})\n"
            "from _repl_helpers import bootstrap\n"
            "globals().update(bootstrap(\n"
            f"    history_db_path={history_db_path!r},\n"
            f"    session_id={session_id!r},\n"
            f"    task_id={task_id!r},\n"
            f"    scratch_dir={scratch_dir!r},\n"
            f"    scratch_db_path={scratch_db!r},\n"
            "))\n"
        )
        cells_dir.mkdir(parents=True, exist_ok=True)
        cell = cells_dir / f"cell_{uuid.uuid4().hex}.py"
        cell.write_text(preamble + "\n" + (source or ""), encoding="utf-8")
        return cell

    async def execute_python(
        source: str,
        sandbox_config: Optional[Any] = None,
    ) -> ToolChunk:
        cell = _build_cell(source)
        cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(cell))}"
        try:
            if sandbox_config is not None:
                stdout, stderr, code = await _run_sandboxed(
                    cmd, sandbox_config, timeout_s, scratch_root,
                )
            else:
                stdout, stderr, code = await _run_subprocess(
                    cmd, timeout_s, scratch_root,
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
    execute_python._tool_descriptor = ToolDescriptor(  # type: ignore[attr-defined]
        name="execute_python",
        func=execute_python,
        requires_sandbox=("shell_exec",),
        async_execution=True,
        description=_DOC.splitlines()[0],
    )
    return execute_python


async def _run_sandboxed(
    cmd: str, sandbox_config: Any, timeout_s: int, cwd: str,
) -> tuple[str, str, int]:
    from ....sandbox import create_sandbox

    sandbox_config.timeout_seconds = int(timeout_s)
    async with create_sandbox(sandbox_config) as sandbox:
        result = await sandbox.execute(cmd, cwd=cwd)
    return result.stdout, result.stderr, result.exit_code


async def _run_subprocess(
    cmd: str, timeout_s: int, cwd: str,
) -> tuple[str, str, int]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        return "", f"execute_python timed out after {timeout_s}s", -1
    return out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), proc.returncode or 0


def _format_observation(stdout: str, stderr: str, code: int) -> str:
    parts: list[str] = []
    if stdout.strip():
        parts.append(f"stdout:\n{stdout.rstrip()}")
    if stderr.strip():
        parts.append(f"stderr:\n{stderr.rstrip()}")
    if code != 0:
        parts.append(f"exit_code: {code}")
    return "\n".join(parts) if parts else "(no output)"
