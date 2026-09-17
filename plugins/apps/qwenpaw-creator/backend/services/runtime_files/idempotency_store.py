# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Filesystem idempotency reservations with payload-drift detection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from .atomic_store import (
    AtomicJsonRecordStore,
    CreateIfAbsentJsonStore,
    canonical_json_bytes,
)
from .errors import (
    CorruptRecordError,
    IdempotencyConflictError,
    IdempotencyStateConflictError,
    RuntimeFileValidationError,
)
from .locking import CrossProcessFileLock
from .models import IdempotencyRecord, IdempotencyStatus, utc_now

logger = logging.getLogger("qwenpaw.creator.runtime_files.idempotency_store")


@dataclass(frozen=True, slots=True)
class IdempotencyReservation:
    record: IdempotencyRecord
    created: bool


class IdempotencyRecordStore:
    """Persistent reserve/complete/fail semantics without a database index."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        lock_timeout_seconds: float | None = 10.0,
    ) -> None:
        self.root = Path(root)
        self.lock_timeout_seconds = lock_timeout_seconds
        self._create_store = CreateIfAbsentJsonStore(
            self.root,
            IdempotencyRecord,
            lock_timeout_seconds=lock_timeout_seconds,
        )

    @staticmethod
    def request_hash(payload: Any) -> str:
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return f"sha256:{digest}"

    @classmethod
    def operation_id(
        cls,
        *,
        namespace: str,
        owner_id: str,
        scope: str,
        idempotency_key: str,
        request_hash: str,
    ) -> str:
        """Return the stable Runtime operation ID for one reservation.

        The operation ID is persisted as ``record_id`` and may also be used by
        the underlying filesystem transaction.  This gives an ``IN_PROGRESS``
        retry an exact transaction to inspect/recover; no clock or lease-age
        guess is involved.
        """

        namespace = cls._require_text("namespace", namespace)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", namespace):
            raise RuntimeFileValidationError("namespace is not path safe")
        identity = {
            "ownerId": cls._require_text("owner_id", owner_id),
            "scope": cls._require_text("scope", scope),
            "idempotencyKey": cls._require_text(
                "idempotency_key",
                idempotency_key,
            ),
            "requestHash": cls._require_text("request_hash", request_hash),
        }
        digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        return f"{namespace}-{digest}"

    @staticmethod
    def _require_text(name: str, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise RuntimeFileValidationError(f"{name} must not be empty")
        return normalized

    @classmethod
    def _identity_hash(
        cls,
        owner_id: str,
        scope: str,
        idempotency_key: str,
    ) -> str:
        identity = {
            "ownerId": cls._require_text("owner_id", owner_id),
            "scope": cls._require_text("scope", scope),
            "idempotencyKey": cls._require_text(
                "idempotency_key",
                idempotency_key,
            ),
        }
        digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        return f"sha256:{digest}"

    def _key(
        self,
        owner_id: str,
        scope: str,
        idempotency_key: str,
    ) -> tuple[str, str]:
        key_hash = self._identity_hash(owner_id, scope, idempotency_key)
        return key_hash, key_hash.removeprefix("sha256:")

    def _record_store(
        self,
        owner_id: str,
        scope: str,
        idempotency_key: str,
    ) -> AtomicJsonRecordStore[IdempotencyRecord]:
        _key_hash, key = self._key(owner_id, scope, idempotency_key)
        path = self._create_store.path_for(key)
        return AtomicJsonRecordStore(
            path,
            IdempotencyRecord,
            lock_path=self.root / ".locks" / f"{path.name}.lock",
            lock_timeout_seconds=self.lock_timeout_seconds,
        )

    def operation_lock(
        self,
        *,
        owner_id: str,
        scope: str,
        idempotency_key: str,
    ) -> CrossProcessFileLock:
        """Serialize execution/recovery for one idempotency identity.

        This deliberately uses a lock domain separate from the record's
        short atomic-update lock: callers hold it while invoking the backing
        transaction and still need to complete/fail the record without a
        self-deadlock.  ``flock`` releases it if the worker process crashes.
        """

        _key_hash, key = self._key(owner_id, scope, idempotency_key)
        return CrossProcessFileLock(
            self.root / ".operation-locks" / f"{key}.lock",
            timeout_seconds=self.lock_timeout_seconds,
        )

    def get(
        self,
        *,
        owner_id: str,
        scope: str,
        idempotency_key: str,
    ) -> IdempotencyRecord | None:
        return self._record_store(
            owner_id,
            scope,
            idempotency_key,
        ).read_or_none()

    def reserve(
        self,
        *,
        owner_id: str,
        scope: str,
        idempotency_key: str,
        request_hash: str,
        record_id: str | None = None,
    ) -> IdempotencyReservation:
        owner_id = self._require_text("owner_id", owner_id)
        scope = self._require_text("scope", scope)
        idempotency_key = self._require_text(
            "idempotency_key",
            idempotency_key,
        )
        request_hash = self._require_text("request_hash", request_hash)
        key_hash, key = self._key(owner_id, scope, idempotency_key)
        candidate = IdempotencyRecord(
            record_id=record_id or f"idempotency-{uuid4().hex}",
            owner_id=owner_id,
            scope=scope,
            key_hash=key_hash,
            request_hash=request_hash,
        )
        created = self._create_store.create(key, candidate)
        record = candidate if created else self._create_store.read(key)
        if (
            record.owner_id != owner_id
            or record.scope != scope
            or record.key_hash != key_hash
        ):
            raise CorruptRecordError(
                self._create_store.path_for(key),
                "idempotency identity does not match its "
                "content-addressed path",
            )
        if record.request_hash != request_hash:
            logger.info(
                "idempotency replay detected: owner=%s scope=%s key=%s",
                owner_id,
                scope,
                idempotency_key,
            )
            raise IdempotencyConflictError(
                owner_id=owner_id,
                scope=scope,
                idempotency_key=idempotency_key,
                existing_request_hash=record.request_hash,
                request_hash=request_hash,
            )
        logger.debug(
            "idempotency reserved: owner=%s scope=%s key=%s created=%s",
            owner_id,
            scope,
            idempotency_key,
            created,
        )
        return IdempotencyReservation(record=record, created=created)

    @staticmethod
    def _assert_request(
        record: IdempotencyRecord,
        *,
        owner_id: str,
        scope: str,
        idempotency_key: str,
        request_hash: str,
    ) -> None:
        if record.request_hash != request_hash:
            raise IdempotencyConflictError(
                owner_id=owner_id,
                scope=scope,
                idempotency_key=idempotency_key,
                existing_request_hash=record.request_hash,
                request_hash=request_hash,
            )

    def complete(
        self,
        *,
        owner_id: str,
        scope: str,
        idempotency_key: str,
        request_hash: str,
        response: dict[str, Any],
        response_status: int = 200,
    ) -> IdempotencyRecord:
        store = self._record_store(owner_id, scope, idempotency_key)

        def transition(record: IdempotencyRecord) -> IdempotencyRecord:
            self._assert_request(
                record,
                owner_id=owner_id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if record.status is IdempotencyStatus.COMPLETED:
                if (
                    record.response == response
                    and record.response_status == response_status
                ):
                    return record
                raise IdempotencyStateConflictError(
                    expected=IdempotencyStatus.IN_PROGRESS.value,
                    actual=record.status.value,
                )
            if record.status is not IdempotencyStatus.IN_PROGRESS:
                raise IdempotencyStateConflictError(
                    expected=IdempotencyStatus.IN_PROGRESS.value,
                    actual=record.status.value,
                )
            return record.model_copy(
                update={
                    "status": IdempotencyStatus.COMPLETED,
                    "response": response,
                    "response_status": response_status,
                    "error": None,
                    "updated_at": utc_now(),
                },
            )

        result = store.update(transition).value
        logger.debug(
            "idempotency completed: owner=%s scope=%s key=%s",
            owner_id,
            scope,
            idempotency_key,
        )
        return result

    def fail(
        self,
        *,
        owner_id: str,
        scope: str,
        idempotency_key: str,
        request_hash: str,
        error: dict[str, Any],
        response_status: int,
    ) -> IdempotencyRecord:
        store = self._record_store(owner_id, scope, idempotency_key)

        def transition(record: IdempotencyRecord) -> IdempotencyRecord:
            self._assert_request(
                record,
                owner_id=owner_id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if record.status is IdempotencyStatus.FAILED:
                if (
                    record.error == error
                    and record.response_status == response_status
                ):
                    return record
                raise IdempotencyStateConflictError(
                    expected=IdempotencyStatus.IN_PROGRESS.value,
                    actual=record.status.value,
                )
            if record.status is not IdempotencyStatus.IN_PROGRESS:
                raise IdempotencyStateConflictError(
                    expected=IdempotencyStatus.IN_PROGRESS.value,
                    actual=record.status.value,
                )
            return record.model_copy(
                update={
                    "status": IdempotencyStatus.FAILED,
                    "error": error,
                    "response_status": response_status,
                    "response": None,
                    "updated_at": utc_now(),
                },
            )

        result = store.update(transition).value
        logger.debug(
            "idempotency failed: owner=%s scope=%s key=%s",
            owner_id,
            scope,
            idempotency_key,
        )
        return result

    def fail_if_in_progress(
        self,
        *,
        owner_id: str,
        scope: str,
        idempotency_key: str,
        request_hash: str,
        error: dict[str, Any],
        response_status: int,
    ) -> IdempotencyRecord:
        """Persist the first failure without masking a concurrent terminal result.

        A mutation may fail while another worker or a post-publication recovery
        completes the same reservation.  In that case its existing terminal
        result wins.  Otherwise this transition guarantees a handled failure is
        not left as an immortal ``IN_PROGRESS`` record.
        """

        store = self._record_store(owner_id, scope, idempotency_key)

        def transition(record: IdempotencyRecord) -> IdempotencyRecord:
            self._assert_request(
                record,
                owner_id=owner_id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if record.status is not IdempotencyStatus.IN_PROGRESS:
                return record
            return record.model_copy(
                update={
                    "status": IdempotencyStatus.FAILED,
                    "error": error,
                    "response_status": response_status,
                    "response": None,
                    "updated_at": utc_now(),
                },
            )

        return store.update(transition).value
