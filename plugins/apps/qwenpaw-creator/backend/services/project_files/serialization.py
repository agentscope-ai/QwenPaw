# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements,try-except-raise
# pylint: disable=unnecessary-lambda
"""Deterministic JSON encoding and ETags for ``project.json``."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any

from pydantic import BaseModel, ValidationError

from .migrations import ProjectMigrationError, migrate_project_document
from .models import Project


class CanonicalJsonError(ValueError):
    """Raised when bytes cannot represent one unambiguous Project document."""


def canonical_data(value: Any) -> Any:
    """Convert a Pydantic value to deterministic JSON-compatible data.

    Pydantic model fields retain their declared order. Dynamic map keys are
    sorted, while business-order lists are left untouched.
    """

    if isinstance(value, BaseModel):
        return {
            field_name: canonical_data(getattr(value, field_name))
            for field_name in type(value).model_fields
        }
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalJsonError("JSON object keys must be strings")
        return {key: canonical_data(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonical_data(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalJsonError("datetime must include a timezone")
        return (
            value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
    if isinstance(value, Enum):
        return canonical_data(value.value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError(
                "NaN and Infinity are not valid Project values",
            )
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise CanonicalJsonError(f"unsupported JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    """Serialize typed Project data with one deterministic representation.

    Unlike the field-CAS encoder in :mod:`services.project_files.json_pointer`,
    this preserves the model's integer-versus-float representation. Project
    validation establishes those declared types before persistence and ETag
    generation; callers comparing untyped field values should use the CAS
    encoder instead.
    """

    data = canonical_data(value)
    if pretty:
        text = json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        return (text + "\n").encode("utf-8")
    return json.dumps(
        data,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def project_file_bytes(project: Project) -> bytes:
    """Return the human-readable canonical form persisted on disk."""

    # Revalidate here so callers cannot persist an object mutated through
    # ``object.__setattr__`` or another validation bypass.
    validated = Project.model_validate(project.model_dump(mode="python"))
    return canonical_json_bytes(validated, pretty=True)


def project_etag(project: Project) -> str:
    """Hash semantic canonical JSON, independent of display whitespace."""

    validated = Project.model_validate(project.model_dump(mode="python"))
    digest = hashlib.sha256(canonical_json_bytes(validated)).hexdigest()
    return f"sha256:{digest}"


def load_project_json(payload: bytes | str) -> Project:
    """Parse one strict Project, rejecting duplicate JSON object keys."""

    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalJsonError("project.json must be UTF-8") from exc
    else:
        text = payload

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CanonicalJsonError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    try:
        raw = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_raise_invalid_constant(value)),
        )
    except CanonicalJsonError:
        raise
    except json.JSONDecodeError as exc:
        raise CanonicalJsonError("project.json is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise CanonicalJsonError("project.json root must be an object")
    try:
        migrated = migrate_project_document(raw)
        return Project.model_validate(migrated)
    except (ProjectMigrationError, ValidationError) as exc:
        raise CanonicalJsonError(
            "project.json does not match the Project schema",
        ) from exc


def _raise_invalid_constant(value: str) -> None:
    raise CanonicalJsonError(f"invalid JSON number: {value}")


__all__ = [
    "CanonicalJsonError",
    "canonical_data",
    "canonical_json_bytes",
    "load_project_json",
    "project_etag",
    "project_file_bytes",
]
