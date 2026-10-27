# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
import json
from pathlib import Path
import stat
import time
from typing import Iterable
from uuid import uuid4

from pydantic import Field

from domain.errors import ConflictError
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.execution_models import (
    SpecialistRunRecord,
    TaskRecord,
)
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.models import StrictRuntimeModel
from services.runtime_files.path_safety import (
    is_link_path,
    is_link_stat,
    require_safe_runtime_segment,
)


class ManualHoldConflict(ConflictError):
    pass


# project.json is published by atomic replacement, so (mtime, size, inode)
# changes on every write and a hit means the parsed identity is still valid.
_IDENTITY_CACHE: dict[Path, tuple[tuple[int, int, int], str]] = {}


class ManualHoldState(StrictRuntimeModel):
    project_id: str
    project_identity: str
    revision: int = Field(default=0, ge=0)
    contributions: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def node_ids(self) -> frozenset[str]:
        return frozenset(
            n for nodes in self.contributions.values() for n in nodes
        )

    def payload(self) -> dict:
        return {"revision": self.revision, "nodeIds": sorted(self.node_ids)}


@dataclass(frozen=True)
class HoldOperation:
    project_id: str
    project_identity: str
    token: str
    target: str
    observed_tokens: frozenset[str]


@dataclass
class ManualAdmission:
    store: ManualRegenerationHoldStore
    operation: HoldOperation | None
    project_id: str
    request_id: str
    closed: bool = False
    untracked_admission: bool = False
    node_id: str | None = None


_automatic: ContextVar[tuple[Path, str, str] | None] = ContextVar(
    "manual_hold_automatic_node",
    default=None,
)
_manual: ContextVar[ManualAdmission | None] = ContextVar(
    "manual_hold_admission",
    default=None,
)
_creating: ContextVar[bool] = ContextVar("manual_hold_creating", default=False)
_creating_node: ContextVar[str | None] = ContextVar(
    "manual_hold_creating_node",
    default=None,
)


def _transitive_dependents(root: str, nodes: Iterable) -> set[str]:
    dependents: dict[str, list[str]] = {}
    for node in nodes:
        for dependency in node.deps:
            dependents.setdefault(dependency, []).append(node.node_id)
    seen = {root}
    stack = [root]
    while stack:
        for child in dependents.get(stack.pop(), ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen - {root}


class ManualRegenerationHoldStore:
    def __init__(self, data_root):
        self.root = Path(data_root).resolve(strict=True)

    def _identity(self, project_id: str) -> str:
        require_safe_runtime_segment(project_id, label="project_id")
        root = self.root / project_id
        root_stat = root.lstat()
        project_path = root / "project.json"
        project_stat = project_path.lstat()
        if (
            is_link_stat(root_stat)
            or not stat.S_ISDIR(root_stat.st_mode)
            or not stat.S_ISREG(project_stat.st_mode)
        ):
            raise ManualHoldConflict("Unsafe Project path")
        if is_link_path(root / "runtime"):
            raise ManualHoldConflict("Unsafe Runtime path")
        key = (
            project_stat.st_mtime_ns,
            project_stat.st_size,
            project_stat.st_ino,
        )
        cached = _IDENTITY_CACHE.get(project_path)
        if cached is not None and cached[0] == key:
            return cached[1]
        document = json.loads(project_path.read_bytes())
        if document["project_id"] != project_id:
            raise ManualHoldConflict("Project identity mismatch")
        # Durable fields only: an exported/imported or relocated Project keeps
        # its holds, while a deleted and recreated one has a new created_at.
        identity = f"{project_id}:{document['created_at']}"
        _IDENTITY_CACHE[project_path] = (key, identity)
        return identity

    def _record(self, project_id):
        return AtomicJsonRecordStore(
            self.root
            / project_id
            / "runtime"
            / "manual-regeneration-hold.json",
            ManualHoldState,
            locked=False,
        )

    @contextmanager
    def _lock(self, project_id, *, _lifecycle_lock_held=False):
        require_safe_runtime_segment(project_id, label="project_id")
        lifecycle = (
            nullcontext()
            if _lifecycle_lock_held
            else CrossProcessFileLock(
                self.root / ".locks" / f"project-{project_id}.lock",
                shared=True,
            )
        )
        with lifecycle:
            identity = self._identity(project_id)
            with CrossProcessFileLock(
                self.root
                / project_id
                / "runtime"
                / "locks"
                / "manual-regeneration-hold.lock",
            ):
                state = self._record(project_id).read_or_none()
                if state is None:
                    state = ManualHoldState(
                        project_id=project_id,
                        project_identity=identity,
                    )
                if (
                    state.project_id != project_id
                    or state.project_identity != identity
                ):
                    raise ManualHoldConflict("Project lifetime changed")
                yield state

    def _write(self, state):
        state.contributions = {
            k: v for k, v in state.contributions.items() if v
        }
        # Microsecond revisions remain JS-safe and do not alias a recreated
        # Project.
        state.revision = max(state.revision + 1, time.time_ns() // 1000)
        self._record(state.project_id).write(state)

    def read(
        self,
        project_id,
        *,
        _lifecycle_lock_held=False,
    ) -> ManualHoldState:
        with self._lock(
            project_id,
            _lifecycle_lock_held=_lifecycle_lock_held,
        ) as state:
            return state

    def is_held(self, project_id, node_id) -> bool:
        return node_id in self.read(project_id).node_ids

    def begin(
        self,
        project_id,
        node,
        nodes,
        *,
        expected_identity=None,
        existing_output=False,
    ) -> HoldOperation | None:
        with self._lock(project_id) as state:
            if (
                expected_identity is not None
                and state.project_identity != expected_identity
            ):
                raise ManualHoldConflict("Project lifetime changed")
            regeneration = (
                existing_output
                or bool(node.regeneration_of)
                or node.status.value in {"done", "stale"}
            )
            if not regeneration and node.node_id not in state.node_ids:
                return None
            observed = frozenset(
                k for k, v in state.contributions.items() if node.node_id in v
            )
            token = uuid4().hex
            held = (
                _transitive_dependents(node.node_id, nodes)
                if regeneration
                else set()
            )
            state.contributions[token] = sorted(held | {node.node_id})
            self._write(state)
            return HoldOperation(
                project_id,
                state.project_identity,
                token,
                node.node_id,
                observed,
            )

    @staticmethod
    def _check_operation(state, operation):
        if state.project_identity != operation.project_identity:
            raise ManualHoldConflict("Project lifetime changed")

    def admitted(self, operation: HoldOperation | None):
        if operation is None:
            return
        with self._lock(operation.project_id) as state:
            self._check_operation(state, operation)
            for token in operation.observed_tokens | {operation.token}:
                if token in state.contributions:
                    state.contributions[token] = [
                        n
                        for n in state.contributions[token]
                        if n != operation.target
                    ]
            self._write(state)

    def rollback(self, operation: HoldOperation | None):
        if operation is None:
            return
        with self._lock(operation.project_id) as state:
            self._check_operation(state, operation)
            if state.contributions.pop(operation.token, None) is not None:
                self._write(state)

    def resume(self, project_id, revision: int):
        with self._lock(project_id) as state:
            if state.revision != revision:
                raise ManualHoldConflict("暂停状态已更新，请刷新后继续")
            if state.contributions:
                state.contributions.clear()
                self._write(state)

    def finish(self, admission: ManualAdmission, *, succeeded: bool):
        with self._lock(admission.project_id) as state:
            if admission.operation:
                self._check_operation(state, admission.operation)
            admission.closed = True
            executions = ProjectExecutionStore(self.root)
            records = [
                *executions.list_specialist_runs(admission.project_id),
                *executions.list_tasks(admission.project_id),
            ]
            durable = any(
                value == admission.request_id
                or value.startswith(admission.request_id + "-r")
                for record in records
                for value in (
                    getattr(record, "idempotency_key", None),
                    record.caused_by_request_id,
                )
                if value
            )
        if durable or succeeded:
            self.admitted(admission.operation)
        elif not admission.untracked_admission:
            self.rollback(admission.operation)


@contextmanager
def automatic_node(data_root, project_id, node_id):
    manual_token = _manual.set(None)
    token = _automatic.set((Path(data_root).resolve(), project_id, node_id))
    try:
        yield
    finally:
        _automatic.reset(token)
        _manual.reset(manual_token)


@contextmanager
def manual_admission(admission: ManualAdmission):
    automatic_token = _automatic.set(None)
    token = _manual.set(admission)
    try:
        yield
    finally:
        _manual.reset(token)
        _automatic.reset(automatic_token)


def background_context():
    """Retain provider configuration, never a caller's media permission."""
    context = copy_context()
    context.run(_manual.set, None)
    context.run(_automatic.set, None)
    context.run(_creating.set, False)
    context.run(_creating_node.set, None)
    return context


@contextmanager
def admission_guard(
    data_root,
    project_id,
    *,
    node_id=None,
    _lifecycle_lock_held=False,
):
    root = Path(data_root).resolve()
    automatic = _automatic.get()
    if automatic and automatic[:2] == (root, project_id):
        node_id = automatic[2]
    manual = _manual.get()
    if manual and (
        manual.store.root != root or manual.project_id != project_id
    ):
        manual = None
    if manual is not None:
        target = manual.node_id or (
            manual.operation.target if manual.operation else None
        )
        if node_id is not None and node_id != target:
            manual = None
        else:
            node_id = None
    if node_id is None and manual is None:
        yield
        return
    store = ManualRegenerationHoldStore(root)
    # This module-level guard shares the store's admission transaction.
    # pylint: disable-next=protected-access
    with store._lock(
        project_id,
        _lifecycle_lock_held=_lifecycle_lock_held,
    ) as state:
        if manual:
            if manual.closed:
                raise ManualHoldConflict("Manual request admission is closed")
            if manual.operation:
                # Check the operation against that same locked state.
                # pylint: disable-next=protected-access
                store._check_operation(state, manual.operation)
        if node_id is not None and node_id in state.node_ids:
            raise ManualHoldConflict("节点等待手动重新生成或继续制作")
        yield


def check_automatic(data_root, project_id, *, _lifecycle_lock_held=False):
    with admission_guard(
        data_root,
        project_id,
        _lifecycle_lock_held=_lifecycle_lock_held,
    ):
        pass


def mark_untracked_admission(data_root, project_id):
    with admission_guard(data_root, project_id):
        admission = _manual.get()
        if admission:
            admission.untracked_admission = True


class HoldAwareExecutionStore(ProjectExecutionStore):
    @contextmanager
    def _project_lock(self, project_id, *, _lifecycle_lock_held=False):
        with super()._project_lock(
            project_id,
            _lifecycle_lock_held=_lifecycle_lock_held,
        ):
            guard = (
                admission_guard(
                    self.data_root,
                    project_id,
                    node_id=_creating_node.get(),
                    _lifecycle_lock_held=True,
                )
                if _creating.get()
                else nullcontext()
            )
            with guard:
                yield

    def _with_automatic_metadata(self, record):
        automatic = _automatic.get()
        node_id = record.metadata.get("automaticWorkNodeId")
        manual = _manual.get()
        if manual and (
            manual.store.root == self.data_root
            and manual.project_id == record.project_id
        ):
            node_id = manual.node_id or (
                manual.operation.target if manual.operation else node_id
            )
        if automatic and automatic[:2] == (self.data_root, record.project_id):
            node_id = automatic[2]
        elif isinstance(record, TaskRecord) and record.run_id and not node_id:
            node_id = self.get_run(
                record.project_id,
                record.run_id,
            ).metadata.get("automaticWorkNodeId")
        if node_id:
            record = record.model_copy(
                update={
                    "metadata": {
                        **record.metadata,
                        "automaticWorkNodeId": node_id,
                    },
                },
            )
        return record

    def create_specialist_run(self, record):
        record = self._with_automatic_metadata(
            SpecialistRunRecord.model_validate(record),
        )
        token = _creating.set(True)
        node_token = _creating_node.set(
            record.metadata.get("automaticWorkNodeId"),
        )
        try:
            return super().create_specialist_run(record)
        finally:
            _creating_node.reset(node_token)
            _creating.reset(token)

    create_run = create_specialist_run

    def create_task(self, record):
        record = self._with_automatic_metadata(
            TaskRecord.model_validate(record),
        )
        token = _creating.set(True)
        node_token = _creating_node.set(
            record.metadata.get("automaticWorkNodeId"),
        )
        try:
            result = super().create_task(record)
            manual = _manual.get()
            if (
                manual
                and manual.project_id == record.project_id
                and (manual.store.root == self.data_root)
                and any(
                    value == manual.request_id
                    or value.startswith(manual.request_id + "-r")
                    for value in (
                        record.idempotency_key,
                        record.caused_by_request_id,
                    )
                    if value
                )
            ):
                # Release this target before a clean background supervisor
                # can claim it; downstream holds remain intact.
                manual.store.admitted(manual.operation)
            return result
        finally:
            _creating_node.reset(node_token)
            _creating.reset(token)


__all__ = [
    "ManualRegenerationHoldStore",
    "ManualHoldState",
    "HoldOperation",
    "ManualAdmission",
    "ManualHoldConflict",
    "HoldAwareExecutionStore",
    "automatic_node",
    "manual_admission",
    "admission_guard",
    "check_automatic",
    "mark_untracked_admission",
    "background_context",
]
