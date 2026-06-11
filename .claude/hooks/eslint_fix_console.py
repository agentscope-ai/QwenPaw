#!/usr/bin/env python3
"""PostToolUse hook: run `eslint --fix` on edited console TS/TSX files.

Best-effort and non-blocking: any failure exits 0 so it never interrupts the
agent. Complements the existing prettier hook in .claude/settings.json.
"""
import json
import os
import subprocess
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    # Support both flat and nested (tool_input) payload shapes.
    file_path = data.get("file_path") or data.get("tool_input", {}).get(
        "file_path", ""
    )
    if not file_path:
        return 0

    norm = file_path.replace("\\", "/")
    if "/console/" not in norm and not norm.endswith(
        (".ts", ".tsx")
    ):
        return 0
    if not norm.endswith((".ts", ".tsx")):
        return 0
    if "/console/" not in norm:
        return 0

    # Resolve the console package root (the segment up to and incl. /console).
    idx = norm.lower().rfind("/console/")
    console_root = norm[: idx + len("/console")]

    try:
        subprocess.run(
            ["npx", "eslint", "--fix", file_path],
            cwd=console_root,
            timeout=120,
            capture_output=True,
            shell=os.name == "nt",
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
