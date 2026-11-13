"""Use the installed QwenPaw CLI without importing its Python package."""

from __future__ import annotations

import json
import subprocess
from typing import Any


def skills(*arguments: str) -> dict[str, Any]:
    try:
        process = subprocess.run(
            ["qwenpaw", "skills", *arguments, "--json"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"Cannot start the QwenPaw CLI: {exc}") from exc
    try:
        result = json.loads(process.stdout)
        if not isinstance(result, dict) or not isinstance(
            result.get("ok"), bool
        ):
            raise ValueError("Expected a JSON result with an 'ok' boolean.")
        if result["ok"] != (process.returncode == 0):
            raise ValueError("The CLI result and exit code disagree.")
    except ValueError as exc:
        detail = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(
            f"QwenPaw CLI did not return a valid JSON result: {detail or exc}",
        ) from exc
    return result
