# -*- coding: utf-8 -*-
"""Update owned configuration references to the user's workspace policy."""

from __future__ import annotations

import json
import sys

from ..utils.io_utils import write_json_atomic
from .models import RuntimeRecord
from .user_profile import runtime_workspace


def prepare_workspace_paths(record: RuntimeRecord, previous: str) -> None:
    """Relocate directory fields on restart without changing user content."""
    root = record.working_dir.resolve()
    target = (
        runtime_workspace(record)
        if record.provisioner == "docker" or sys.platform == "linux"
        else str(root)
    )
    # The former Docker mount is an input to migration, never a new alias.
    sources = (str(root), previous, "/app/working")

    def relocate(value):
        if not isinstance(value, str):
            return value
        normalized = value.replace("\\", "/")
        for source in sources:
            prefix = source.replace("\\", "/").rstrip("/")
            candidate = normalized
            if len(prefix) > 1 and prefix[1] == ":":
                candidate, prefix = candidate.casefold(), prefix.casefold()
            if candidate == prefix or candidate.startswith(f"{prefix}/"):
                return f"{target}{normalized[len(prefix):]}"
        return value

    def rewrite(value):
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in {"workspace_dir", "project_dir"}:
                result[key] = relocate(item)
            elif key == "project_dirs" and isinstance(item, list):
                result[key] = [
                    {**entry, "path": relocate(entry["path"])}
                    if isinstance(entry, dict) and "path" in entry
                    else entry
                    for entry in item
                ]
            else:
                result[key] = rewrite(item)
        return result

    for path in [root / "config.json", *root.glob("workspaces/*/agent.json")]:
        if not path.resolve().is_relative_to(root):
            raise ValueError(
                "Runtime configuration escapes its data directory",
            )
        if not path.is_file():
            continue
        original = json.loads(path.read_text(encoding="utf-8"))
        updated = rewrite(original)
        if updated != original:
            write_json_atomic(path, updated)
