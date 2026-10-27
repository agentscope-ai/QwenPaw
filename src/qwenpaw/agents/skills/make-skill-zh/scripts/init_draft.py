#!/usr/bin/env python3
"""Create a private draft for an approved make-skill v2 plan."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

import create_plan


def initialize(workspace: Path, plan_id: Any) -> dict[str, Any]:
    # Resolve the stored plan before creating any draft directories.
    plan = create_plan.load_plan(workspace, plan_id)
    draft_root = create_plan.allocate_directory(
        workspace, "drafts", plan["name"]
    )

    try:
        skill_dir = draft_root / plan["name"]
        skill_dir.mkdir(mode=0o700)
        create_plan.write_plan_snapshot(draft_root / "plan.json", plan)
    except Exception:
        shutil.rmtree(draft_root, ignore_errors=True)
        raise

    return {
        "ok": True,
        "stage": "draft",
        "draft_id": draft_root.name,
        "skill_dir": str(skill_dir),
        "planned_files": plan["package"],
        "errors": [],
        "warnings": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        help="Read JSON from this file instead of stdin.",
    )
    args = parser.parse_args()
    try:
        payload = create_plan.load_json_input(args.input)
        if not isinstance(payload, dict):
            raise create_plan.input_error(
                "invalid-input",
                "",
                "Input must be a JSON object.",
            )
        unknown = sorted(set(payload) - {"workspace", "plan_id"})
        if unknown:
            raise create_plan.input_error(
                "unknown-field",
                unknown[0],
                "Not part of the draft initialization contract.",
            )
        workspace = create_plan.resolve_workspace(payload.get("workspace"))
    except create_plan.InputError as exc:
        create_plan.emit(
            {
                "ok": False,
                "stage": "draft",
                "errors": exc.errors,
                "warnings": [],
            },
        )
        return 2

    try:
        result = initialize(workspace, payload.get("plan_id"))
    except create_plan.InputError as exc:
        create_plan.emit(
            {
                "ok": False,
                "stage": "draft",
                "errors": exc.errors,
                "warnings": [],
            },
        )
        return 3
    except Exception as exc:
        create_plan.emit(
            {
                "ok": False,
                "stage": "draft",
                "errors": [
                    create_plan.error(
                        "draft-create-failed",
                        "workspace",
                        str(exc),
                    ),
                ],
                "warnings": [],
            },
        )
        return 5
    create_plan.emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
