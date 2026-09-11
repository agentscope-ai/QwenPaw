# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches
"""Generic JSON Pointer diff, hashing, CAS, and merge helpers.

The Project commit boundary deliberately operates on JSON values instead of
knowing about any particular Creator domain entity.  A
model or browser may therefore change several related fields in one request,
while the runtime still detects same-field conflicts without rejecting
unrelated concurrent edits.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal


MISSING = object()


class JsonPointerError(ValueError):
    """Raised for malformed pointers or impossible patch operations."""


class JsonCasConflict(JsonPointerError):
    """Raised when a touched JSON value changed since the caller's base."""

    def __init__(self, conflicts: list[dict[str, str]]) -> None:
        super().__init__("one or more touched JSON fields changed")
        self.conflicts = conflicts


JsonChangeKind = Literal["create", "update", "delete", "reorder"]


@dataclass(frozen=True, slots=True)
class JsonChange:
    kind: JsonChangeKind
    pointer: str
    before: Any
    after: Any

    @property
    def before_hash(self) -> str:
        return hash_json_value(self.before)

    @property
    def after_hash(self) -> str:
        return hash_json_value(self.after)


def escape_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def unescape_pointer_token(value: str) -> str:
    # RFC 6901 requires ~1 to be decoded before ~0.
    return value.replace("~1", "/").replace("~0", "~")


def split_pointer(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise JsonPointerError(f"invalid JSON Pointer: {pointer!r}")
    return tuple(
        unescape_pointer_token(token) for token in pointer[1:].split("/")
    )


def join_pointer(parent: str, token: str) -> str:
    escaped = escape_pointer_token(token)
    return f"/{escaped}" if not parent else f"{parent}/{escaped}"


def value_at(document: Any, pointer: str, *, missing: Any = MISSING) -> Any:
    current = document
    for token in split_pointer(pointer):
        if isinstance(current, dict):
            if token not in current:
                return missing
            current = current[token]
            continue
        if isinstance(current, list):
            try:
                index = int(token)
            except (TypeError, ValueError):
                return missing
            if index < 0 or index >= len(current):
                return missing
            current = current[index]
            continue
        return missing
    return current


def canonical_json_bytes(value: Any) -> bytes:
    """Encode one field-CAS value using JSON-number equality semantics.

    Integral floats normalize to integers so provider-produced ``1.0`` does
    not conflict with an otherwise identical Project field containing ``1``.
    This representation is intentionally different from the typed whole-
    Project ETag encoder in :mod:`services.project_files.serialization`.
    """

    def normalize_numbers(obj: Any) -> Any:
        if isinstance(obj, float) and obj.is_integer():
            return int(obj)
        if isinstance(obj, dict):
            return {k: normalize_numbers(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [normalize_numbers(v) for v in obj]
        return obj

    return json.dumps(
        normalize_numbers(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def hash_json_value(value: Any) -> str:
    raw = b"MISSING" if value is MISSING else canonical_json_bytes(value)
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _same(left: Any, right: Any) -> bool:
    if left is MISSING or right is MISSING:
        return left is right
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def diff_json(
    before: Any,
    after: Any,
    *,
    pointer: str = "",
) -> tuple[JsonChange, ...]:
    """Return a deterministic minimal structural diff.

    Objects recurse by key so disjoint field edits can merge.  Arrays are one
    CAS value because index-level identities are unstable; the Project schema
    uses ``items + order``, making entity edits object-key based and leaving
    only explicit order arrays as list-level conflicts.
    """

    changes: list[JsonChange] = []

    def visit(left: Any, right: Any, path: str) -> None:
        if _same(left, right):
            return
        if isinstance(left, dict) and isinstance(right, dict):
            left_keys = set(left)
            right_keys = set(right)
            for key in sorted(left_keys - right_keys):
                child = join_pointer(path, str(key))
                changes.append(
                    JsonChange(
                        "delete",
                        child,
                        copy.deepcopy(left[key]),
                        MISSING,
                    ),
                )
            for key in sorted(right_keys - left_keys):
                child = join_pointer(path, str(key))
                changes.append(
                    JsonChange(
                        "create",
                        child,
                        MISSING,
                        copy.deepcopy(right[key]),
                    ),
                )
            for key in sorted(left_keys & right_keys):
                visit(left[key], right[key], join_pointer(path, str(key)))
            return
        kind: JsonChangeKind = (
            "reorder" if path.endswith("/order") else "update"
        )
        changes.append(
            JsonChange(kind, path, copy.deepcopy(left), copy.deepcopy(right)),
        )

    visit(before, after, pointer)
    return tuple(changes)


def _parent_and_token(document: Any, pointer: str) -> tuple[Any, str]:
    tokens = split_pointer(pointer)
    if not tokens:
        raise JsonPointerError(
            "root replacement is not a supported patch operation",
        )
    parent: Any = document
    for token in tokens[:-1]:
        if isinstance(parent, dict) and token in parent:
            parent = parent[token]
        elif isinstance(parent, list):
            try:
                parent = parent[int(token)]
            except (ValueError, IndexError) as exc:
                raise JsonPointerError(
                    f"missing JSON Pointer parent: {pointer}",
                ) from exc
        else:
            raise JsonPointerError(f"missing JSON Pointer parent: {pointer}")
    return parent, tokens[-1]


def apply_changes(
    document: Any,
    changes: tuple[JsonChange, ...] | list[JsonChange],
) -> Any:
    result = copy.deepcopy(document)
    # A structural diff never emits both a parent and child operation.  Keep
    # deletes deepest-first nevertheless so callers can also provide a safe
    # hand-built generic patch.
    ordered = sorted(
        changes,
        key=lambda item: (
            0 if item.kind == "delete" else 1,
            -len(split_pointer(item.pointer))
            if item.kind == "delete"
            else len(split_pointer(item.pointer)),
            item.pointer,
        ),
    )
    for change in ordered:
        parent, token = _parent_and_token(result, change.pointer)
        if isinstance(parent, dict):
            if change.kind == "delete":
                if token not in parent:
                    raise JsonPointerError(
                        f"cannot delete missing value: {change.pointer}",
                    )
                del parent[token]
            elif change.kind == "create":
                if token in parent:
                    raise JsonPointerError(
                        f"cannot create existing value: {change.pointer}",
                    )
                parent[token] = copy.deepcopy(change.after)
            else:
                if token not in parent:
                    raise JsonPointerError(
                        f"cannot replace missing value: {change.pointer}",
                    )
                parent[token] = copy.deepcopy(change.after)
            continue
        if isinstance(parent, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise JsonPointerError(
                    f"invalid array index: {change.pointer}",
                ) from exc
            if change.kind == "delete":
                if index < 0 or index >= len(parent):
                    raise JsonPointerError(
                        f"cannot delete missing value: {change.pointer}",
                    )
                del parent[index]
            elif change.kind == "create":
                if index < 0 or index > len(parent):
                    raise JsonPointerError(
                        f"invalid array insertion: {change.pointer}",
                    )
                parent.insert(index, copy.deepcopy(change.after))
            else:
                if index < 0 or index >= len(parent):
                    raise JsonPointerError(
                        f"cannot replace missing value: {change.pointer}",
                    )
                parent[index] = copy.deepcopy(change.after)
            continue
        raise JsonPointerError(
            f"JSON Pointer parent is not a container: {change.pointer}",
        )
    return result


def merge_candidate(
    *,
    base: Any,
    candidate: Any,
    latest: Any,
) -> tuple[Any, tuple[JsonChange, ...]]:
    """Apply ``base -> candidate`` to latest when every touched value matches base."""

    changes = diff_json(base, candidate)
    conflicts: list[dict[str, str]] = []
    for change in changes:
        current = value_at(latest, change.pointer)
        if not _same(change.before, current):
            conflicts.append(
                {
                    "pointer": change.pointer,
                    "expected": change.before_hash,
                    "actual": hash_json_value(current),
                },
            )
    if conflicts:
        raise JsonCasConflict(conflicts)
    return apply_changes(latest, changes), changes


def pointers_overlap(left: str, right: str) -> bool:
    left_tokens = split_pointer(left)
    right_tokens = split_pointer(right)
    shared = min(len(left_tokens), len(right_tokens))
    return left_tokens[:shared] == right_tokens[:shared]
