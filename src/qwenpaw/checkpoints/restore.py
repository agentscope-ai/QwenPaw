# -*- coding: utf-8 -*-
"""Transactional restore orchestration for checkpoints."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from .policy import is_qwenpaw_state_path
from .policy import session_file_path, session_key
from .models import CheckpointError, RestorePlan, RestoreResult

if TYPE_CHECKING:
    from .service import CheckpointService

logger = logging.getLogger("qwenpaw.checkpoints")


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
        async with self.service.maintenance_lock:
            if not dry_run:
                self.service.query_gate.clear()
            try:
                async with self.service.lock:
                    return await asyncio.to_thread(
                        self._restore_sync,
                        target,
                        session_id,
                        user_id,
                        channel,
                        dry_run,
                    )
            finally:
                if not dry_run:
                    self.service.query_gate.set()

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
        memory = self._memory_restorer()
        entry = None
        previous_head = None
        pre_ref = None
        pre_commit = None
        mem_restored: list[str] = []
        mem_deleted: list[str] = []
        async with service.maintenance_lock:
            if not dry_run:
                service.query_gate.clear()
            try:
                async with service.lock:
                    entry = service.resolve_target(
                        target,
                        session_id,
                        user_id,
                        channel,
                    )
                    previous_head = service.session_head(skey)
                    conv_blob = service.repository.read_blob(
                        entry.commit,
                        conv_rel,
                    )
                    mem_restored, mem_deleted = memory.plan(entry.commit)
                    plan = RestorePlan(
                        target=target,
                        commit=entry.commit,
                        conversation_path=conv_rel,
                        restore_paths=tuple(mem_restored),
                        delete_paths=tuple(mem_deleted),
                        include_memory=True,
                    )
                    if dry_run:
                        return self._result_from_plan(plan, dry_run=True)

                    # Memory and conversation validation complete before the
                    # safety checkpoint becomes visible in the timeline.
                    pre_snapshot = await asyncio.to_thread(
                        service.create_snapshot_unlocked,
                        "pre-restore",
                        session_id,
                        user_id,
                        channel,
                        None,
                        f"Before memory restore to {target}",
                        None,
                    )
                    pre_ref = pre_snapshot.ref
                    pre_commit = pre_snapshot.commit
                    service.repository.restore_paths({conv_rel: conv_blob})

                mem_restored, mem_deleted = await memory.apply(entry.commit)
                async with service.lock:
                    service.repository.set_session_head(skey, entry.commit)
            except Exception as exc:
                if pre_commit:
                    await self._rollback_failed_restore(
                        exc,
                        pre_commit,
                        paths={conv_rel},
                        include_memory=memory.mutation_started,
                        session_key_str=skey,
                        previous_head=previous_head,
                    )
                raise
            finally:
                if not dry_run:
                    service.query_gate.set()

        assert entry is not None
        return self._result_from_plan(
            plan,
            dry_run=False,
            pre_restore_ref=pre_ref,
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
        memory = self._memory_restorer()
        entry = None
        previous_head = None
        touched: set[str] = set()
        pre_ref = None
        pre_commit = None
        async with service.maintenance_lock:
            if not dry_run:
                service.query_gate.clear()
            try:
                async with service.lock:
                    entry = service.resolve_target(
                        target,
                        session_id,
                        user_id,
                        channel,
                    )
                    previous_head = service.session_head(skey)
                    current_tree = service.repository.write_workspace_tree()
                    touched = self._file_restore_candidates(
                        target_commit=entry.commit,
                        current_tree=current_tree,
                        conv_rel=conv_rel,
                        selected_files=selected_files,
                    )
                    plan = self._build_file_plan(
                        target=target,
                        commit=entry.commit,
                        conversation_path=conv_rel,
                        touched=touched,
                        include_memory=include_memory,
                        memory=memory,
                    )
                    conv_blob = service.repository.read_blob(
                        entry.commit,
                        conv_rel,
                    )

                    if dry_run:
                        return self._result_from_plan(plan, dry_run=True)

                    # No persistent safety state is created until the entire
                    # restore plan and every user-selected path are valid.
                    pre_snapshot = await asyncio.to_thread(
                        service.create_snapshot_unlocked,
                        "pre-restore",
                        session_id,
                        user_id,
                        channel,
                        None,
                        f"Before file restore to {target}",
                        None,
                    )
                    pre_ref = pre_snapshot.ref
                    pre_commit = pre_snapshot.commit
                    service.repository.restore_paths({conv_rel: conv_blob})

                    self._restore_paths_to_commit_sync(
                        entry.commit,
                        touched,
                    )

                if include_memory:
                    await memory.apply(entry.commit)
                async with service.lock:
                    service.repository.set_session_head(skey, entry.commit)
            except Exception as exc:
                if pre_commit:
                    await self._rollback_failed_restore(
                        exc,
                        pre_commit,
                        paths={conv_rel, *touched},
                        include_memory=(
                            include_memory and memory.mutation_started
                        ),
                        session_key_str=skey,
                        previous_head=previous_head,
                    )
                raise
            finally:
                if not dry_run:
                    service.query_gate.set()

        assert entry is not None
        return self._result_from_plan(
            plan,
            dry_run=False,
            pre_restore_ref=pre_ref,
        )

    def _build_file_plan(
        self,
        *,
        target: str,
        commit: str,
        conversation_path: str,
        touched: set[str],
        include_memory: bool,
        memory: "MemoryRestorer",
    ) -> RestorePlan:
        restore_paths, delete_paths = self._plan_paths_to_commit_sync(
            commit,
            touched,
        )
        if include_memory:
            memory_restore, memory_delete = memory.plan(commit)
            restore_paths.extend(memory_restore)
            delete_paths.extend(memory_delete)
        return RestorePlan(
            target=target,
            commit=commit,
            conversation_path=conversation_path,
            restore_paths=tuple(restore_paths),
            delete_paths=tuple(delete_paths),
            file_paths=tuple(sorted(touched)),
            include_memory=include_memory,
            include_files=True,
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

    def _plan_paths_to_commit_sync(
        self,
        commit: str,
        paths: set[str],
    ) -> tuple[list[str], list[str]]:
        restored: list[str] = []
        deleted: list[str] = []
        blob_paths = self.service.repository.tree_blob_paths(commit, paths)
        for rel in sorted(paths):
            if rel not in blob_paths:
                target = self.service.repository.workspace_path(rel)
                if target.exists() or target.is_symlink():
                    deleted.append(rel)
                continue
            blob = self.service.repository.read_blob(commit, rel)
            if not self._same_workspace_content(rel, blob):
                restored.append(rel)
        return restored, deleted

    def _restore_sync(
        self,
        target: str,
        session_id: str,
        user_id: str,
        channel: str,
        dry_run: bool,
    ) -> RestoreResult:
        service = self.service
        entry = service.resolve_target(target, session_id, user_id, channel)
        rel = self._conversation_rel(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        blob = service.repository.read_blob(entry.commit, rel)
        pre_ref = None
        if not dry_run:
            key = session_key(
                channel=channel,
                user_id=user_id,
                session_id=session_id,
            )
            previous_head = service.session_head(key)
            pre_snapshot = service.create_snapshot_unlocked(
                "pre-restore",
                session_id,
                user_id,
                channel,
                None,
                f"Before restore to {target}",
                None,
            )
            pre_ref = pre_snapshot.ref
            pre_commit = pre_snapshot.commit
            try:
                service.repository.restore_paths({rel: blob})
                service.repository.set_session_head(key, entry.commit)
            except Exception:
                try:
                    self._restore_paths_to_commit_sync(pre_commit, {rel})
                    if previous_head:
                        service.repository.set_session_head(key, previous_head)
                except Exception as rollback_exc:
                    raise CheckpointError(
                        "Conversation restore failed and rollback also "
                        "failed; "
                        f"inspect safety checkpoint {pre_ref}.",
                    ) from rollback_exc
                raise
        return RestoreResult(
            target=target,
            commit=entry.commit,
            restored_paths=(rel,),
            pre_restore_ref=pre_ref,
            dry_run=dry_run,
        )

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

    def _restore_paths_to_commit_sync(
        self,
        commit: str,
        paths: set[str],
    ) -> tuple[list[str], list[str]]:
        restored: list[str] = []
        deleted: list[str] = []
        blob_paths = self.service.repository.tree_blob_paths(commit, paths)
        for rel in sorted(paths):
            if rel not in blob_paths:
                if self.service.repository.delete_workspace_path(rel):
                    deleted.append(rel)
                continue
            blob = self.service.repository.read_blob(commit, rel)
            if self._same_workspace_content(rel, blob):
                continue
            target = self.service.repository.workspace_path(rel)
            if target.is_dir() and not target.is_symlink():
                self.service.repository.delete_workspace_path(rel)
            self.service.repository.restore_paths({rel: blob})
            restored.append(rel)
        return restored, deleted

    def _same_workspace_content(self, rel: str, expected: bytes) -> bool:
        target = self.service.repository.workspace_path(rel)
        try:
            if (
                target.is_symlink()
                or not target.is_file()
                or target.stat().st_size != len(expected)
            ):
                return False
            view = memoryview(expected)
            offset = 0
            with target.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    end = offset + len(chunk)
                    if chunk != view[offset:end]:
                        return False
                    offset = end
            return offset == len(expected)
        except OSError:
            return False

    async def _rollback_failed_restore(
        self,
        original: BaseException,
        pre_commit: str,
        *,
        paths: set[str],
        include_memory: bool,
        session_key_str: str,
        previous_head: str | None,
    ) -> None:
        try:
            async with self.service.lock:
                await asyncio.to_thread(
                    self._restore_paths_to_commit_sync,
                    pre_commit,
                    paths,
                )
                if previous_head:
                    self.service.repository.set_session_head(
                        session_key_str,
                        previous_head,
                    )
            if include_memory:
                await self._memory_restorer().apply(pre_commit)
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

    def _memory_restorer(self) -> MemoryRestorer:
        return MemoryRestorer(
            workspace_dir=self.service.workspace_dir,
            git_runner=self.service.repository.run_git,
            read_blob=self.service.repository.read_blob,
            workspace=self.service.workspace,
            quiesce_timeout=self.service.memory_quiesce_timeout,
        )


class MemoryRestorer:
    """Restore ``MEMORY.md`` and ``memory/`` from a checkpoint tree."""

    def __init__(
        self,
        *,
        workspace_dir: Path,
        git_runner,
        read_blob,
        workspace=None,
        quiesce_timeout: float = 30.0,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.git_runner = git_runner
        self.read_blob = read_blob
        self.workspace = workspace
        self.quiesce_timeout = quiesce_timeout
        self.mutation_started = False

    def plan(self, commit: str) -> tuple[list[str], list[str]]:
        """Return only memory files whose contents would actually change."""
        target_paths = self._checkpoint_paths(commit)
        current_paths = self._current_memory_paths()
        would_restore: list[str] = []
        for rel in target_paths:
            content = self.read_blob(commit, rel)
            if not self._same_content(self._target_path(rel), content):
                would_restore.append(rel)
        would_delete = sorted(current_paths - set(target_paths))
        return would_restore, would_delete

    async def apply(self, commit: str) -> tuple[list[str], list[str]]:
        """Shielded memory restore with best-effort workspace quiesce."""
        return await asyncio.shield(self._apply(commit))

    async def _apply(self, commit: str) -> tuple[list[str], list[str]]:
        self.mutation_started = False
        resume_callbacks: list[Callable[[], None]] = []
        if self.workspace is not None:
            resume_callbacks = await self._quiesce_workspace()
        try:
            self.mutation_started = True
            restored, deleted = await asyncio.to_thread(
                self._restore_sync,
                commit,
            )
            logger.info(
                "Memory restore complete: %d restored, %d deleted",
                len(restored),
                len(deleted),
            )
            return restored, deleted
        except Exception:
            logger.exception("Memory restore failed")
            raise
        finally:
            self._resume_workspace(resume_callbacks)

    def _restore_sync(self, commit: str) -> tuple[list[str], list[str]]:
        target_paths = self._checkpoint_paths(commit)
        target_path_set = set(target_paths)
        current_paths = self._current_memory_paths()
        restored: list[str] = []
        deleted: list[str] = []

        for rel in sorted(current_paths - target_path_set):
            target = self._target_path(rel)
            try:
                target.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise CheckpointError(
                    f"Failed to delete memory file {rel}: {exc}",
                ) from exc
            deleted.append(rel)

        for rel in target_paths:
            blob = self.read_blob(commit, rel)
            target = self._target_path(rel)
            if self._same_content(target, blob):
                continue
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write_bytes(target, blob)
            restored.append(rel)

        self._remove_empty_memory_dirs()
        return restored, deleted

    def _checkpoint_paths(self, commit: str) -> list[str]:
        """List checkpoint memory files without loading their contents."""
        paths = [
            *self._list_tree_paths(commit, "MEMORY.md"),
            *self._list_tree_paths(commit, "memory/"),
        ]
        return sorted(set(paths))

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

    @staticmethod
    def _same_content(path: Path, expected: bytes) -> bool:
        try:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != len(expected)
            ):
                return False
            view = memoryview(expected)
            offset = 0
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    end = offset + len(chunk)
                    if chunk != view[offset:end]:
                        return False
                    offset = end
            return offset == len(expected)
        except OSError:
            return False

    def _target_path(self, rel: str) -> Path:
        target = Path(os.path.abspath(self.workspace_dir / rel))
        if not target.is_relative_to(self.workspace_dir):
            raise CheckpointError(
                f"Refusing to restore memory outside workspace: {rel}",
            )
        parent = target.parent
        while parent != self.workspace_dir:
            if parent.is_symlink():
                raise CheckpointError(
                    f"Refusing to follow memory symlink for path: {rel}",
                )
            parent = parent.parent
        return target

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

    def _list_tree_paths(self, commit: str, prefix: str) -> list[str]:
        output = self.git_runner(
            "ls-tree",
            "-r",
            "--name-only",
            commit,
            "--",
            prefix,
        )
        return [line for line in output.splitlines() if line.strip()]

    @staticmethod
    def _atomic_write_bytes(target: Path, content: bytes) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}.mem-",
                suffix=".tmp",
                delete=False,
            ) as tf:
                tf.write(content)
                tf.flush()
                os.fsync(tf.fileno())
                temp_path = Path(tf.name)
            os.replace(temp_path, target)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise CheckpointError(
                f"Failed to restore memory file {target.name}: {exc}",
            ) from exc

    async def _quiesce_workspace(self) -> list[Callable[[], None]]:
        resume_callbacks: list[Callable[[], None]] = []
        workspace = self.workspace

        resume_callbacks.extend(self._pause_workspace_cron(workspace))
        await self._wait_workspace_idle(workspace, resume_callbacks)
        return resume_callbacks

    def _pause_workspace_cron(self, workspace) -> list[Callable[[], None]]:
        resume_callbacks: list[Callable[[], None]] = []
        cron_executor = getattr(workspace, "cron_executor", None)
        if cron_executor is not None and hasattr(cron_executor, "pause"):
            try:
                cron_executor.pause()
                if hasattr(cron_executor, "resume"):
                    resume_callbacks.append(cron_executor.resume)
            except Exception as exc:
                raise CheckpointError(
                    "Memory restore was cancelled because cron could not be "
                    "paused.",
                ) from exc
            return resume_callbacks

        cron_manager = getattr(workspace, "cron_manager", None)
        scheduler = getattr(cron_manager, "_scheduler", None)
        if scheduler is not None and hasattr(scheduler, "pause"):
            try:
                scheduler.pause()
                if hasattr(scheduler, "resume"):
                    resume_callbacks.append(scheduler.resume)
            except Exception as exc:
                raise CheckpointError(
                    "Memory restore was cancelled because the cron "
                    "scheduler could not be paused.",
                ) from exc
        return resume_callbacks

    async def _wait_workspace_idle(
        self,
        workspace,
        resume_callbacks: list[Callable[[], None]],
    ) -> None:
        task_tracker = getattr(workspace, "task_tracker", None)
        if task_tracker is not None and hasattr(task_tracker, "wait_all_idle"):
            try:
                await asyncio.wait_for(
                    task_tracker.wait_all_idle(),
                    timeout=self.quiesce_timeout,
                )
            except asyncio.TimeoutError as exc:
                self._resume_workspace(resume_callbacks)
                raise CheckpointError(
                    "Memory restore was cancelled because workspace tasks did "
                    f"not become idle within {self.quiesce_timeout:.1f}s.",
                ) from exc
            except Exception as exc:
                self._resume_workspace(resume_callbacks)
                raise CheckpointError(
                    "Memory restore was cancelled because workspace idle "
                    "state could not be verified.",
                ) from exc
        elif task_tracker is not None and hasattr(
            task_tracker,
            "list_active_tasks",
        ):
            try:
                await asyncio.wait_for(
                    self._wait_for_other_tasks(task_tracker),
                    timeout=self.quiesce_timeout,
                )
            except asyncio.TimeoutError as exc:
                self._resume_workspace(resume_callbacks)
                raise CheckpointError(
                    "Memory restore was cancelled because workspace tasks did "
                    f"not become idle within {self.quiesce_timeout:.1f}s.",
                ) from exc
            except Exception as exc:
                self._resume_workspace(resume_callbacks)
                raise CheckpointError(
                    "Memory restore was cancelled because active tasks could "
                    "not be inspected.",
                ) from exc

    @staticmethod
    async def _wait_for_other_tasks(task_tracker) -> None:
        while True:
            active = await task_tracker.list_active_tasks()
            if len(active) <= 1:
                return
            await asyncio.sleep(0.5)

    @staticmethod
    def _resume_workspace(callbacks: list[Callable[[], None]]) -> None:
        for resume in reversed(callbacks):
            try:
                resume()
            except Exception:
                logger.debug("Failed to resume cron", exc_info=True)
