# -*- coding: utf-8 -*-
"""Checkpoint application service: snapshot, timeline, GC, and reset."""

# Synchronous Git helpers run through run_sync_io.
# pylint: disable=too-many-arguments
# pylint: disable=too-many-public-methods

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from agentscope.state import AgentState
from pydantic import ValidationError

from ..utils.io_utils import run_sync_io, write_text_atomic

from .policy import (
    DEFAULT_AUTO_DEBOUNCE_SECONDS,
    DEFAULT_GC_KEEP_COUNT,
    DEFAULT_GC_KEEP_DAYS,
    DEFAULT_MEMORY_QUIESCE_TIMEOUT,
    DEFAULT_PRE_RESTORE_RETENTION_DAYS,
    DEFAULT_QUERY_PREVIEW_CHARS,
    DEFAULT_TIMELINE_LIMIT,
    DEFAULT_TIMELINE_MAX_LIMIT,
    CheckpointPolicy,
)
from .policy import (
    encode_metadata,
    latest_user_query,
    metadata_from_commit_message,
    query_from_commit_message,
    ref_kind,
    ref_session_key,
    sanitize_ref_component,
    session_key,
    session_file_path,
)
from .models import (
    CheckpointEntry,
    CheckpointError,
    GcResult,
    RestoreResult,
    SnapshotResult,
)
from .restore import RestoreService
from .repository import CheckpointRepository

logger = logging.getLogger("qwenpaw.checkpoints")

_REF_FIELD_SEPARATOR = "\x1f"
_REF_RECORD_SEPARATOR = "\x1e"


@dataclass(frozen=True)
class _RefRecord:
    ref: str
    commit: str
    timestamp_ms: int
    message: str


class CheckpointService:
    """Coordinate checkpoint use cases for one workspace."""

    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        repository: CheckpointRepository | None = None,
        policy: CheckpointPolicy | None = None,
    ):
        self.repository = repository or CheckpointRepository(workspace_dir)
        self.policy = policy or CheckpointPolicy(self.repository.config_file)
        # Set by the registry when a live request is available; mutating
        # restores need it to quiesce tasks and pause cron.
        self._workspace_ref = None
        self._workspace_fallback = None
        self.agent_id = ""
        self.checkpoint_scope = "agent_workspace"
        self.conversation_workspace_dir = self.repository.workspace_dir
        self.query_gate = asyncio.Event()
        self.query_gate.set()
        self.lock = asyncio.Lock()
        self.maintenance_lock = asyncio.Lock()
        self._copy_maintenance_owner: asyncio.Task | None = None
        self._restores = RestoreService(self)

    @property
    def workspace_dir(self) -> Path:
        """Workspace root managed by this service."""
        return self.repository.workspace_dir

    @property
    def workspace(self):
        """Return the live workspace without retaining it indefinitely."""
        if self._workspace_ref is not None:
            return self._workspace_ref()
        return self._workspace_fallback

    @workspace.setter
    def workspace(self, value) -> None:
        self._workspace_ref = None
        self._workspace_fallback = None
        if value is None:
            return
        try:
            self._workspace_ref = weakref.ref(value)
        except TypeError:
            # Some slot-only integrations cannot be weak-referenced.
            self._workspace_fallback = value

    # -- config -----------------------------------------------------------

    @property
    def auto_enabled(self) -> bool:
        return self.policy.boolean("auto", "enabled", False)

    async def auto_settings(self) -> tuple[bool, float]:
        """Return auto-snapshot settings without blocking the event loop."""
        return await run_sync_io(
            lambda: (self.auto_enabled, self.auto_debounce_seconds),
        )

    async def set_auto_enabled(self, enabled: bool) -> tuple[bool, float]:
        """Toggle auto-snapshot and return its effective settings."""

        def _set() -> tuple[bool, float]:
            self.policy.set_auto_enabled(enabled)
            return self.auto_enabled, self.auto_debounce_seconds

        return await run_sync_io(_set)

    def _gc_settings_sync(self) -> dict[str, int]:
        """Return effective automatic cleanup settings in a worker."""
        return {
            "gc_keep_count": self.gc_keep_count,
            "gc_keep_days": self.gc_keep_days,
            "pre_restore_retention_days": self.pre_restore_retention_days,
        }

    async def gc_settings(self) -> dict[str, int]:
        """Return automatic cleanup settings off the event loop."""
        return await run_sync_io(self._gc_settings_sync)

    async def set_gc_settings(
        self,
        *,
        gc_keep_count: int,
        gc_keep_days: int,
        pre_restore_retention_days: int,
    ) -> dict[str, int]:
        """Persist and return automatic cleanup settings."""

        def _set() -> dict[str, int]:
            self.policy.set_gc_retention(
                gc_keep_count=gc_keep_count,
                gc_keep_days=gc_keep_days,
                pre_restore_retention_days=pre_restore_retention_days,
            )
            return self._gc_settings_sync()

        return await run_sync_io(_set)

    async def timeline_settings(self) -> tuple[int, int, int]:
        """Return timeline limits and preview length off the event loop."""
        return await run_sync_io(
            lambda: (
                self.timeline_default_limit,
                self.timeline_max_limit,
                self.query_preview_chars,
            ),
        )

    @property
    def auto_debounce_seconds(self) -> float:
        return self.policy.number(
            "auto",
            "debounce_seconds",
            DEFAULT_AUTO_DEBOUNCE_SECONDS,
            minimum=0.0,
            maximum=300.0,
        )

    @property
    def timeline_default_limit(self) -> int:
        return self.policy.number(
            "timeline",
            "default_limit",
            DEFAULT_TIMELINE_LIMIT,
            minimum=1,
            maximum=self.timeline_max_limit,
        )

    @property
    def timeline_max_limit(self) -> int:
        return self.policy.number(
            "timeline",
            "max_limit",
            DEFAULT_TIMELINE_MAX_LIMIT,
            minimum=1,
            maximum=10_000,
        )

    @property
    def query_preview_chars(self) -> int:
        return self.policy.number(
            "display",
            "query_preview_chars",
            DEFAULT_QUERY_PREVIEW_CHARS,
            minimum=20,
            maximum=10_000,
        )

    @property
    def gc_keep_count(self) -> int:
        return self.policy.number(
            "gc",
            "gc_keep_count",
            DEFAULT_GC_KEEP_COUNT,
            minimum=0,
            maximum=1_000_000,
        )

    @property
    def gc_keep_days(self) -> int:
        return self.policy.number(
            "gc",
            "gc_keep_days",
            DEFAULT_GC_KEEP_DAYS,
            minimum=0,
            maximum=36_500,
        )

    @property
    def pre_restore_retention_days(self) -> int:
        return self.policy.number(
            "gc",
            "pre_restore_retention_days",
            DEFAULT_PRE_RESTORE_RETENTION_DAYS,
            minimum=0,
            maximum=36_500,
        )

    @property
    def memory_quiesce_timeout(self) -> float:
        return self.policy.number(
            "safety",
            "include_memory_quiesce_timeout",
            DEFAULT_MEMORY_QUIESCE_TIMEOUT,
            minimum=1.0,
            maximum=600.0,
        )

    # -- snapshot ---------------------------------------------------------

    async def snapshot(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        message: str,
    ) -> str:
        """Create a permanent snapshot and return its display name."""
        ref = await self.make_snapshot(
            kind="snap",
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            name=message or None,
            message=message,
        )
        return ref.rsplit("/", 1)[-1]

    async def make_auto_checkpoint(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        message: str = "Auto checkpoint after response",
        query: str | None = None,
    ) -> str:
        """Create one automatic checkpoint and return its ref."""
        return await self.make_snapshot(
            kind="auto",
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            message=message,
            query=query,
        )

    async def make_snapshot(
        self,
        *,
        kind: str,
        session_id: str,
        user_id: str,
        channel: str,
        name: str | None = None,
        message: str = "",
        query: str | None = None,
    ) -> str:
        """Create a parentless full-workspace snapshot and return its ref."""
        result = await self.make_snapshot_result(
            kind=kind,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            name=name,
            message=message,
            query=query,
        )
        return result.ref

    async def make_snapshot_result(
        self,
        *,
        kind: str,
        session_id: str,
        user_id: str,
        channel: str,
        name: str | None = None,
        message: str = "",
        query: str | None = None,
    ) -> SnapshotResult:
        """Create a snapshot and return its complete internal result."""
        if kind not in {"auto", "snap", "pre-restore"}:
            raise ValueError(f"Unsupported checkpoint kind: {kind}")
        async with self.maintenance_lock:
            async with self.lock:
                result = await run_sync_io(
                    self.create_snapshot_unlocked,
                    kind,
                    session_id,
                    user_id,
                    channel,
                    name,
                    message,
                    query,
                )
        return result

    def create_snapshot_unlocked(
        self,
        kind: str,
        session_id: str,
        user_id: str,
        channel: str,
        name: str | None,
        message: str,
        query_override: str | None,
        *,
        tree_override: str | None = None,
    ) -> SnapshotResult:
        key = session_key(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
        )
        parent_commit = self.session_head(key)
        now_ms = int(time.time() * 1000)
        label = None
        if kind == "auto":
            ref = f"refs/auto/{key}/{now_ms}"
            while self.repository.ref_exists(ref):
                now_ms += 1
                ref = f"refs/auto/{key}/{now_ms}"
            subject = f"auto {key} {now_ms}"
        elif kind == "snap":
            label = sanitize_ref_component(name or message or f"snap-{now_ms}")
            ref = f"refs/snap/{key}/{label}"
            if (
                len(str(self.repository.git_dir / ref)) > 240
                or len(label.encode("utf-8")) > 240
            ):
                short_label = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
                ref = f"refs/snap/{key}/{short_label}"
            base_ref = ref
            suffix = 1
            while self.repository.ref_exists(ref):
                suffix += 1
                ref = f"{base_ref}-{suffix}"
            if suffix > 1:
                label = f"{label}-{suffix}"
            subject = f"snapshot {key} {label}"
        else:
            ref = f"refs/pre-restore/{now_ms}-{key}"
            while self.repository.ref_exists(ref):
                now_ms += 1
                ref = f"refs/pre-restore/{now_ms}-{key}"
            subject = f"pre-restore {key} {now_ms}"

        tree = tree_override or self.repository.write_workspace_tree(
            self._conversation_snapshot_blob(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            ),
        )
        body = message.strip() if message else subject
        query = query_override
        if query is None:
            query = latest_user_query(
                Path(self.conversation_workspace_dir),
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
        metadata = encode_metadata(
            query,
            agent_id=self.agent_id or None,
            channel=channel,
            user_id=user_id,
            session_id=session_id,
            parent_commit=parent_commit,
            snapshot_name=label,
        )
        commit = self.repository.run_git(
            "commit-tree",
            tree,
            input_text=f"{subject}\n\n{body}\n\n{metadata}\n",
        )
        self.repository.run_git("update-ref", ref, commit)
        self.repository.set_session_head(key, commit)
        return SnapshotResult(
            ref=ref,
            commit=commit,
            tree=tree,
            parent_commit=parent_commit,
            timestamp_ms=now_ms,
        )

    def _conversation_snapshot_blob(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> dict[str, bytes] | None:
        """跨空间快照只注入当前会话，不扫描其他用户 session。"""
        source = session_file_path(
            Path(self.conversation_workspace_dir),
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        try:
            content = source.read_bytes()
        except OSError as exc:
            if Path(self.conversation_workspace_dir) == self.workspace_dir:
                return {}
            raise CheckpointError(
                "The source session state is unavailable for this checkpoint.",
            ) from exc
        rel = session_file_path(
            Path("."),
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        ).as_posix()
        return {rel: content}

    @asynccontextmanager
    async def restore_copy_transaction(self, *, dry_run: bool = False):
        """同一任务的会话、文件、元数据和补偿共用维护事务。"""
        task = asyncio.current_task()
        if self._copy_maintenance_owner is task:
            yield
            return
        async with self.maintenance_lock:
            guard = self._restores._workspace_mutation_guard() if not dry_run else None
            callbacks = []
            if not dry_run:
                self.query_gate.clear()
            try:
                if guard is not None:
                    callbacks = await guard.quiesce()
                self._copy_maintenance_owner = task
                yield
            finally:
                self._copy_maintenance_owner = None
                if guard is not None:
                    guard.resume(callbacks)
                if not dry_run:
                    self.query_gate.set()

    async def restore_session_copy(
        self,
        *,
        target: str,
        source_session_id: str,
        source_user_id: str,
        source_channel: str,
        new_session_id: str,
        new_user_id: str,
        new_channel: str,
        dry_run: bool = False,
    ) -> RestoreResult:
        """把检查点中的会话状态复制为新会话，绝不覆盖源会话。"""
        async with self.restore_copy_transaction(dry_run=dry_run):
            async with self.lock:
                return await run_sync_io(
                    self._restore_session_copy_sync,
                    target=target,
                    source_session_id=source_session_id,
                    source_user_id=source_user_id,
                    source_channel=source_channel,
                    new_session_id=new_session_id,
                    new_user_id=new_user_id,
                    new_channel=new_channel,
                    dry_run=dry_run,
                )

    def _restore_session_copy_sync(self, **kwargs) -> RestoreResult:
        entry = self.resolve_target(
            kwargs["target"],
            kwargs["source_session_id"],
            kwargs["source_user_id"],
            kwargs["source_channel"],
        )
        source_rel = session_file_path(
            Path("."),
            session_id=kwargs["source_session_id"],
            user_id=kwargs["source_user_id"],
            channel=kwargs["source_channel"],
        ).as_posix()
        try:
            content = self.repository.read_blob(entry.commit, source_rel)
        except CheckpointError as exc:
            raise CheckpointError(
                "Checkpoint session state is missing or invalid.",
            ) from exc
        try:
            state = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CheckpointError(
                "Checkpoint session state is missing or invalid.",
            ) from exc
        try:
            if not isinstance(state, dict) or not isinstance(state.get("agent"), dict):
                raise ValueError("Missing agent")
            agent_state = state["agent"].get("state")
            if not isinstance(agent_state, dict) or "context" not in agent_state:
                raise ValueError("Missing agent state or context")
            AgentState.model_validate(agent_state)
        except (ValueError, TypeError, ValidationError) as exc:
            raise CheckpointError(
                "Checkpoint session state is missing or invalid."
            ) from exc
        target_path = session_file_path(
            Path(self.conversation_workspace_dir),
            session_id=kwargs["new_session_id"],
            user_id=kwargs["new_user_id"],
            channel=kwargs["new_channel"],
        )
        target_rel = target_path.relative_to(
            Path(self.conversation_workspace_dir),
        ).as_posix()
        if target_path.exists():
            raise CheckpointError("Restored session already exists.")
        if not kwargs["dry_run"]:
            write_text_atomic(
                target_path,
                json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        return RestoreResult(
            target=kwargs["target"],
            commit=entry.commit,
            restored_paths=(target_rel,),
            pre_restore_ref=None,
            dry_run=kwargs["dry_run"],
        )

    async def restore_selected_files_copy(
        self,
        *,
        target: str,
        source_session_id: str,
        source_user_id: str,
        source_channel: str,
        selected_files: tuple[str, ...] | None,
        include_files: bool = True,
        include_memory: bool = False,
        dry_run: bool = False,
    ) -> RestoreResult:
        """预览或恢复勾选文件，不触碰源会话状态。"""
        async with self.restore_copy_transaction(dry_run=dry_run):
            async with self.lock:
                operation = asyncio.create_task(
                    run_sync_io(
                        self._restore_selected_files_copy_sync,
                        target=target,
                        source_session_id=source_session_id,
                        source_user_id=source_user_id,
                        source_channel=source_channel,
                        selected_files=selected_files,
                        include_files=include_files,
                        include_memory=include_memory,
                        dry_run=dry_run,
                    ),
                )
                try:
                    return await asyncio.shield(operation)
                except asyncio.CancelledError:
                    # The worker may already have applied files. Keep its result
                    # so cancellation can compensate before releasing writers.
                    result = await operation
                    if not dry_run:
                        await run_sync_io(self._rollback_selected_scopes_sync, result)
                    raise

    def _restore_selected_files_copy_sync(self, **kwargs) -> RestoreResult:
        entry = self.resolve_target(
            kwargs["target"],
            kwargs["source_session_id"],
            kwargs["source_user_id"],
            kwargs["source_channel"],
        )
        source_rel = session_file_path(
            Path("."),
            session_id=kwargs["source_session_id"],
            user_id=kwargs["source_user_id"],
            channel=kwargs["source_channel"],
        ).as_posix()
        current_tree = self.repository.write_workspace_tree(
            self._conversation_snapshot_blob(
                session_id=kwargs["source_session_id"],
                user_id=kwargs["source_user_id"],
                channel=kwargs["source_channel"],
            ),
        )
        touched = (
            self._restores._file_restore_candidates(
                target_commit=entry.commit,
                current_tree=current_tree,
                conv_rel=source_rel,
                selected_files=kwargs["selected_files"],
            )
            if kwargs["include_files"]
            else set()
        )
        restored, deleted = self.repository.plan_tree_restore(
            entry.commit,
            touched,
        )
        memory = self._restores._memory_restorer() if kwargs["include_memory"] else None
        if memory is not None:
            memory_restored, memory_deleted = memory.plan(entry.commit)
            restored.extend(memory_restored)
            deleted.extend(memory_deleted)
        pre_ref = None
        if not kwargs["dry_run"]:
            pre_ref = self.create_snapshot_unlocked(
                "pre-restore",
                kwargs["source_session_id"],
                kwargs["source_user_id"],
                kwargs["source_channel"],
                None,
                f"Before selected file restore to {kwargs['target']}",
                None,
                tree_override=current_tree,
            ).ref
            try:
                self.repository.restore_tree_paths(entry.commit, touched)
                if memory is not None:
                    memory.restore_sync(entry.commit)
            except Exception:
                self.repository.restore_tree_paths(current_tree, touched)
                if memory is not None:
                    memory.restore_sync(current_tree)
                raise
        return RestoreResult(
            target=kwargs["target"],
            commit=entry.commit,
            restored_paths=tuple(restored),
            deleted_paths=tuple(deleted),
            file_paths=tuple(sorted(touched)),
            pre_restore_ref=pre_ref,
            dry_run=kwargs["dry_run"],
            include_files=kwargs["include_files"],
            include_memory=kwargs["include_memory"],
        )

    async def rollback_selected_scopes(self, result: RestoreResult) -> None:
        """回滚本次新会话创建失败前已应用的文件/记忆范围。"""
        if not result.pre_restore_ref:
            return
        async with self.restore_copy_transaction():
            async with self.lock:
                await run_sync_io(self._rollback_selected_scopes_sync, result)

    def _rollback_selected_scopes_sync(self, result: RestoreResult) -> None:
        if result.file_paths:
            self.repository.restore_tree_paths(
                result.pre_restore_ref,
                set(result.file_paths),
            )
        if result.include_memory:
            self._restores._memory_restorer().restore_sync(result.pre_restore_ref)

    # -- reset ------------------------------------------------------------

    async def reset(self) -> None:
        """Delete and recreate this workspace's checkpoint state."""
        async with self.maintenance_lock:
            self.query_gate.clear()
            try:
                async with self.lock:
                    await run_sync_io(self._reset_unlocked)
            finally:
                self.query_gate.set()

    def _reset_unlocked(self) -> None:
        self.repository.reset()
        self.policy.reload(force=True)

    # -- timeline ---------------------------------------------------------

    async def timeline(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        limit: int | None = None,
        include_all: bool = False,
    ) -> list[CheckpointEntry]:
        """Return timeline entries grouped by kind, newest first per group."""
        async with self.maintenance_lock:
            async with self.lock:
                return await run_sync_io(
                    self._timeline_sync,
                    session_id,
                    user_id,
                    channel,
                    limit,
                    include_all,
                )

    async def graph_entries(
        self,
        *,
        limit: int = 1000,
        user_id: str | None = None,
    ) -> list[CheckpointEntry]:
        """Return workspace-wide entries for graph visualisation."""
        resolved = max(1, min(1000, limit))
        async with self.maintenance_lock:
            async with self.lock:
                return await run_sync_io(
                    self._timeline_sync,
                    "",
                    "",
                    "",
                    resolved,
                    True,
                    user_id,
                )

    async def resolve_target_entry(
        self,
        target: str,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> CheckpointEntry:
        """精确解析单个恢复目标，不受图谱分页上限影响。"""
        async with self.maintenance_lock:
            async with self.lock:
                return await run_sync_io(
                    self.resolve_target,
                    target,
                    session_id,
                    user_id,
                    channel,
                )

    def _timeline_sync(
        self,
        session_id: str,
        user_id: str,
        channel: str,
        limit: int | None,
        include_all: bool,
        creator_user_id: str | None = None,
    ) -> list[CheckpointEntry]:
        resolved = self.timeline_default_limit if limit is None else limit
        resolved = max(1, min(self.timeline_max_limit, resolved))
        key = session_key(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
        )
        all_records = self._list_ref_records()
        session_records = [
            item for item in all_records if ref_session_key(item.ref) == key
        ]
        records = all_records if include_all else session_records
        current_records = sorted(
            session_records,
            key=lambda item: item.timestamp_ms,
            reverse=True,
        )
        restore_indexes = {
            item.ref: index for index, item in enumerate(current_records, 1)
        }
        records_by_key: dict[str, list[_RefRecord]] = {}
        for record in records:
            record_key = ref_session_key(record.ref)
            if record_key:
                records_by_key.setdefault(record_key, []).append(record)
        heads: dict[str, str | None] = {}
        for record_key, key_records in records_by_key.items():
            heads[record_key] = self._head_for_records(
                record_key,
                key_records,
            )
        entries = [
            self._entry_from_record(
                record,
                restore_index=restore_indexes.get(record.ref),
                is_head=(
                    record.commit == heads.get(ref_session_key(record.ref))
                ),
            )
            for record in records
        ]
        if creator_user_id is not None:
            entries = [
                entry for entry in entries if entry.user_id == creator_user_id
            ]
        entries.sort(
            key=lambda entry: entry.timestamp_ms,
            reverse=True,
        )
        return entries[:resolved]

    def _list_ref_records(self) -> list[_RefRecord]:
        """Read checkpoint refs and commit metadata in one Git process."""
        fmt = (
            "%(refname)%1f%(objectname)%1f%(creatordate:unix)%1f"
            + "%(contents)%1e"
        )
        output = self.repository.run_git(
            "for-each-ref",
            f"--format={fmt}",
            "refs/auto",
            "refs/snap",
            "refs/pre-restore",
        )
        records: list[_RefRecord] = []
        for raw_record in output.split(_REF_RECORD_SEPARATOR):
            raw_record = raw_record.lstrip("\r\n")
            if not raw_record:
                continue
            parts = raw_record.split(_REF_FIELD_SEPARATOR, 3)
            if len(parts) != 4:
                continue
            ref, commit, timestamp, message = parts
            try:
                timestamp_ms = int(timestamp) * 1000
            except ValueError:
                timestamp_ms = 0
            records.append(
                _RefRecord(
                    ref=ref,
                    commit=commit,
                    timestamp_ms=self._timestamp_from_ref(
                        ref,
                        timestamp_ms,
                    ),
                    message=message.rstrip("\r\n"),
                ),
            )
        return records

    def session_head(self, key: str) -> str | None:
        records = [
            record
            for record in self._list_ref_records()
            if ref_session_key(record.ref) == key
        ]
        return self._head_for_records(key, records)

    def _head_for_records(
        self,
        key: str,
        records: list[_RefRecord],
    ) -> str | None:
        if not records:
            return None
        stored = self.repository.get_session_head(key)
        if stored and any(record.commit == stored for record in records):
            return stored
        return max(
            records,
            key=lambda record: record.timestamp_ms,
        ).commit

    async def delete_sessions(
        self,
        sessions: list[tuple[str, str, str]],
    ) -> tuple[str, ...]:
        """Delete all checkpoint refs and HEAD records for sessions."""
        keys = {
            session_key(
                channel=channel,
                user_id=user_id,
                session_id=session_id,
            )
            for session_id, user_id, channel in sessions
            if session_id
        }
        if not keys:
            return ()
        async with self.maintenance_lock:
            async with self.lock:
                return await run_sync_io(
                    self._delete_sessions_sync,
                    keys,
                )

    def _delete_sessions_sync(self, keys: set[str]) -> tuple[str, ...]:
        refs = tuple(
            record.ref
            for record in self._list_ref_records()
            if ref_session_key(record.ref) in keys
        )
        if refs:
            commands = "".join(f"delete {ref}\n" for ref in refs)
            self.repository.run_git(
                "update-ref",
                "--stdin",
                input_text=commands,
            )
        self.repository.remove_session_heads(keys)
        return refs

    def _entry_from_ref(
        self,
        ref: str,
        commit: str,
        *,
        restore_index: int | None = None,
        is_head: bool = False,
    ) -> CheckpointEntry:
        commit_message = self.repository.run_git(
            "log",
            "-1",
            "--format=%B",
            commit,
        )
        return self._entry_from_record(
            _RefRecord(
                ref=ref,
                commit=commit,
                timestamp_ms=self._entry_timestamp(ref, commit),
                message=commit_message,
            ),
            restore_index=restore_index,
            is_head=is_head,
        )

    def _entry_from_record(
        self,
        record: _RefRecord,
        *,
        restore_index: int | None = None,
        is_head: bool = False,
    ) -> CheckpointEntry:
        ref = record.ref
        parts = ref.split("/")
        kind = ref_kind(ref)
        key = ref_session_key(ref)
        name = "/".join(parts[3:]) if len(parts) > 3 else ""
        commit_message = record.message
        subject = commit_message.splitlines()[0] if commit_message else ""
        metadata = metadata_from_commit_message(commit_message)
        if isinstance(metadata.get("snapshot_name"), str):
            name = metadata["snapshot_name"]
        parent = metadata.get("parent")
        if not isinstance(parent, str) or not parent:
            parent = None
        chan = metadata.get("channel")
        if not isinstance(chan, str) or not chan:
            chan = key.split("-", 1)[0] if key else "unknown"
        user_id = metadata.get("user_id")
        if not isinstance(user_id, str):
            user_id = ""
        session_id = metadata.get("session_id")
        if not isinstance(session_id, str):
            session_id = ""
        agent_id = metadata.get("agent_id")
        if not isinstance(agent_id, str):
            agent_id = ""
        return CheckpointEntry(
            ref=ref,
            kind=kind,
            session_key=key,
            name=name,
            commit=record.commit,
            timestamp_ms=record.timestamp_ms,
            subject=subject,
            query=query_from_commit_message(commit_message),
            channel=chan,
            restore_index=restore_index,
            parent_commit=parent,
            is_head=is_head,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
        )

    def _entry_timestamp(self, ref: str, commit: str) -> int:
        return self._timestamp_from_ref(
            ref,
            self._commit_timestamp(commit),
        )

    def _commit_timestamp(self, commit: str) -> int:
        try:
            return (
                int(
                    self.repository.run_git(
                        "show",
                        "-s",
                        "--format=%ct",
                        commit,
                    ),
                )
                * 1000
            )
        except CheckpointError:
            return 0

    @staticmethod
    def _timestamp_from_ref(ref: str, fallback_ms: int) -> int:
        parts = ref.split("/")
        tail = parts[-1] if parts else ""
        if ref.startswith("refs/auto/") and tail.isdigit():
            return int(tail)
        if ref.startswith("refs/pre-restore/"):
            maybe_ts = tail.split("-", 1)[0]
            if maybe_ts.isdigit():
                return int(maybe_ts)
        return fallback_ms

    # -- restore (conversation) ------------------------------------------

    async def restore(
        self,
        *,
        target: str | None,
        session_id: str,
        user_id: str,
        channel: str,
        dry_run: bool = False,
    ) -> RestoreResult:
        """Restore the current conversation session to a checkpoint."""
        return await self._restores.restore(
            target=target,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            dry_run=dry_run,
        )

    # -- restore with memory -----------------------------------------------

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
        return await self._restores.restore_with_memory(
            target=target,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            dry_run=dry_run,
        )

    # -- restore with files ------------------------------------------------

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
        """Restore conversation + query-touched files to a checkpoint."""
        return await self._restores.restore_with_files(
            target=target,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            include_memory=include_memory,
            selected_files=selected_files,
            dry_run=dry_run,
        )

    def resolve_target(
        self,
        target: str,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> CheckpointEntry:
        target = target.strip()
        index_target = target[1:] if target.startswith("#") else target
        explicit_index = target.startswith("#")
        timeline = self._timeline_sync(
            session_id,
            user_id,
            channel,
            self.timeline_max_limit,
            False,
        )
        key = session_key(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
        )
        if index_target.isdigit() and (
            explicit_index or len(index_target) < 7
        ):
            index = int(index_target)
            if 1 <= index <= len(timeline):
                return timeline[index - 1]
        snap_ref = f"refs/snap/{key}/{sanitize_ref_component(target)}"
        if self.repository.ref_exists(snap_ref):
            return self._entry_from_ref(
                snap_ref,
                self.repository.run_git("rev-parse", snap_ref),
            )
        # Names, refs and commit IDs are exact targets, independent of the
        # timeline page used for numeric indexes. Include legacy ref keys.
        records = sorted(
            (
                record for record in self._list_ref_records()
                if ref_session_key(record.ref) == key
            ),
            key=lambda record: record.timestamp_ms,
            reverse=True,
        )
        normalized_name = sanitize_ref_component(target)
        for record in records:
            entry = self._entry_from_record(record)
            if (
                entry.ref == target
                or entry.ref.endswith("/" + target)
                or entry.name == target
                or entry.name == normalized_name
            ):
                return entry
            if len(target) >= 7 and entry.commit.startswith(target):
                return entry
        if index_target.isdigit() and (
            explicit_index or len(index_target) < 7
        ):
            raise CheckpointError(f"Timeline index out of range: {target}")
        raise CheckpointError(
            f"Unknown restore target for this session: {target}",
        )

    # -- gc ---------------------------------------------------------------

    async def gc(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        compact: bool = False,
        all_sessions: bool = False,
        dry_run: bool = False,
        keep_count: int | None = None,
        keep_days: int | None = None,
        pre_restore_days: int | None = None,
        creator_user_id: str | None = None,
    ) -> GcResult:
        """Delete collectible auto/pre-restore refs and run git gc."""
        async with self.maintenance_lock:
            async with self.lock:
                return await run_sync_io(
                    self._gc_sync,
                    session_id,
                    user_id,
                    channel,
                    compact,
                    all_sessions,
                    dry_run,
                    keep_count,
                    keep_days,
                    pre_restore_days,
                    creator_user_id,
                )

    @staticmethod
    def _kept_auto_refs_by_session(
        records: list[_RefRecord],
        keep_count: int,
    ) -> set[str]:
        """Return newest auto refs under a separate quota per session."""
        records_by_session: dict[str, list[_RefRecord]] = {}
        for record in records:
            record_key = ref_session_key(record.ref)
            # Malformed refs must not share one accidental global quota.
            group_key = record_key or record.ref
            records_by_session.setdefault(group_key, []).append(record)

        kept: set[str] = set()
        for session_records in records_by_session.values():
            session_records.sort(
                key=lambda record: record.timestamp_ms,
                reverse=True,
            )
            kept.update(record.ref for record in session_records[:keep_count])
        return kept

    def _gc_sync(
        self,
        session_id: str,
        user_id: str,
        channel: str,
        compact: bool,
        all_sessions: bool,
        dry_run: bool,
        keep_count: int | None,
        keep_days: int | None,
        pre_restore_days: int | None,
        creator_user_id: str | None,
    ) -> GcResult:
        resolved_count = (
            self.gc_keep_count if keep_count is None else keep_count
        )
        resolved_days = self.gc_keep_days if keep_days is None else keep_days
        resolved_pre_restore_days = (
            self.pre_restore_retention_days
            if pre_restore_days is None
            else pre_restore_days
        )
        key = session_key(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
        )
        records = self._list_ref_records()
        scoped_records = (
            records
            if all_sessions
            else [
                record
                for record in records
                if ref_session_key(record.ref) == key
            ]
        )
        if creator_user_id is not None:
            scoped_records = [
                record
                for record in scoped_records
                if self._entry_from_record(record).user_id == creator_user_id
            ]
        now_ms = int(time.time() * 1000)
        keep_cutoff_ms = now_ms - resolved_days * 86_400_000
        pre_cutoff_ms = now_ms - resolved_pre_restore_days * 86_400_000

        records_by_session: dict[str, list[_RefRecord]] = {}
        for record in scoped_records:
            record_key = ref_session_key(record.ref)
            if record_key:
                records_by_session.setdefault(record_key, []).append(record)
        head_commits = {
            record_key: self._head_for_records(record_key, key_records)
            for record_key, key_records in records_by_session.items()
        }

        auto_records = [
            record
            for record in scoped_records
            if record.ref.startswith("refs/auto/")
        ]
        kept_auto = (
            set()
            if compact
            else self._kept_auto_refs_by_session(
                auto_records,
                resolved_count,
            )
        )
        delete_refs: list[str] = []
        keep_refs: list[str] = []
        for record in auto_records:
            ref = record.ref
            # Never delete a session HEAD checkpoint.
            if head_commits.get(ref_session_key(ref)) == record.commit:
                keep_refs.append(ref)
            elif compact:
                delete_refs.append(ref)
            elif ref in kept_auto or record.timestamp_ms >= keep_cutoff_ms:
                keep_refs.append(ref)
            else:
                delete_refs.append(ref)

        pre_records = [
            record
            for record in scoped_records
            if record.ref.startswith("refs/pre-restore/")
        ]
        for record in pre_records:
            ref = record.ref
            if head_commits.get(ref_session_key(ref)) == record.commit:
                keep_refs.append(ref)
            elif record.timestamp_ms < pre_cutoff_ms:
                delete_refs.append(ref)
            else:
                keep_refs.append(ref)

        if not dry_run and delete_refs:
            commits_by_ref = {
                record.ref: record.commit for record in scoped_records
            }
            commands = "".join(
                f"delete {ref} {commits_by_ref[ref]}\n" for ref in delete_refs
            )
            self.repository.run_git(
                "update-ref",
                "--stdin",
                input_text=commands,
            )
            self.repository.run_git("gc", "--auto")
        return GcResult(
            deleted_refs=tuple(delete_refs),
            kept_refs=tuple(keep_refs),
            dry_run=dry_run,
        )
