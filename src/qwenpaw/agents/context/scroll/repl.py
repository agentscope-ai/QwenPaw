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

For the common reads — re-expand a seq span, search by keywords, re-read one
tool call — prefer the simpler `recall_history` tool (op="expand"/"search"/
"recall_tool"): it needs no code and no sandbox. Reach for THIS Python REPL
when you need more than those three: listing/reading whole sessions, custom
SQL counting/ranking, scratch tables, or programmatically cross-referencing
many turns in one cell.

Read back the verbatim turns of your conversations from a durable log: this
session's turns that scrolled out of context (seq spans come from the
[context compressed] map) plus your earlier sessions. Usual flow: LOCATE a
seq — via the map or ms.search — then ms.expand(lo, hi) for the full turns
(one turn is ms.expand(seq, seq)). Commit an answer only from the FULL turn
text that ms.search / ms.expand return, never from a headline alone — the
answer is often buried late in a long, multi-topic turn.

`ms` is ALREADY DEFINED in this cell — use it directly. Do NOT `import ms`: it
is a ready-made object, not a module, and importing it raises
ModuleNotFoundError. Only what you print() is returned; variables do NOT
persist across calls, but scratch tables do.

    # scan hits by content (raw turns usually have NO headline), then re-read
    hits = ms.search("flight number", k=20)
    for r in hits:
        print(r["seq"], r["content"][:1000])
    print(ms.expand(180, 184))   # full turns once you have the seq span

Every helper returns a LIST OF DICTS (rows). Each helper's output schema is its
`Row: {…}` line below — those are the EXACT dict keys you index by (there is no
`content_preview`: the text key is always `content`, and only `search` carries
`session_id`). Don't assume a key; print(rows[0].keys()) if unsure. On overflow
the row helpers append a trailing {"_truncated": True} row (search is capped by
k instead) — narrow your span if you see it.

The persistent record reaches you through `ms`. Prefer these intent helpers
(values are bound for you — no SQL to write):
  • ms.expand(lo, hi) — full turns in the seq span [lo, hi], oldest first.
    Row: {seq, kind, role, name, content, headline}.
  • ms.recall_tool(tool_call_id) — a tool call and its result (this agent;
    pass all_agents=True to widen). Row: {seq, kind, role, name, tool_input,
    tool_state, content}.
  • ms.search(query, all_agents=False, kind=None, k=10) — FTS5. By default
    searches your whole history across past sessions; all_agents=True spans
    every agent here. Pin a specific one with session_id="cron:<job>" /
    agent_id="<other>" (these take precedence). kind filters by row kind
    ("model_turn" / "tool_result"). Row: {seq, session_id, kind, role, name,
    headline, content (full turn)}. Query with keywords, not full sentences
    (all terms must appear); use OR-sets for alternatives and a generous k to
    cast a wide net: ms.search("tank OR aquarium OR goldfish", k=20). Your
    current in-progress turn is never a hit — it is already in front of you.
  • ms.sessions() — your past conversations (incl. scheduled cron/heartbeat
    runs); ms.session(session_id, all_agents=False) reads one in full, scoped
    to you by default. ms.agents() lists agents.
  • ms.days_between(d1, d2, inclusive=False) — |days| between two dates
    (parses a date out of either string); use it instead of hand math.
Advanced escape hatch: ms.sql_query(sql, params) reads arbitrary SQL over the
read-only `hist.conversation_history` (for custom counting/ranking) and
ms.sql_exec(sql, params) writes a `main` scratch DB. Bind via params, never
f-string values in.

ANSWERING FROM RECALL — once you've pulled the turns:
  • "How many / list all": the evidence is usually spread across SESSIONS —
    find them ALL (several searches / angles), then count DISTINCT items the
    user actually DID — not mentions (the same thing said 3× is one), and not
    things merely planned/considered or that you (the assistant) suggested.
  • A fact that CHANGED over time: the most recent one (by date) is the current
    answer and supersedes earlier values — give the latest, don't report a
    stale one or stack both.
  • "When / how long between": read each relevant turn's date (turns carry a
    date), anchor relative phrases ("last Tuesday", "two months ago") to THAT
    turn's date, and use ms.days_between — never do calendar math by hand.
  • What the USER did, owns, or prefers comes from the USER's own turns, not
    from suggestions you (the assistant) offered.
  • CONNECT facts: linking two stated facts to reach a third is valid reading,
    not fabrication. But COMMIT only to the EXACT thing asked — a near-relative
    does not count ("Sales Engineer" != "Sales Manager").
  • Don't refuse after one empty query — try a differently-phrased search
    first; abstain only when the history genuinely holds nothing.

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
