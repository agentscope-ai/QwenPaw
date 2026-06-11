#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PreToolUse guard for AgentScope / qwenpaw edits.

Blocks Edit/Write on code that belongs to qwenpaw or uses AgentScope until the
`agentscope-guardian` skill has reviewed and approved the change. Approval is
recorded in `.claude/.agentscope-guardian-approved` (one normalized relative
path per line, tab-separated with an ISO timestamp). The guardian skill writes
that marker after it APPROVES a change.

Exit codes (Claude Code hook protocol):
  0  -> allow the tool call
  2  -> block the tool call; stderr is shown to the model as feedback

Escape hatch: set env var QWENPAW_GUARDIAN_OFF=1 to disable gating entirely.
"""
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = os.path.join(REPO, ".claude", ".agentscope-guardian-approved")
APPROVAL_TTL_SECONDS = 24 * 60 * 60  # approvals older than this are ignored


def _norm(path: str) -> str:
    """Repo-relative, forward-slash, lowercased path (or abs lowercased)."""
    if not path:
        return ""
    p = os.path.abspath(path)
    try:
        p = os.path.relpath(p, REPO)
    except ValueError:
        pass
    return p.replace("\\", "/").lstrip("./").lower()


# Paths that are reference/config only and must never be gated, even though
# they contain the word "agentscope" or live near the gated code.
EXCLUDE_PREFIXES = (
    "docs/",
    ".claude/",
    "scripts/agentscope_guardian_hook.py",
)


def _is_excluded(rel: str) -> bool:
    return any(rel.startswith(pref) for pref in EXCLUDE_PREFIXES)


def _gated(rel: str, content: str) -> bool:
    """Decide whether this edit touches qwenpaw or AgentScope code."""
    if not rel or _is_excluded(rel):
        return False
    # 1) Anything under the qwenpaw package source.
    if "src/qwenpaw/" in rel or rel.startswith("src/qwenpaw/"):
        return True
    # 2) AgentScope library source (vendored / fork), Python only.
    if rel.endswith(".py") and "/agentscope/" in ("/" + rel):
        return True
    # 3) Any Python file that imports agentscope.
    if rel.endswith(".py") and content:
        low = content.lower()
        if "import agentscope" in low or "from agentscope" in low:
            return True
    return False


def _approved(rel: str) -> bool:
    if not os.path.exists(MARKER):
        return False
    now = time.time()
    try:
        with open(MARKER, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                path = parts[0].strip().lower()
                ts = 0.0
                if len(parts) > 1:
                    try:
                        ts = float(parts[1])
                    except ValueError:
                        ts = now  # no/!bad timestamp -> treat as fresh
                else:
                    ts = now
                if path == rel and (now - ts) <= APPROVAL_TTL_SECONDS:
                    return True
    except OSError:
        return False
    return False


def main() -> int:
    if os.environ.get("QWENPAW_GUARDIAN_OFF") == "1":
        return 0
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # never break the harness on malformed input

    tool_input = data.get("tool_input") or data
    file_path = tool_input.get("file_path", "")
    # Content varies by tool: Write uses `content`, Edit uses `new_string`.
    content = tool_input.get("content") or tool_input.get("new_string") or ""

    rel = _norm(file_path)
    if not _gated(rel, content):
        return 0
    if _approved(rel):
        return 0

    sys.stderr.write(
        "[agentscope-guardian] BLOCKED edit to a qwenpaw/AgentScope file:\n"
        f"    {rel}\n\n"
        "This file uses qwenpaw or AgentScope. Before changing it you MUST run the\n"
        "guardian review so the change is checked against the AgentScope v2 knowledge\n"
        "base (docs/agentscope-v2/).\n\n"
        "Do this:\n"
        "  1. Invoke the skill:  /agentscope-guardian\n"
        "     (describe the change + the file path; it reads the relevant KB file,\n"
        "      then returns APPROVE or REJECT with the correct AgentScope v2 API to use).\n"
        "  2. If APPROVED, the guardian records approval and this edit will go through.\n\n"
        "Escape hatch (only if the user explicitly authorizes skipping review):\n"
        "  set QWENPAW_GUARDIAN_OFF=1 for the session.\n",
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
