# -*- coding: utf-8 -*-
"""Exact runtime custody and stop evidence, without process supervision."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


class RuntimeSourceBusyError(RuntimeError):
    """A source mutation or retained lease excludes the requested operation."""


@dataclass(frozen=True)
class RuntimeKey:
    """A capability slot in a stable scope, independent of its owner."""

    kind: str
    name: str
    scope_id: str


@dataclass(frozen=True)
class RuntimeLease:
    """The precise generation retaining a source directory."""

    plugin_id: str
    key: RuntimeKey
    instance_id: str
    generation: int
    code_root: Path


@dataclass(frozen=True)
class RuntimeStopReceipt:
    """Business quiescence and process exit are independent attestations.

    Non-process adapters attest exited=True when no process remains.
    """

    quiescent: bool
    detail: str = ""
    exited: bool = True
    returncode: int | None = None
    forced: bool = False
    residual: tuple[str, ...] = ()

    @property
    def stopped(self) -> bool:
        """Whether all evidence permits releasing this resource."""
        return self.quiescent and self.exited and not self.residual


@dataclass
class _OwnedRuntime:
    lease: RuntimeLease
    identity_claims: tuple[tuple[str, str], ...] = field(
        default=(),
        repr=False,
    )
    dependency_owner: RuntimeLease | None = field(default=None, repr=False)
    custody_only: bool = field(default=False, repr=False)
    stop: Callable[[], Awaitable[RuntimeStopReceipt]] | None = None
    stopping: asyncio.Task[RuntimeStopReceipt] | None = None
    resource: object | None = None


class RuntimeOwners:
    """Reserve synchronously; retain each resource until exact stop proof."""

    def __init__(self):
        self._entries: dict[RuntimeKey, _OwnedRuntime] = {}
        self._generations: dict[RuntimeKey, int] = {}
        self._mutations: dict[object, tuple[object, tuple[Path, ...]]] = {}

    @staticmethod
    def _overlaps(left, right):
        return left.is_relative_to(right) or right.is_relative_to(left)

    @contextmanager
    def mutation(self, *roots):
        """Exclude new custody until a source operation has fully settled.

        Enter on the event loop before handing work to a thread. Nested scopes
        each retain their own token; leaving one cannot release another.
        """
        paths = tuple(
            Path(root).resolve() for root in roots if root is not None
        )
        try:
            owner = asyncio.current_task()
        except RuntimeError:
            owner = threading.get_ident()
        if any(
            held_owner != owner and self._overlaps(root, held_root)
            for held_owner, held_paths in self._mutations.values()
            for root in paths
            for held_root in held_paths
        ):
            raise RuntimeSourceBusyError("RUNTIME_SOURCE_MUTATING")
        if any(
            self._overlaps(root, lease.code_root)
            for root in paths
            for lease in self.leases()
        ):
            raise RuntimeSourceBusyError(
                "RUNTIME_SOURCE_STILL_OWNED; needs_restart",
            )
        token = object()
        self._mutations[token] = (owner, paths)
        try:
            yield
        finally:
            del self._mutations[token]

    def reserve(
        self,
        plugin_id,
        key,
        code_root,
        *,
        instance_id,
        identity_claims=(),
        dependency_owner=None,
        custody_only=False,
    ):
        """Occupy a slot before construction or asynchronous startup."""
        if key in self._entries:
            raise RuntimeError("RUNTIME_ALREADY_OWNED; needs_restart")
        if type(custody_only) is not bool or (
            custody_only and dependency_owner is not None
        ):
            raise ValueError("RUNTIME_CUSTODY_CLASS_INVALID")
        claims = tuple(identity_claims)
        if any(
            not isinstance(claim, tuple)
            or len(claim) != 2
            or not all(isinstance(value, str) and value for value in claim)
            for claim in claims
        ):
            raise ValueError("RUNTIME_IDENTITY_CLAIM_INVALID")
        if any(
            set(claims).intersection(entry.identity_claims)
            for entry in self._entries.values()
        ):
            raise RuntimeError("RUNTIME_IDENTITY_ALREADY_OWNED; needs_restart")
        code_root = Path(code_root).resolve()
        if dependency_owner is not None:
            parent = (
                self._entries.get(dependency_owner.key)
                if isinstance(dependency_owner, RuntimeLease)
                else None
            )
            if parent is None or parent.lease != dependency_owner:
                raise ValueError("RUNTIME_DEPENDENCY_OWNER_STALE")
            if (
                dependency_owner.plugin_id != plugin_id
                or dependency_owner.code_root != code_root
                or dependency_owner.instance_id != instance_id
            ):
                raise ValueError("RUNTIME_DEPENDENCY_OWNER_MISMATCH")
        if any(
            self._overlaps(code_root, root)
            for _, roots in self._mutations.values()
            for root in roots
        ):
            raise RuntimeSourceBusyError("RUNTIME_SOURCE_MUTATING")
        generation = self._generations.get(key, 0) + 1
        lease = RuntimeLease(
            plugin_id,
            key,
            instance_id,
            generation,
            code_root,
        )
        self._entries[key] = _OwnedRuntime(
            lease,
            identity_claims=claims,
            dependency_owner=dependency_owner,
            custody_only=custody_only,
        )
        self._generations[key] = generation
        return lease

    def attach(self, lease, stop, *, resource=None):
        """Bind the sole stop adapter before the first startup await."""
        entry = self._entries.get(lease.key)
        if entry is None or entry.lease != lease:
            raise RuntimeError("RUNTIME_LEASE_STALE")
        if entry.stop is not None:
            raise RuntimeError("RUNTIME_STOP_ALREADY_ATTACHED")
        entry.stop = stop
        entry.resource = resource

    def resource(self, lease) -> object | None:
        """Read opaque adapter data for this exact current lease."""
        entry = self._entries.get(lease.key)
        return (
            entry.resource
            if entry is not None and entry.lease == lease
            else None
        )

    def release(self, lease, receipt) -> bool:
        """A stale generation or incomplete evidence cannot release custody."""
        entry = self._entries.get(lease.key)
        if entry is None or entry.lease != lease or not receipt.stopped:
            return False
        # An independently supplied receipt cannot abandon a running adapter.
        if entry.stopping is not None and not entry.stopping.done():
            return False
        del self._entries[lease.key]
        return True

    def leases(self, plugin_id=None) -> tuple[RuntimeLease, ...]:
        """Snapshot custody independently of plugin registration records."""
        return tuple(
            entry.lease
            for entry in self._entries.values()
            if plugin_id is None or entry.lease.plugin_id == plugin_id
        )

    def dependency_leases(self) -> tuple[RuntimeLease, ...]:
        """Execution owners plus orphan claims, excluding pure host records."""
        leases = []
        for entry in self._entries.values():
            if entry.custody_only:
                continue
            owner = entry.dependency_owner
            if owner is not None:
                parent = self._entries.get(owner.key)
                if parent is not None and parent.lease == owner:
                    continue
            leases.append(entry.lease)
        return tuple(leases)

    @staticmethod
    async def _invoke(entry):
        try:
            if entry.stop is None:
                return RuntimeStopReceipt(False, "RUNTIME_STOP_UNATTACHED")
            return await entry.stop()
        except Exception as exc:  # noqa: BLE001
            return RuntimeStopReceipt(
                False,
                str(exc) or type(exc).__name__,
                exited=False,
            )

    async def stop(self, lease) -> RuntimeStopReceipt:
        """Stop an exact lease; coalesce concurrent callers."""
        entry = self._entries.get(lease.key)
        if entry is None or entry.lease != lease:
            return RuntimeStopReceipt(True, "RUNTIME_LEASE_ALREADY_RELEASED")
        if entry.stopping is None:
            entry.stopping = asyncio.create_task(self._invoke(entry))
        task = entry.stopping
        try:
            receipt = await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                entry.stopping = None
            raise
        self.release(lease, receipt)
        if entry.stopping is task:
            entry.stopping = None
        return receipt

    async def stop_all(self, plugin_id) -> tuple[RuntimeStopReceipt, ...]:
        """Stop a snapshot without skipping resources after a failure."""
        receipts = []
        for lease in self.leases(plugin_id):
            receipts.append(await self.stop(lease))
        return tuple(receipts)
