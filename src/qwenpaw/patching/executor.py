# -*- coding: utf-8 -*-
"""Ordered, staged patch commits with best-effort rollback."""

from __future__ import annotations

import os
import secrets
import shutil
from contextlib import AsyncExitStack
from pathlib import Path

from ..utils.io_utils import get_path_lock, run_sync_io
from .errors import PatchError
from .models import PatchDocument, PatchPlan, PatchResult
from .planner import build_plan, resolve_patch_paths


def _sibling(path: Path, suffix: str) -> Path:
    return path.with_name(f".{path.name}.{secrets.token_hex(8)}.{suffix}")


def _write_stage(path: Path, content: bytes, mode: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = _sibling(path, "patch-stage")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(stage, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        stage.chmod(mode)
        return stage
    except BaseException:
        stage.unlink(missing_ok=True)
        raise


def _commit(plan: PatchPlan) -> None:
    stages: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    committed: list[Path] = []
    created_directories: set[Path] = set()
    succeeded = False
    try:
        for mutation in plan.mutations:
            if mutation.content is not None:
                parent = mutation.path.parent
                while not parent.exists():
                    created_directories.add(parent)
                    parent = parent.parent
                stages[mutation.path] = _write_stage(
                    mutation.path,
                    mutation.content,
                    mutation.mode,
                )
        for mutation in plan.mutations:
            path = mutation.path
            if path.exists():
                backup = _sibling(path, "patch-backup")
                shutil.copy2(path, backup)
                backups[path] = backup
            else:
                backups[path] = None
        for mutation in plan.mutations:
            path = mutation.path
            if mutation.content is None:
                path.unlink(missing_ok=False)
            else:
                stage = stages[path]
                os.replace(stage, path)
                del stages[path]
            committed.append(path)
        succeeded = True
    except BaseException as exc:
        rollback_errors: list[str] = []
        for path in reversed(committed):
            backup = backups.get(path)
            try:
                if backup is None:
                    path.unlink(missing_ok=True)
                elif backup.exists():
                    os.replace(backup, path)
                    backups[path] = None
            except OSError as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        raise PatchError(
            "commit_error",
            f"Patch commit failed: {exc}",
            rolled_back=not rollback_errors,
            rollback_errors=tuple(rollback_errors),
        ) from exc
    finally:
        for temporary in (*stages.values(), *(p for p in backups.values() if p)):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        if not succeeded:
            for directory in sorted(
                created_directories,
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                try:
                    directory.rmdir()
                except OSError:
                    pass


async def apply_patch_document(root: Path, document: PatchDocument) -> PatchResult:
    """Validate and apply a document while holding every target path lock."""
    resolved = await run_sync_io(resolve_patch_paths, root, document)
    lock_paths = sorted(set(resolved.values()), key=lambda path: str(path))
    async with AsyncExitStack() as stack:
        for path in lock_paths:
            await stack.enter_async_context(get_path_lock(path))

        def plan_and_commit() -> PatchPlan:
            plan = build_plan(root, document, resolved)
            _commit(plan)
            return plan

        plan = await run_sync_io(plan_and_commit)
    return PatchResult(
        "applied",
        files=plan.files,
        hunks_applied=plan.hunks_applied,
    )
