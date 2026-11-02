# -*- coding: utf-8 -*-
"""Durable, immutable unknown receipts outside the live route budget."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import time

from .response_lifecycle import ResponseCleanupState, ResponseRouteSnapshot


def receipt_key(namespace: str, handle: str) -> str:
    return namespace + ":" + hashlib.sha256(handle.encode()).hexdigest()


def receipt_path(workspace, channel: str) -> Path:
    workspace = Path(workspace).expanduser().resolve()
    instance = (
        "channel:"
        + hashlib.sha256(
            (str(workspace) + "\0" + channel).encode(),
        ).hexdigest()
    )
    scope = hashlib.sha256((channel + ":" + instance).encode()).hexdigest()
    return workspace / "channel_state" / (scope + ".receipts.sqlite3")


def _namespace(key):
    namespace, separator, digest = key.rpartition(":")
    if (
        not separator
        or not namespace
        or "/" in namespace
        or "\\" in namespace
        or namespace.startswith(".")
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise ValueError("RESPONSE_RECEIPT_KEY")
    return namespace


def validate_receipt(key, value):
    namespace = _namespace(key)
    snapshot = ResponseRouteSnapshot.from_mapping(value)
    if (
        receipt_key(namespace, snapshot.response_handle) != key
        or snapshot.cleanup_state is not ResponseCleanupState.COMPLETE
        or snapshot.route_refs
        or not snapshot.resource_refs
    ):
        raise ValueError("RESPONSE_RECEIPT_INVALID")
    attempts = [
        ref for ref in snapshot.resource_refs if ref.kind.endswith(".attempt")
    ]
    if not attempts:
        raise ValueError("RESPONSE_RECEIPT_INVALID")
    prefixes = {ref.kind.rpartition(".")[0] for ref in attempts}
    for ref in snapshot.resource_refs:
        attrs = dict(ref.attributes)
        if ref.kind.rpartition(".")[0] not in prefixes:
            raise ValueError("RESPONSE_RECEIPT_INVALID")
        if not ref.kind.endswith(".attempt"):
            # Driver compaction may retain native digests or unsettled resource
            # evidence. These immutable refs are never restored as live routes.
            continue
        if (
            attrs.get("state") != "unknown"
            or re.fullmatch(r"[0-9a-f]{64}", attrs.get("fingerprint", ""))
            is None
            or not set(attrs)
            <= {
                "fingerprint",
                "operation",
                "state",
                "reason_code",
                "target_delivery_id",
                "sequence",
            }
        ):
            raise ValueError("RESPONSE_RECEIPT_INVALID")
    raw = json.dumps(
        snapshot.to_mapping(),
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    )
    if len(raw.encode()) > 768 * 1024:
        raise ValueError("RESPONSE_RECEIPT_CAPACITY")
    return namespace, raw


class ResponseReceiptStore:
    """Use short SQLite transactions and close every connection explicitly."""

    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        import sqlite3

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS receipts ("
                "key TEXT PRIMARY KEY, namespace TEXT NOT NULL, "
                "value TEXT NOT NULL, resolution_note TEXT, resolved_at_ms INTEGER)",
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS receipts_namespace "
                "ON receipts(namespace, key)",
            )
            connection.commit()
            return connection
        except BaseException:
            connection.close()
            raise

    def get(self, key):
        _namespace(key)
        if not self.path.exists():
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM receipts WHERE key=?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        validate_receipt(key, value)
        return value

    def put(self, key, value):
        namespace, raw = validate_receipt(key, value)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO receipts(key,namespace,value) VALUES(?,?,?)",
                (key, namespace, raw),
            )
            previous = connection.execute(
                "SELECT value FROM receipts WHERE key=?",
                (key,),
            ).fetchone()[0]
            if previous != raw:
                raise ValueError("RESPONSE_RECEIPT_CONFLICT")

    @staticmethod
    def _row(row):
        return dict(
            key=row[0],
            value=json.loads(row[1]),
            resolution_note=row[2],
            resolved_at_ms=row[3],
        )

    def list(self, namespace=None, *, limit=100, offset=0):
        if (
            type(limit) is not int
            or not 1 <= limit <= 1000
            or type(offset) is not int
            or offset < 0
        ):
            raise ValueError("RESPONSE_RECEIPT_PAGE")
        if not self.path.exists():
            return []
        where, args = (
            ("WHERE namespace=?", (namespace,)) if namespace else ("", ())
        )
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT key,value,resolution_note,resolved_at_ms FROM receipts "
                + where
                + " ORDER BY key LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return [self._row(row) for row in rows]

    def resolve(self, key, note):
        _namespace(key)
        if not isinstance(note, str) or not note.strip() or len(note) > 8192:
            raise ValueError("RESPONSE_RECEIPT_NOTE")
        if not self.path.exists():
            raise ValueError("RESPONSE_RECEIPT_UNKNOWN")
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE receipts SET resolution_note=?,resolved_at_ms=? WHERE key=?",
                (note.strip(), time.time_ns() // 1_000_000, key),
            )
            if cursor.rowcount != 1:
                raise ValueError("RESPONSE_RECEIPT_UNKNOWN")
            row = connection.execute(
                "SELECT key,value,resolution_note,resolved_at_ms FROM receipts WHERE key=?",
                (key,),
            ).fetchone()
        return self._row(row)
