# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_policy(
    protected_paths: list[str],
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    return {
        "version": 1,
        "workspaceRoot": str(workspace_root.resolve()),
        "targets": [
            {"path": path, "mode": "alert"}
            for path in protected_paths
        ],
    }
