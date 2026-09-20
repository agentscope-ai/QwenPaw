# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements,try-except-raise
# pylint: disable=unnecessary-lambda
"""Deterministic JSON encoding and ETags for ``project.json``."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any

from pydantic import BaseModel, ValidationError

from .migrations import ProjectMigrationError, migrate_project_document
from .models import Project, R2VCreation


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


# Frozen field order is part of the historical ETag, even for retired data.
# These names only encode old journal bytes; they do not validate, expose or
# restore authoring rows in the current Project model.
_RETIRED_SHOT_FIELDS = (
    "shot_id",
    "description",
    "camera",
    "framing",
    "camera_description",
    "dialogue",
    "duration_seconds",
    "character_refs",
    "scene_ref",
    "prop_refs",
)


def _retired_shots_data(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return _source_document_data(value, None)
    ordered: dict[str, Any] = {}
    for name in ("items", "order", *sorted(set(value) - {"order", "items"})):
        if name not in value:
            continue
        item = value[name]
        if name == "items" and isinstance(item, Mapping):
            ordered[name] = {}
            for key in sorted(item):
                row = item[key]
                if isinstance(row, Mapping):
                    row = {
                        field: _source_document_data(row[field], None)
                        for field in (
                            *_RETIRED_SHOT_FIELDS,
                            *sorted(set(row) - set(_RETIRED_SHOT_FIELDS)),
                        )
                        if field in row
                    }
                ordered[name][key] = row
        else:
            ordered[name] = _source_document_data(item, None)
    return ordered


def _source_document_data(value: Any, model_value: Any) -> Any:
    """Order a historical document as its matching Project model did.

    Migrations intentionally add fields only in memory.  ETags recorded by an
    older Runtime therefore need the source schema's field set and values, but
    the declared Project field order rather than alphabetically sorted object
    keys.  Walking the validated current model supplies that stable order while
    the raw document decides which historical fields were present.
    """

    if isinstance(value, Mapping):
        if isinstance(model_value, BaseModel):
            fields = list(type(model_value).model_fields)
            if isinstance(model_value, R2VCreation):
                fields.insert(fields.index("recipe"), "shots")
                fields.append("min_dialogue_ratio")
            ordered = {
                name: (
                    _retired_shots_data(value[name])
                    if isinstance(model_value, R2VCreation) and name == "shots"
                    else _source_document_data(
                        value[name],
                        getattr(model_value, name, None),
                    )
                )
                for name in fields
                if name in value
            }
            # Retain other legacy-only keys in the persisted identity while
            # the current typed view may deliberately ignore them.
            ordered.update(
                (name, _source_document_data(value[name], None))
                for name in sorted(set(value) - set(fields))
            )
            return ordered
        if isinstance(model_value, Mapping):
            return {
                name: _source_document_data(value[name], model_value.get(name))
                for name in sorted(value)
            }
        return {
            name: _source_document_data(value[name], None)
            for name in sorted(value)
        }
    if isinstance(value, list):
        model_items = (
            model_value if isinstance(model_value, (list, tuple)) else ()
        )
        return [
            _source_document_data(
                item,
                model_items[index] if index < len(model_items) else None,
            )
            for index, item in enumerate(value)
        ]
    return value


def project_document_etag(
    document: Mapping[str, Any],
    *,
    project: Project | None = None,
) -> str:
    """Hash a validated Project using the schema persisted in *document*.

    This keeps a Project ETag stable across an in-memory schema migration, so
    historical commit journals and the current authority remain comparable.
    New writes still use :func:`project_etag` for the current schema.
    """

    validated = project or load_project_document(document)
    source_data = _source_document_data(document, validated)
    payload = json.dumps(
        source_data,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_project_document(raw: Mapping[str, Any]) -> Project:
    """Migrate and validate one already-parsed Project document."""

    try:
        migrated = migrate_project_document(raw)
        return Project.model_validate(migrated)
    except (ProjectMigrationError, ValidationError) as exc:
        raise CanonicalJsonError(
            "project.json does not match the Project schema",
        ) from exc


def _parse_project_json(payload: bytes | str) -> dict[str, Any]:
    """Parse one Project JSON object, rejecting ambiguous JSON input."""

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
            parse_constant=lambda value: _raise_invalid_constant(value),
        )
    except CanonicalJsonError:
        raise
    except json.JSONDecodeError as exc:
        raise CanonicalJsonError("project.json is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise CanonicalJsonError("project.json root must be an object")
    return raw


def load_project_json_with_etag(
    payload: bytes | str,
) -> tuple[Project, str]:
    """Parse a Project and retain the persisted schema's semantic ETag."""

    raw = _parse_project_json(payload)
    project = load_project_document(raw)
    return project, project_document_etag(raw, project=project)


def load_project_json(payload: bytes | str) -> Project:
    """Parse one strict Project, rejecting duplicate JSON object keys."""

    project, _etag = load_project_json_with_etag(payload)
    return project


def _raise_invalid_constant(value: str) -> None:
    raise CanonicalJsonError(f"invalid JSON number: {value}")


__all__ = [
    "CanonicalJsonError",
    "canonical_data",
    "canonical_json_bytes",
    "load_project_document",
    "load_project_json",
    "load_project_json_with_etag",
    "project_document_etag",
    "project_etag",
    "project_file_bytes",
]
