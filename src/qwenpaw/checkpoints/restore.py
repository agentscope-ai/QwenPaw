# -*- coding: utf-8 -*-
"""Transactional restore orchestration for checkpoints."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ..utils.io_utils import run_sync_io

from .policy import is_qwenpaw_state_path
from .policy import session_file_path, session_key
from .models import (
    CheckpointEntry,
    CheckpointError,
    RestorePlan,
    RestoreResult,
)

if TYPE_CHECKING:
    from .service import CheckpointService

logger = logging.getLogger("qwenpaw.checkpoints")


@dataclass(frozen=True)
class _PreparedRestore:
    entry: CheckpointEntry
    previous_head: str | None
    plan: RestorePlan
    conversation_blob: bytes
    touched: frozenset[str]
    current_tree: str | None = None


def _changed_paths(
    repository,
    *,
    target_commit: str,
    current_commit: str | None,
) -> set[str]:
    """Return paths changed between two checkpoint trees."""
    if not current_commit or current_commit == target_commit:
        return set()
    output = repository.run_git(
        "diff-tree",
        "--name-status",
        "-r",
        "--no-commit-id",
        "-M",
        target_commit,
        current_commit,
    )
    paths: set[str] = set()
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            paths.add(parts[-1])
        if parts and parts[0].startswith("R") and len(parts) >= 3:
            paths.add(parts[1])
    return paths


class WorkspaceMutationGuard:
    """Pause cooperative workspace writers for one restore transaction."""

    def __init__(self, workspace, *, timeout: float) -> None:
        self.workspace = workspace
        self.timeout = timeout

    async def quiesce(self) -> list[Callable[[], None]]:
        """Pause cron and wait until tracked workspace tasks are idle."""
        resume_callbacks = self._pause_workspace_cron()
        try:
            await self._wait_workspace_idle()
        except BaseException:
            self.resume(resume_callbacks)
            raise
        return resume_callbacks

    def _pause_workspace_cron(self) -> list[Callable[[], None]]:
        resume_callbacks: list[Callable[[], None]] = []
        cron_executor = getattr(self.workspace, "cron_executor", None)
        if cron_executor is not None and hasattr(cron_executor, "pause"):
            try:
                cron_executor.pause()
                if hasattr(cron_executor, "resume"):
                    resume_callbacks.append(cron_executor.resume)
            except Exception as exc:
                raise CheckpointError(
                    "Checkpoint restore was cancelled because cron could "
                    "not be paused.",
                ) from exc
            return resume_callbacks

        cron_manager = getattr(self.workspace, "cron_manager", None)
        scheduler = getattr(cron_manager, "_scheduler", None)
        if scheduler is not None and hasattr(scheduler, "pause"):
            try:
                scheduler.pause()
                if hasattr(scheduler, "resume"):
                    resume_callbacks.append(scheduler.resume)
            except Exception as exc:
                raise CheckpointError(
                    "Checkpoint restore was cancelled because the cron "
                    "scheduler could not be paused.",
                ) from exc
        return resume_callbacks

    async def _wait_workspace_idle(self) -> None:
        task_tracker = getattr(self.workspace, "task_tracker", None)
        if task_tracker is not None and hasattr(
            task_tracker,
            "has_active_tasks_excluding",
        ):
            try:
                async with asyncio.timeout(self.timeout):
                    await self._wait_for_other_tasks(
                        task_tracker,
                        asyncio.current_task(),
                    )
            except TimeoutError as exc:
                raise CheckpointError(
                    "Checkpoint restore was cancelled because workspace "
                    f"tasks did not become idle within {self.timeout:.1f}s.",
                ) from exc
            except Exception as exc:
                raise CheckpointError(
                    "Checkpoint restore was cancelled because active tasks "
                    "could not be inspected.",
                ) from exc
        elif task_tracker is not None and hasattr(
            task_tracker,
            "wait_all_idle",
        ):
            try:
                await asyncio.wait_for(
                    task_tracker.wait_all_idle(),
                    timeout=self.timeout,
                )
            except asyncio.TimeoutError as exc:
                raise CheckpointError(
                    "Checkpoint restore was cancelled because workspace "
                    f"tasks did not become idle within {self.timeout:.1f}s.",
                ) from exc
            except Exception as exc:
                raise CheckpointError(
                    "Checkpoint restore was cancelled because workspace "
                    "idle state could not be verified.",
                ) from exc
        elif task_tracker is not None and hasattr(
            task_tracker,
            "list_active_tasks",
        ):
            try:
                await asyncio.wait_for(
                    self._wait_for_no_active_tasks(task_tracker),
                    timeout=self.timeout,
                )
            except asyncio.TimeoutError as exc:
                raise CheckpointError(
                    "Checkpoint restore was cancelled because workspace "
                    f"tasks did not become idle within {self.timeout:.1f}s.",
                ) from exc
            except Exception as exc:
                raise CheckpointError(
                    "Checkpoint restore was cancelled because active tasks "
                    "could not be inspected.",
                ) from exc

    @staticmethod
    async def _wait_for_other_tasks(
        task_tracker,
        restore_task: asyncio.Task | None,
    ) -> None:
        while await task_tracker.has_active_tasks_excluding(restore_task):
            await asyncio.sleep(0.5)

    @staticmethod
    async def _wait_for_no_active_tasks(task_tracker) -> None:
        while True:
            active = await task_tracker.list_active_tasks()
            if not active:
                return
            await asyncio.sleep(0.5)

    @staticmethod
    def resume(callbacks: list[Callable[[], None]]) -> None:
        """Resume paused writers in reverse acquisition order."""
        for callback in reversed(callbacks):
            try:
                callback()
            except Exception:
                logger.debug("Failed to resume cron", exc_info=True)


class RestoreService:
    """Plan, apply, and roll back checkpoint restores."""

    def __init__(self, service: "CheckpointService") -> None:
        self.service = service
        self.repository = service.repository

    async def restore(
        self,
        *,
        target: str | None,
        session_id: str,
        user_id: str,
        channel: str,
        dry_run: bool = False,
    ) -> RestoreResult:
        """Restore only the current conversation session file."""
        if not target:
            raise CheckpointError(
                "Usage: /checkpoint restore <N | snap_name | sha> "
                "[--dry-run | --confirm]",
            )
        return await self._run_restore(
            target=target,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            dry_run=dry_run,
        )

    async def restore_with_memory(
        self,
        *,
        target: str | None,
        session_id: str,
        user_id: str,
        channel: str,
        dry_run: bool = False,
    ) -> RestoreResult:
        """Restore conversation + MEMORY.md + memory/ to a checkpoint."""
        if not target:
            raise CheckpointError(
                "Usage: /checkpoint restore <target> --include-memory "
                "--confirm",
            )
        return await self._run_restore(
            target=target,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            include_memory=True,
            dry_run=dry_run,
        )

    async def restore_with_files(
        self,
        *,
        target: str | None,
        session_id: str,
        user_id: str,
        channel: str,
        include_memory: bool = False,
        selected_files: tuple[str, ...] | None = None,
        dry_run: bool = False,
    ) -> RestoreResult:
        """Restore conversation and workspace files to a checkpoint tree."""
        if not target:
            raise CheckpointError(
                "Usage: /checkpoint restore <target> --include-files "
                "--confirm",
            )
        if not dry_run and selected_files is None:
            raise CheckpointError(
                "Applying workspace-file restore requires an explicit "
                "`--files` selection.",
            )
        return await self._run_restore(
            target=target,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            include_memory=include_memory,
            include_files=True,
            selected_files=selected_files,
            dry_run=dry_run,
        )

    async def _run_restore(
        self,
        *,
        target: str,
        session_id: str,
        user_id: str,
        channel: str,
        include_memory: bool = False,
        include_files: bool = False,
        selected_files: tuple[str, ...] | None = None,
        dry_run: bool = False,
    ) -> RestoreResult:
        """Run one validated restore transaction."""
        service = self.service
        conv_rel = self._conversation_rel(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        skey = session_key(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
        )
        memory = (
            await run_sync_io(self._memory_restorer)
            if include_memory
            else None
        )
        mutation_guard = (
            self._workspace_mutation_guard() if not dry_run else None
        )
        prepared: _PreparedRestore | None = None
        pre_ref: str | None = None
        resume_callbacks: list[Callable[[], None]] = []
        async with service.maintenance_lock:
            if not dry_run:
                service.query_gate.clear()
            try:
                async with service.lock:
                    if mutation_guard is not None:
                        resume_callbacks = await mutation_guard.quiesce()
                    prepared = await run_sync_io(
                        self._prepare_restore,
                        target=target,
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        session_key_str=skey,
                        conversation_path=conv_rel,
                        include_memory=include_memory,
                        include_files=include_files,
                        selected_files=selected_files,
                        memory=memory,
                    )

                    if dry_run:
                        return self._result_from_plan(
                            prepared.plan,
                            dry_run=True,
                        )

                    if include_files:
                        description = f"Before file restore to {target}"
                    elif include_memory:
                        description = f"Before memory restore to {target}"
                    else:
                        description = f"Before restore to {target}"

                    pre_ref = await run_sync_io(
                        self._apply_restore_transaction_sync,
                        prepared,
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        session_key_str=skey,
                        conversation_path=conv_rel,
                        include_files=include_files,
                        description=description,
                        memory=memory,
                    )
            finally:
                if mutation_guard is not None:
                    mutation_guard.resume(resume_callbacks)
                if not dry_run:
                    service.query_gate.set()

        assert prepared is not None
        return self._result_from_plan(
            prepared.plan,
            dry_run=False,
            pre_restore_ref=pre_ref,
        )

    def _apply_restore_transaction_sync(
        self,
        prepared: _PreparedRestore,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        session_key_str: str,
        conversation_path: str,
        include_files: bool,
        description: str,
        memory: "MemoryRestorer | None",
    ) -> str:
        """Apply and, on failure, roll back all repository mutations."""
        pre_snapshot = None
        try:
            pre_snapshot = self.service.create_snapshot_unlocked(
                "pre-restore",
                session_id,
                user_id,
                channel,
                None,
                description,
                None,
                tree_override=(
                    prepared.current_tree if include_files else None
                ),
            )
            self.repository.restore_internal_paths(
                {conversation_path: prepared.conversation_blob},
            )
            if include_files:
                self.repository.restore_tree_paths(
                    prepared.entry.commit,
                    set(prepared.touched),
                )
            if memory is not None:
                memory.mutation_started = True
                memory.restore_sync(prepared.entry.commit)
            self.repository.set_session_head(
                session_key_str,
                prepared.entry.commit,
            )
            return pre_snapshot.ref
        except Exception as exc:
            if pre_snapshot is not None:
                self._rollback_restore_transaction_sync(
                    original=exc,
                    pre_commit=pre_snapshot.commit,
                    conversation_path=conversation_path,
                    file_paths=set(prepared.touched),
                    include_memory=(
                        memory is not None and memory.mutation_started
                    ),
                    session_key_str=session_key_str,
                    previous_head=prepared.previous_head,
                    memory=memory,
                )
            raise

    def _rollback_restore_transaction_sync(
        self,
        *,
        original: BaseException,
        pre_commit: str,
        conversation_path: str,
        file_paths: set[str],
        include_memory: bool,
        session_key_str: str,
        previous_head: str | None,
        memory: "MemoryRestorer | None",
    ) -> None:
        try:
            conversation = self.repository.read_blob(
                pre_commit,
                conversation_path,
            )
            self.repository.restore_internal_paths(
                {conversation_path: conversation},
            )
            self.repository.restore_tree_paths(pre_commit, file_paths)
            if include_memory and memory is not None:
                memory.restore_sync(pre_commit)
            if previous_head is None:
                self.repository.remove_session_heads({session_key_str})
            else:
                self.repository.set_session_head(
                    session_key_str,
                    previous_head,
                )
        except Exception as rollback_exc:
            logger.exception("Checkpoint restore rollback failed")
            raise CheckpointError(
                "Restore failed and rollback to the pre-restore checkpoint "
                "also failed; inspect the pre-restore ref manually.",
            ) from rollback_exc
        logger.info(
            "Rolled back failed checkpoint restore after error: %s",
            original,
        )

    def _prepare_restore(
        self,
        *,
        target: str,
        session_id: str,
        user_id: str,
        channel: str,
        session_key_str: str,
        conversation_path: str,
        include_memory: bool,
        include_files: bool,
        selected_files: tuple[str, ...] | None,
        memory: "MemoryRestorer | None",
    ) -> _PreparedRestore:
        entry = self.service.resolve_target(
            target,
            session_id,
            user_id,
            channel,
        )
        previous_head = self.service.session_head(session_key_str)
        touched: set[str] = set()
        current_tree: str | None = None
        if include_files:
            current_tree = self.repository.write_workspace_tree()
            assert current_tree is not None
            touched = self._file_restore_candidates(
                target_commit=entry.commit,
                current_tree=current_tree,
                conv_rel=conversation_path,
                selected_files=selected_files,
            )
        plan = self._build_plan(
            target=target,
            commit=entry.commit,
            conversation_path=conversation_path,
            touched=touched,
            include_memory=include_memory,
            include_files=include_files,
            memory=memory,
        )
        conversation = self.repository.read_blob(
            entry.commit,
            conversation_path,
        )
        return _PreparedRestore(
            entry=entry,
            previous_head=previous_head,
            plan=plan,
            conversation_blob=conversation,
            touched=frozenset(touched),
            current_tree=current_tree,
        )

    def _build_plan(
        self,
        *,
        target: str,
        commit: str,
        conversation_path: str,
        touched: set[str],
        include_memory: bool,
        include_files: bool,
        memory: "MemoryRestorer | None",
    ) -> RestorePlan:
        restored: list[str] = []
        deleted: list[str] = []
        if include_files:
            restored, deleted = self.repository.plan_tree_restore(
                commit,
                touched,
            )
        if memory is not None:
            memory_restore, memory_delete = memory.plan(commit)
            restored.extend(memory_restore)
            deleted.extend(memory_delete)
        return RestorePlan(
            target=target,
            commit=commit,
            conversation_path=conversation_path,
            restore_paths=tuple(restored),
            delete_paths=tuple(deleted),
            file_paths=tuple(sorted(touched)) if include_files else (),
            include_memory=include_memory,
            include_files=include_files,
        )

    @staticmethod
    def _result_from_plan(
        plan: RestorePlan,
        *,
        dry_run: bool,
        pre_restore_ref: str | None = None,
    ) -> RestoreResult:
        return RestoreResult(
            target=plan.target,
            commit=plan.commit,
            restored_paths=(
                plan.conversation_path,
                *plan.restore_paths,
            ),
            pre_restore_ref=pre_restore_ref,
            dry_run=dry_run,
            include_memory=plan.include_memory,
            include_files=plan.include_files,
            deleted_paths=plan.delete_paths,
            file_paths=plan.file_paths,
        )

    def _file_restore_candidates(
        self,
        *,
        target_commit: str,
        current_tree: str,
        conv_rel: str,
        selected_files: tuple[str, ...] | None,
    ) -> set[str]:
        touched = _changed_paths(
            self.repository,
            target_commit=target_commit,
            current_commit=current_tree,
        )
        candidates = {
            rel
            for rel in touched
            if self._is_file_restore_candidate(rel, conv_rel=conv_rel)
        }
        if selected_files is None:
            return candidates

        selected = {
            self._normalize_selected_file(rel, conv_rel=conv_rel)
            for rel in selected_files
        }
        unavailable = selected - candidates
        if unavailable:
            rendered = ", ".join(f"`{rel}`" for rel in sorted(unavailable))
            raise CheckpointError(
                "Selected file(s) are not changed between the target "
                f"checkpoint and the current workspace: {rendered}.",
            )
        return selected

    @classmethod
    def _normalize_selected_file(cls, rel: str, *, conv_rel: str) -> str:
        normalized = (rel or "").strip().replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or path.is_absolute()
            or ".." in path.parts
            or (path.parts and path.parts[0].endswith(":"))
        ):
            raise CheckpointError(
                f"`--files` path must be workspace-relative: `{rel}`.",
            )
        normalized = path.as_posix().removeprefix("./")
        if not cls._is_file_restore_candidate(normalized, conv_rel=conv_rel):
            raise CheckpointError(
                f"`--files` cannot restore QwenPaw state path `{rel}`.",
            )
        return normalized

    def _conversation_rel(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> str:
        conv_path = session_file_path(
            self.service.workspace_dir,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        return conv_path.relative_to(self.service.workspace_dir).as_posix()

    @staticmethod
    def _is_file_restore_candidate(rel: str, *, conv_rel: str) -> bool:
        if not rel or rel == conv_rel:
            return False
        if rel.startswith("sessions/"):
            return False
        if rel == "MEMORY.md" or rel.startswith("memory/"):
            return False
        if is_qwenpaw_state_path(rel):
            return False
        return True

    def _memory_restorer(self) -> MemoryRestorer:
        return MemoryRestorer(repository=self.repository)

    def _workspace_mutation_guard(self) -> WorkspaceMutationGuard:
        return WorkspaceMutationGuard(
            workspace=self.service.workspace,
            timeout=self.service.memory_quiesce_timeout,
        )


class MemoryRestorer:
    """Restore ``MEMORY.md`` and ``memory/`` from a checkpoint tree."""

    def __init__(
        self,
        *,
        repository,
    ) -> None:
        self.repository = repository
        self.workspace_dir = repository.workspace_dir
        self.mutation_started = False

    def plan(self, commit: str) -> tuple[list[str], list[str]]:
        """Return only memory files whose contents would actually change."""
        target_paths = self._checkpoint_paths(commit)
        current_paths = self._current_memory_paths()
        return self.repository.plan_tree_restore(
            commit,
            current_paths | set(target_paths),
        )

    def restore_sync(self, commit: str) -> tuple[list[str], list[str]]:
        target_paths = self._checkpoint_paths(commit)
        current_paths = self._current_memory_paths()
        restored, deleted = self.repository.restore_tree_paths(
            commit,
            current_paths | set(target_paths),
        )
        self._remove_empty_memory_dirs()
        return restored, deleted

    def _checkpoint_paths(self, commit: str) -> list[str]:
        """List checkpoint memory files without loading their contents."""
        return self.repository.list_tree_paths(
            commit,
            "MEMORY.md",
            "memory/",
        )

    def _current_memory_paths(self) -> set[str]:
        paths: set[str] = set()
        memory_md = self.workspace_dir / "MEMORY.md"
        memory_dir = self.workspace_dir / "memory"
        if memory_md.is_file() or memory_md.is_symlink():
            paths.add("MEMORY.md")
        if memory_dir.exists():
            for root, dirs, files in os.walk(memory_dir):
                for dirname in list(dirs):
                    path = Path(root, dirname)
                    if path.is_symlink():
                        paths.add(
                            path.relative_to(self.workspace_dir).as_posix(),
                        )
                        dirs.remove(dirname)
                for fname in files:
                    paths.add(
                        Path(root, fname)
                        .relative_to(
                            self.workspace_dir,
                        )
                        .as_posix(),
                    )
        return paths

    def _remove_empty_memory_dirs(self) -> None:
        memory_dir = self.workspace_dir / "memory"
        if not memory_dir.is_dir():
            return
        for root, _dirs, _files in os.walk(memory_dir, topdown=False):
            path = Path(root)
            try:
                path.rmdir()
            except OSError:
                pass
