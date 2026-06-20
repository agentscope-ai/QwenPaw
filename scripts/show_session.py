# -*- coding: utf-8 -*-
"""Pretty-print a QwenPaw agent's persisted context (session state).

Two views:

* **Session JSON** (default) — ``state.context``, the *compacted* window the
  agent currently reasons over, plus ``state.summary``. This is what the
  agent (and the frontend) actually sees right now.
* **Durable history.db** (``--session`` / ``--list-sessions``) — under the
  *scroll* strategy, the FULL per-session record, never trimmed. Use it to
  inspect what a scheduled run actually said, e.g. a ``cron:<job-id>`` or the
  ``main`` heartbeat session, even after compaction dropped it from the window.

Usage:
    # session JSON, by full path
    uv run python scripts/show_session.py <session.json>
    # session JSON, by agent + question id / latest
    QWENPAW_WORKING_DIR=$HOME/.copaw uv run python scripts/show_session.py \
        --agent memory-agent --qid gpt4_2655b836
    QWENPAW_WORKING_DIR=$HOME/.copaw uv run python scripts/show_session.py \
        --agent memory-agent --latest

    # durable history.db (scroll): list sessions, then dump one in full
    QWENPAW_WORKING_DIR=$HOME/.copaw uv run python scripts/show_session.py \
        --agent memory-agent --list-sessions
    QWENPAW_WORKING_DIR=$HOME/.copaw uv run python scripts/show_session.py \
        --agent memory-agent --session cron:nightly-report

Add --full to print whole message texts (default truncates to 200 chars).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3


def _sessions_dir(agent: str) -> str:
    from qwenpaw.constant import WORKING_DIR

    return os.path.join(str(WORKING_DIR), "workspaces", agent, "sessions")


def _history_db_path(args: argparse.Namespace) -> str:
    """Locate the durable scroll history.db (explicit override or by agent)."""
    if args.history_db:
        return args.history_db
    if args.agent:
        from qwenpaw.constant import WORKING_DIR

        return os.path.join(
            str(WORKING_DIR), "workspaces", args.agent, "history.db"
        )
    raise SystemExit("history mode needs --history-db or --agent")


def _open_ro(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        raise SystemExit(f"history.db not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _list_sessions(db_path: str) -> None:
    conn = _open_ro(db_path)
    rows = conn.execute(
        "SELECT session_id, agent_id, COUNT(*) AS turns, "
        "MIN(seq) AS first_seq, MAX(seq) AS last_seq, "
        "MAX(created_at) AS last_at FROM conversation_history "
        "GROUP BY session_id ORDER BY last_seq DESC"
    ).fetchall()
    print(f"# {db_path}\n")
    print(f"=== {len(rows)} session(s) ===")
    for r in rows:
        print(
            f"{r['session_id']}  [agent={r['agent_id']}]  "
            f"{r['turns']} turns, seq {r['first_seq']}-{r['last_seq']}, "
            f"last {r['last_at']}"
        )


def _show_history_session(db_path: str, session_id: str, full: bool) -> None:
    conn = _open_ro(db_path)
    rows = conn.execute(
        "SELECT seq, kind, role, name, headline, content "
        "FROM conversation_history WHERE session_id = ? ORDER BY seq",
        (session_id,),
    ).fetchall()
    print(f"# {db_path}  session={session_id}\n")
    if not rows:
        print("(no rows — unknown session_id? try --list-sessions)")
        return
    print(f"=== {len(rows)} turn(s) ===")
    for r in rows:
        text = (r["content"] or "").replace("\n", " ")
        if not full:
            text = text[:200]
        headline = f" ⟦{r['headline']}⟧" if r["headline"] else ""
        print(f"[{r['seq']:04d}][{r['role']}/{r['kind']}]{headline} {text}")


def _resolve_path(args: argparse.Namespace) -> str:
    if args.path:
        return args.path
    sdir = _sessions_dir(args.agent)
    if args.qid:
        hits = glob.glob(os.path.join(sdir, f"*{args.qid}*"))
        if not hits:
            raise SystemExit(
                f"No session file matching qid={args.qid} in {sdir}"
            )
        return hits[0]
    if args.latest:
        files = glob.glob(os.path.join(sdir, "*.json"))
        if not files:
            raise SystemExit(f"No session files in {sdir}")
        return max(files, key=os.path.getmtime)
    raise SystemExit("Provide a path, or --agent with --qid/--latest")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", help="session state JSON path")
    p.add_argument("--agent", help="agent id (to locate sessions dir)")
    p.add_argument("--qid", help="question id to match in filename")
    p.add_argument("--latest", action="store_true", help="newest session file")
    p.add_argument(
        "--full", action="store_true", help="print full message text"
    )
    p.add_argument(
        "--history-db",
        help="read the durable scroll history.db instead of session JSON",
    )
    p.add_argument(
        "--session",
        help="session_id to dump from history.db (e.g. cron:<job-id>, main)",
    )
    p.add_argument(
        "--list-sessions",
        action="store_true",
        help="list the sessions recorded in history.db",
    )
    args = p.parse_args()

    # Durable-history mode: full per-session record (scroll), never trimmed.
    if args.history_db or args.session or args.list_sessions:
        db_path = _history_db_path(args)
        if args.session and not args.list_sessions:
            _show_history_session(db_path, args.session, args.full)
        else:
            _list_sessions(db_path)
        return

    path = _resolve_path(args)
    print(f"# {path}\n")
    d = json.load(open(path, encoding="utf-8"))
    st = (d.get("agent") or {}).get("state") or d.get("state") or {}

    summary = st.get("summary") or ""
    print(f"=== compaction summary ({len(summary)} chars) ===")
    print(summary if args.full else (summary[:500] or "(empty)"))

    ctx = st.get("context") or []
    print(f"\n=== context: {len(ctx)} messages ===")
    for i, m in enumerate(ctx):
        parts = []
        for b in m.get("content", []):
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                else:
                    parts.append(f"<{b.get('type')}>")
        text = " ".join(parts).replace("\n", " ")
        if not args.full:
            text = text[:200]
        print(f"[{i:02d}][{m.get('role')}] {text}")


if __name__ == "__main__":
    main()
