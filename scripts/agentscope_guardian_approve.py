#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Record an approved AgentScope/qwenpaw edit so the guard hook lets it through.

Usage:
    python scripts/agentscope_guardian_approve.py <file_path> [<file_path> ...]

The `agentscope-guardian` skill calls this ONLY after it has reviewed a change
against docs/agentscope-v2/ and decided to APPROVE it. Each path is normalized
to a repo-relative, forward-slash, lowercased form and appended (with a unix
timestamp) to `.claude/.agentscope-guardian-approved`, which the PreToolUse
guard hook reads. Approvals expire after 24h.
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = os.path.join(REPO, ".claude", ".agentscope-guardian-approved")


def _norm(path: str) -> str:
    p = os.path.abspath(path)
    try:
        p = os.path.relpath(p, REPO)
    except ValueError:
        pass
    return p.replace("\\", "/").lstrip("./").lower()


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write(
            "usage: agentscope_guardian_approve.py <file_path> ...\n",
        )
        return 1
    os.makedirs(os.path.dirname(MARKER), exist_ok=True)
    now = str(time.time())
    with open(MARKER, "a", encoding="utf-8") as fh:
        for raw in sys.argv[1:]:
            fh.write(f"{_norm(raw)}\t{now}\n")
    print(
        f"[agentscope-guardian] approved: {', '.join(_norm(p) for p in sys.argv[1:])}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
