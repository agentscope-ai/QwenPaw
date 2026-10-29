# -*- coding: utf-8 -*-
"""Runner-owned request-scoped route and cleanup state."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
import time
from typing import Any

from .models import ResponseOutcome, validate_response_handle

RESPONSE_RECEIPT_TTL_MS = 24 * 60 * 60 * 1000


@dataclass
class ResponseStateError(Exception):
    """Describe one stable response-state violation."""

    reason_code: str
    message: str
    retryable: bool = False


class ResponseRouteKind(StrEnum):
    """Identify the durable Runner route states."""

    ACTIVE = "active"
    REVOKED = "revoked"
    TERMINAL = "terminal"


class ResponseCleanupState(StrEnum):
    """Identify terminal resource cleanup progress."""

    PENDING = "pending"
    COMPLETE = "complete"


@dataclass(frozen=True, order=True)
class ResponseResourceRef:
    """Describe one immutable platform resource used by a response."""

    kind: str
    resource_id: str
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.kind or not self.resource_id:
            raise ValueError("response resource kind and ID are required")
        names = [name for name, _ in self.attributes]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("response resource attributes must be unique")
        if self.attributes != tuple(sorted(self.attributes)):
            raise ValueError("response resource attributes must be sorted")
        if any(not isinstance(value, str) for _, value in self.attributes):
            raise ValueError("response resource attributes must be strings")

    @classmethod
    def create(
        cls,
        kind: str,
        resource_id: str,
        attributes: Mapping[str, str] | None = None,
    ) -> "ResponseResourceRef":
        """Create one normalized immutable resource reference."""
        return cls(
            kind=kind,
            resource_id=resource_id,
            attributes=tuple(sorted((attributes or {}).items())),
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the closed JSON-compatible representation."""
        return {
            "kind": self.kind,
            "resource_id": self.resource_id,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "ResponseResourceRef":
        """Parse one closed JSON-compatible resource reference."""
        if not isinstance(value, Mapping):
            raise ValueError("response resource ref must be an object")
        if set(value) != {"kind", "resource_id", "attributes"}:
            raise ValueError("response resource ref must be closed")
        kind = value.get("kind")
        resource_id = value.get("resource_id")
        attributes = value.get("attributes")
        if not isinstance(kind, str) or not isinstance(resource_id, str):
            raise ValueError("response resource identity must be text")
        if not isinstance(attributes, Mapping) or any(
            not isinstance(name, str) or not isinstance(item, str)
            for name, item in attributes.items()
        ):
            raise ValueError("response resource attributes are invalid")
        return cls.create(kind, resource_id, attributes)


@dataclass(frozen=True)
class ResponseRouteSnapshot:
    """Represent one complete versioned route or finish receipt."""

    response_handle: str
    kind: ResponseRouteKind
    version: int
    route_refs: tuple[ResponseResourceRef, ...] = ()
    resource_refs: tuple[ResponseResourceRef, ...] = ()
    outcome: ResponseOutcome | None = None
    cleanup_state: ResponseCleanupState | None = None
    closed_at_ms: int | None = None
    cleanup_completed_at_ms: int | None = None
    expires_at_ms: int | None = None

    def __post_init__(self) -> None:
        validate_response_handle(self.response_handle)
        if self.version <= 0:
            raise ValueError("response route version must be positive")
        if self.route_refs != _normalize_refs(self.route_refs):
            raise ValueError("response route refs must be sorted and unique")
        if self.resource_refs != _normalize_refs(self.resource_refs):
            raise ValueError(
                "response resource refs must be sorted and unique",
            )
        if self.kind is ResponseRouteKind.ACTIVE:
            self._validate_active()
        elif self.kind is ResponseRouteKind.REVOKED:
            self._validate_revoked()
        else:
            self._validate_terminal()

    def _validate_active(self) -> None:
        terminal_values = (
            self.outcome,
            self.cleanup_state,
            self.closed_at_ms,
            self.cleanup_completed_at_ms,
            self.expires_at_ms,
        )
        if any(value is not None for value in terminal_values):
            raise ValueError("active response route has terminal state")

    def _validate_revoked(self) -> None:
        """Validate an execution-side route revocation snapshot."""
        revoked_values = (
            self.outcome,
            self.cleanup_state,
            self.closed_at_ms,
            self.cleanup_completed_at_ms,
            self.expires_at_ms,
        )
        if any(value is not None for value in revoked_values):
            raise ValueError("revoked response route has terminal state")

    def _validate_terminal(self) -> None:
        if (
            self.outcome is None
            or self.cleanup_state is None
            or self.closed_at_ms is None
            or self.closed_at_ms < 0
        ):
            raise ValueError("terminal response receipt is incomplete")
        if self.cleanup_state is ResponseCleanupState.PENDING:
            if (
                self.cleanup_completed_at_ms is not None
                or self.expires_at_ms is not None
            ):
                raise ValueError("pending cleanup cannot expire")
            return
        if (
            self.cleanup_completed_at_ms is None
            or self.expires_at_ms is None
            or self.cleanup_completed_at_ms < self.closed_at_ms
            or self.expires_at_ms < self.cleanup_completed_at_ms
        ):
            raise ValueError("complete response receipt times are invalid")

    def to_mapping(self) -> dict[str, object]:
        """Return a deterministic closed JSON-compatible snapshot."""
        value: dict[str, object] = {
            "response_handle": self.response_handle,
            "kind": self.kind.value,
            "version": self.version,
            "route_refs": [item.to_mapping() for item in self.route_refs],
            "resource_refs": [
                item.to_mapping() for item in self.resource_refs
            ],
        }
        if self.kind is ResponseRouteKind.TERMINAL:
            if self.outcome is None or self.cleanup_state is None:
                raise ValueError("terminal response receipt is incomplete")
            value.update(
                {
                    "outcome": self.outcome.value,
                    "cleanup_state": self.cleanup_state.value,
                    "closed_at_ms": self.closed_at_ms,
                    "cleanup_completed_at_ms": (self.cleanup_completed_at_ms),
                    "expires_at_ms": self.expires_at_ms,
                },
            )
        return value

    @classmethod
    def from_mapping(cls, value: object) -> "ResponseRouteSnapshot":
        """Parse and validate one closed persisted snapshot."""
        if not isinstance(value, Mapping):
            raise ValueError("response route snapshot must be an object")
        kind_value = value.get("kind")
        if not isinstance(kind_value, str):
            raise ValueError("response route kind is invalid")
        try:
            kind = ResponseRouteKind(kind_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("response route kind is invalid") from exc
        required = {
            "response_handle",
            "kind",
            "version",
            "route_refs",
            "resource_refs",
        }
        terminal = {
            "outcome",
            "cleanup_state",
            "closed_at_ms",
            "cleanup_completed_at_ms",
            "expires_at_ms",
        }
        expected = (
            required | terminal
            if kind is ResponseRouteKind.TERMINAL
            else required
        )
        if set(value) != expected:
            raise ValueError("response route snapshot must be closed")
        handle = value.get("response_handle")
        version = value.get("version")
        route_refs = value.get("route_refs")
        resource_refs = value.get("resource_refs")
        if not isinstance(handle, str) or not isinstance(version, int):
            raise ValueError("response route identity is invalid")
        if not isinstance(route_refs, list) or not isinstance(
            resource_refs,
            list,
        ):
            raise ValueError("response resource ref lists are invalid")
        outcome = None
        cleanup_state = None
        if kind is ResponseRouteKind.TERMINAL:
            try:
                outcome_value = value.get("outcome")
                cleanup_value = value.get("cleanup_state")
                if not isinstance(outcome_value, str) or not isinstance(
                    cleanup_value,
                    str,
                ):
                    raise ValueError("response terminal state is invalid")
                outcome = ResponseOutcome(outcome_value)
                cleanup_state = ResponseCleanupState(cleanup_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("response terminal state is invalid") from exc
        return cls(
            response_handle=handle,
            kind=kind,
            version=version,
            route_refs=_normalize_refs(
                ResponseResourceRef.from_mapping(item) for item in route_refs
            ),
            resource_refs=_normalize_refs(
                ResponseResourceRef.from_mapping(item)
                for item in resource_refs
            ),
            outcome=outcome,
            cleanup_state=cleanup_state,
            closed_at_ms=_optional_int(value, "closed_at_ms"),
            cleanup_completed_at_ms=_optional_int(
                value,
                "cleanup_completed_at_ms",
            ),
            expires_at_ms=_optional_int(value, "expires_at_ms"),
        )


@dataclass(frozen=True)
class RunnerDeliveryResult:
    """Carry internal resource evidence beside one outbound result."""

    outbound_result: object
    resource_refs: tuple[ResponseResourceRef, ...] = ()

    def __post_init__(self) -> None:
        if self.resource_refs != _normalize_refs(self.resource_refs):
            raise ValueError("runner resource refs must be sorted and unique")


class ResponseRouteAggregate:
    """Own all bounded Runner response route and cleanup transitions."""

    def __init__(
        self,
        *,
        max_entries: int,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._entries: dict[str, ResponseRouteSnapshot] = {}

    def open(
        self,
        response_handle: str,
        route_refs: Iterable[ResponseResourceRef] = (),
    ) -> tuple[ResponseRouteSnapshot, bool]:
        """Open one active route and report whether it was newly created."""
        handle = validate_response_handle(response_handle)
        normalized = _normalize_refs(route_refs)
        existing = self._entries.get(handle)
        if existing is not None:
            if existing.kind is not ResponseRouteKind.ACTIVE:
                raise ResponseStateError(
                    "RESPONSE_CLOSED",
                    "response route is closed",
                )
            if existing.route_refs != normalized:
                raise ResponseStateError(
                    "RESPONSE_ROUTE_CONFLICT",
                    "response handle has a different route",
                )
            return existing, False
        self._ensure_capacity()
        snapshot = ResponseRouteSnapshot(
            response_handle=handle,
            kind=ResponseRouteKind.ACTIVE,
            version=1,
            route_refs=normalized,
        )
        self._entries[handle] = snapshot
        return snapshot, True

    def restore(self, snapshot: ResponseRouteSnapshot) -> bool:
        """Restore one snapshot unless an equal or newer version exists."""
        if self._is_expired(snapshot):
            return False
        existing = self._entries.get(snapshot.response_handle)
        if existing is not None:
            if (
                existing.kind is ResponseRouteKind.TERMINAL
                and snapshot.kind is not ResponseRouteKind.TERMINAL
            ):
                return False
            if (
                existing.kind is ResponseRouteKind.REVOKED
                and snapshot.kind is not ResponseRouteKind.REVOKED
            ):
                return False
            if (
                snapshot.kind is ResponseRouteKind.REVOKED
                and existing.kind is ResponseRouteKind.ACTIVE
                and snapshot.version <= existing.version
            ):
                return False
            if existing.version >= snapshot.version:
                if (
                    existing != snapshot
                    and existing.version == snapshot.version
                ):
                    raise ResponseStateError(
                        "RESPONSE_ROUTE_CONFLICT",
                        "response snapshot version conflicts",
                    )
                return False
        else:
            self._ensure_capacity()
        self._entries[snapshot.response_handle] = snapshot
        return True

    def begin_revocation(
        self,
        response_handle: str,
    ) -> ResponseRouteSnapshot | None:
        """Fence one active route before its durable deletion."""
        snapshot = self._entries.get(response_handle)
        if snapshot is None:
            return None
        if snapshot.kind is ResponseRouteKind.REVOKED:
            return snapshot
        if snapshot.kind is not ResponseRouteKind.ACTIVE:
            raise ResponseStateError(
                "RESPONSE_CLOSED",
                "terminal response receipt cannot be discarded",
            )
        revoked = replace(
            snapshot,
            kind=ResponseRouteKind.REVOKED,
            version=snapshot.version + 1,
        )
        self._entries[response_handle] = revoked
        return revoked

    def commit_revocation(self, snapshot: ResponseRouteSnapshot) -> None:
        """Confirm that the revoked snapshot is durable."""
        current = self._entries.get(snapshot.response_handle)
        if (
            current != snapshot
            or snapshot.kind is not ResponseRouteKind.REVOKED
        ):
            raise RuntimeError("response revocation snapshot is stale")

    def pending_revocations(self) -> tuple[ResponseRouteSnapshot, ...]:
        """Return revoked routes awaiting durable deletion."""
        return tuple(
            snapshot
            for snapshot in self.snapshots()
            if snapshot.kind is ResponseRouteKind.REVOKED
        )

    def commit_discard(self, snapshot: ResponseRouteSnapshot) -> None:
        """Remove a revoked route after checkpoint deletion commits."""
        if (
            self._entries.get(snapshot.response_handle) == snapshot
            and snapshot.kind is ResponseRouteKind.REVOKED
        ):
            self._entries.pop(snapshot.response_handle, None)

    def rollback_open(self, response_handle: str, version: int) -> None:
        """Rollback a failed first checkpoint without touching newer state."""
        snapshot = self._entries.get(response_handle)
        if (
            snapshot is not None
            and snapshot.kind is ResponseRouteKind.ACTIVE
            and snapshot.version == version
            and not snapshot.resource_refs
        ):
            self._entries.pop(response_handle, None)

    def admit_operation(self, response_handle: str) -> bool:
        """Admit an operation and report whether its handle is scoped."""
        snapshot = self._entries.get(response_handle)
        if snapshot is None:
            return False
        if snapshot.kind is not ResponseRouteKind.ACTIVE:
            raise ResponseStateError(
                "RESPONSE_CLOSED",
                "response route is closed",
            )
        return True

    def record_delivery(
        self,
        response_handle: str,
        resource_refs: Iterable[ResponseResourceRef],
    ) -> ResponseRouteSnapshot:
        """Record recoverable platform evidence after one side effect."""
        snapshot = self._require_active(response_handle)
        resources = _merge_refs(snapshot.resource_refs, resource_refs)
        if resources == snapshot.resource_refs:
            return snapshot
        updated = replace(
            snapshot,
            version=snapshot.version + 1,
            resource_refs=resources,
        )
        self._entries[response_handle] = updated
        return updated

    def begin_finish(
        self,
        response_handle: str,
        outcome: ResponseOutcome,
    ) -> ResponseRouteSnapshot:
        """Close execution admission and create a pending finish receipt."""
        snapshot = self._entries.get(response_handle)
        if snapshot is None:
            raise ResponseStateError(
                "RESPONSE_HANDLE_UNKNOWN",
                "response handle is unknown",
            )
        if snapshot.kind is ResponseRouteKind.REVOKED:
            raise ResponseStateError(
                "RESPONSE_CLOSED",
                "response route is closed",
            )
        if snapshot.kind is ResponseRouteKind.TERMINAL:
            if snapshot.outcome is not outcome:
                raise ResponseStateError(
                    "RESPONSE_OUTCOME_CONFLICT",
                    "response outcome conflicts with a prior finish",
                )
            return snapshot
        updated = replace(
            snapshot,
            kind=ResponseRouteKind.TERMINAL,
            version=snapshot.version + 1,
            outcome=outcome,
            cleanup_state=ResponseCleanupState.PENDING,
            closed_at_ms=self._clock_ms(),
        )
        self._entries[response_handle] = updated
        return updated

    def cleanup_candidate(
        self,
        response_handle: str,
        outcome: ResponseOutcome,
    ) -> ResponseRouteSnapshot:
        """Build a complete receipt without publishing it in memory."""
        snapshot = self._require_terminal(response_handle, outcome)
        if snapshot.cleanup_state is ResponseCleanupState.COMPLETE:
            return snapshot
        completed_at_ms = self._clock_ms()
        return replace(
            snapshot,
            version=snapshot.version + 1,
            cleanup_state=ResponseCleanupState.COMPLETE,
            cleanup_completed_at_ms=completed_at_ms,
            expires_at_ms=completed_at_ms + RESPONSE_RECEIPT_TTL_MS,
        )

    def commit_cleanup(self, candidate: ResponseRouteSnapshot) -> None:
        """Publish a receipt after its complete snapshot is durable."""
        current = self._entries.get(candidate.response_handle)
        if current == candidate:
            return
        if (
            current is None
            or current.kind is not ResponseRouteKind.TERMINAL
            or current.outcome is not candidate.outcome
            or current.version + 1 != candidate.version
            or candidate.cleanup_state is not ResponseCleanupState.COMPLETE
        ):
            raise RuntimeError("response cleanup candidate is stale")
        self._entries[candidate.response_handle] = candidate

    def snapshot(self, response_handle: str) -> ResponseRouteSnapshot | None:
        """Return one immutable aggregate snapshot."""
        return self._entries.get(response_handle)

    def snapshots(self) -> tuple[ResponseRouteSnapshot, ...]:
        """Return all aggregate snapshots in deterministic order."""
        return tuple(self._entries[key] for key in sorted(self._entries))

    def pending_cleanups(self) -> tuple[ResponseRouteSnapshot, ...]:
        """Return cleanup-pending receipts in deterministic order."""
        return tuple(
            snapshot
            for snapshot in self.snapshots()
            if snapshot.cleanup_state is ResponseCleanupState.PENDING
        )

    def active_route_refs(
        self,
        response_handle: str,
    ) -> tuple[ResponseResourceRef, ...]:
        """Return immutable route refs for one active response."""
        return self._require_active(response_handle).route_refs

    def resource_ref(
        self,
        response_handle: str,
        resource_id: str,
    ) -> ResponseResourceRef | None:
        """Return one active response resource by platform delivery ID."""
        snapshot = self._require_active(response_handle)
        return next(
            (
                item
                for item in snapshot.resource_refs
                if item.resource_id == resource_id
            ),
            None,
        )

    def expired_completed(self) -> tuple[ResponseRouteSnapshot, ...]:
        """Return expired cleanup-complete receipts without removing them."""
        return tuple(
            snapshot
            for snapshot in self.snapshots()
            if self._is_expired(snapshot)
        )

    def commit_gc(self, candidate: ResponseRouteSnapshot) -> None:
        """Remove an expired receipt after checkpoint deletion commits."""
        if self._entries.get(
            candidate.response_handle,
        ) == candidate and self._is_expired(candidate):
            self._entries.pop(candidate.response_handle, None)

    def _require_active(self, response_handle: str) -> ResponseRouteSnapshot:
        snapshot = self._entries.get(response_handle)
        if snapshot is None:
            raise ResponseStateError(
                "RESPONSE_HANDLE_UNKNOWN",
                "response handle is unknown",
            )
        if snapshot.kind is not ResponseRouteKind.ACTIVE:
            raise ResponseStateError(
                "RESPONSE_CLOSED",
                "response route is closed",
            )
        return snapshot

    def _require_terminal(
        self,
        response_handle: str,
        outcome: ResponseOutcome,
    ) -> ResponseRouteSnapshot:
        snapshot = self._entries.get(response_handle)
        if snapshot is None or snapshot.kind is not ResponseRouteKind.TERMINAL:
            raise RuntimeError("response cleanup requires a terminal receipt")
        if snapshot.outcome is not outcome:
            raise ResponseStateError(
                "RESPONSE_OUTCOME_CONFLICT",
                "response outcome conflicts with cleanup",
            )
        return snapshot

    def _ensure_capacity(self) -> None:
        if len(self._entries) >= self.max_entries:
            raise ResponseStateError(
                "RESPONSE_SCOPE_LIMIT",
                "response route capacity is exhausted",
                retryable=True,
            )

    def _is_expired(self, snapshot: ResponseRouteSnapshot) -> bool:
        return bool(
            snapshot.cleanup_state is ResponseCleanupState.COMPLETE
            and snapshot.expires_at_ms is not None
            and self._clock_ms() >= snapshot.expires_at_ms,
        )


def _normalize_refs(
    refs: Iterable[ResponseResourceRef],
) -> tuple[ResponseResourceRef, ...]:
    by_identity = {(item.kind, item.resource_id): item for item in refs}
    return tuple(sorted(by_identity.values()))


def _merge_refs(
    existing: Iterable[ResponseResourceRef],
    updates: Iterable[ResponseResourceRef],
) -> tuple[ResponseResourceRef, ...]:
    by_identity = {(item.kind, item.resource_id): item for item in existing}
    for item in updates:
        by_identity[(item.kind, item.resource_id)] = item
    return tuple(sorted(by_identity.values()))


def _optional_int(value: Mapping[str, Any], name: str) -> int | None:
    item = value.get(name)
    if item is not None and not isinstance(item, int):
        raise ValueError(f"response route {name} must be an integer or null")
    return item


__all__ = [
    "RESPONSE_RECEIPT_TTL_MS",
    "ResponseCleanupState",
    "ResponseResourceRef",
    "ResponseRouteAggregate",
    "ResponseRouteKind",
    "ResponseRouteSnapshot",
    "ResponseStateError",
    "RunnerDeliveryResult",
]
