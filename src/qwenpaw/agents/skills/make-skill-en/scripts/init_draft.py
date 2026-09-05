#!/usr/bin/env python3
"""Create a private draft for an approved make-skill v2 plan."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
from pathlib import Path
from typing import Any

import create_plan


def _input_error(code: str, path: str, message: str) -> create_plan.InputError:
    return create_plan.InputError([create_plan.error(code, path, message)])


def resolve_workspace(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise _input_error(
            "required-workspace",
            "workspace",
            "Must be a non-empty path string.",
        )
    candidate = Path(value).expanduser()
    if candidate.is_symlink():
        raise _input_error(
            "workspace-symlink",
            "workspace",
            "The workspace must not be a symbolic link.",
        )
    try:
        workspace = candidate.resolve(strict=True)
    except OSError:
        raise _input_error(
            "workspace-not-found",
            "workspace",
            "Must be an existing directory.",
        ) from None
    if not workspace.is_dir():
        raise _input_error(
            "workspace-not-directory",
            "workspace",
            "Must be an existing directory.",
        )
    return workspace


def private_drafts_root(workspace: Path, *, create: bool) -> Path:
    current = workspace
    for part in (".qwenpaw", "make-skill", "drafts"):
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"Private draft path is a symlink: {current}")
        if current.exists() and not current.is_dir():
            raise RuntimeError(f"Private draft path is not a directory: {current}")
        if create:
            current.mkdir(mode=0o700, exist_ok=True)
    return current


def _write_plan(path: Path, plan: dict[str, Any]) -> None:
    temporary = path.with_name(f".plan-{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(plan, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def initialize(workspace: Path, plan: dict[str, Any]) -> dict[str, Any]:
    draft_base = private_drafts_root(workspace, create=True)
    draft_root: Path | None = None
    for _ in range(10):
        candidate = draft_base / secrets.token_hex(12)
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            continue
        draft_root = candidate
        break
    if draft_root is None:
        raise RuntimeError("Could not allocate a unique draft id.")

    try:
        skill_dir = draft_root / plan["name"]
        skill_dir.mkdir(mode=0o700)
        _write_plan(draft_root / "plan.json", plan)
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
            raise _input_error("invalid-input", "", "Input must be a JSON object.")
        unknown = sorted(set(payload) - {"workspace", "plan"})
        if unknown:
            raise _input_error(
                "unknown-field",
                unknown[0],
                "Not part of the draft initialization contract.",
            )
        workspace = resolve_workspace(payload.get("workspace"))
        plan = create_plan.normalize_plan(payload.get("plan"))
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
        result = initialize(workspace, plan)
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
