# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements,try-except-raise
# pylint: disable=unnecessary-lambda
"""Deterministic JSON encoding and ETags for ``project.json``."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import threading
from typing import Any

from pydantic import BaseModel, ValidationError

from .migrations import ProjectMigrationError, migrate_project_document
from .models import Project, R2VCreation


from .linear_document import EMPTY_PRESENTATION, without_empty_extensions


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
    if isinstance(value, Project):
        data = without_empty_extensions(data)
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
            # Preserve the historic top-level field order in both variants.
            if (
                isinstance(model_value, Project)
                and "narrative_edges" not in fields
            ):
                assets = fields.index("assets")
                fields[assets:assets] = [
                    "narrative_edges",
                    "interactive_presentation",
                ]
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
            if (
                isinstance(model_value, Project)
                and "interactive_presentation" in value
                and "interactive_presentation"
                not in type(model_value).model_fields
            ):
                # Plain Creator only accepts the validated empty form here.
                presentation = value["interactive_presentation"]
                ordered["interactive_presentation"] = {
                    name: presentation[name]
                    for name in EMPTY_PRESENTATION
                    if name in presentation
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


#: One Project read canonicalizes the whole document twice over (rebuild +
#: ``json.dumps`` + digest): measured on a 352-element Project, 20.2 ms of a
#: 54.8 ms ``store.read``.  Discovery polling and the per-second reconcile tick
#: re-read the same unchanged bytes -- 6.5 reads/second with an idle UI -- so
#: the digest of the stored bytes keys a small LRU.  Content-addressed, so a
#: rewrite misses and an eviction only costs one recomputation.
_ETAG_CACHE_LIMIT = 32
_etag_cache: OrderedDict[str, str] = OrderedDict()
_etag_cache_lock = threading.Lock()


def _etag_cache_key(payload: bytes | str) -> str:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(raw).hexdigest()


def project_document_etag(
    document: Mapping[str, Any],
    *,
    project: Project | None = None,
    source_payload: bytes | str | None = None,
) -> str:
    """Hash a validated Project using the schema persisted in *document*.

    This keeps a Project ETag stable across an in-memory schema migration, so
    historical commit journals and the current authority remain comparable.
    New writes still use :func:`project_etag` for the current schema.

    ``source_payload`` is the exact bytes *document* was parsed from.  Handing
    it in enables the content-addressed cache below: the returned ETag is
    byte-identical to the uncached computation, it is just derived once per
    stored revision instead of once per read.
    """

    cache_key = (
        _etag_cache_key(source_payload) if source_payload is not None else None
    )
    if cache_key is not None:
        with _etag_cache_lock:
            cached = _etag_cache.get(cache_key)
            if cached is not None:
                _etag_cache.move_to_end(cache_key)
                return cached
    validated = project or load_project_document(document)
    source_data = _source_document_data(document, validated)
    payload = json.dumps(
        source_data,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    etag = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if cache_key is not None:
        with _etag_cache_lock:
            _etag_cache[cache_key] = etag
            _etag_cache.move_to_end(cache_key)
            while len(_etag_cache) > _ETAG_CACHE_LIMIT:
                _etag_cache.popitem(last=False)
    return etag


def project_edit_document(document: dict[str, Any]) -> dict[str, Any]:
    """Restore this schema's editing view for a verified linear transaction."""
    # Older plain projects had neither title provenance nor video audio flags.
    # These defaults were absent on both sides of historical edits. Restore
    # only the additive fields, never run repairs on the original candidate:
    # that could conceal a genuine change from an earlier writer.
    data = dict(document)
    data.setdefault("name_source", None)
    timelines = data.get("timelines")
    items = timelines.get("items") if isinstance(timelines, dict) else None
    updated_timelines = {}
    if isinstance(items, dict):
        for timeline_id, timeline in items.items():
            if not isinstance(timeline, dict):
                continue
            elements = timeline.get("elements_by_id")
            if not isinstance(elements, dict):
                continue
            updated_elements = {}
            for element_id, element in elements.items():
                creation = (
                    element.get("creation")
                    if isinstance(element, dict)
                    else None
                )
                if (
                    isinstance(creation, dict)
                    and creation.get("type") in ("r2v", "t2v", "i2v")
                    and "generate_audio" not in creation
                ):
                    updated_elements[element_id] = {
                        **element,
                        "creation": {**creation, "generate_audio": True},
                    }
            if updated_elements:
                updated_timelines[timeline_id] = {
                    **timeline,
                    "elements_by_id": {**elements, **updated_elements},
                }
    if updated_timelines:
        data["timelines"] = {
            **timelines,
            "items": {**items, **updated_timelines},
        }
    compact = without_empty_extensions(data)
    if compact is data and (
        "narrative_edges" in data or "interactive_presentation" in data
    ):
        return data
    if "interactive_presentation" not in Project.model_fields:
        return compact
    return {
        **compact,
        "narrative_edges": [],
        "interactive_presentation": {**EMPTY_PRESENTATION, "screens": {}},
    }


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


def load_project_json_with_source(
    payload: bytes | str,
) -> tuple[Project, str, dict[str, Any]]:
    """Parse a Project, retaining its semantic ETag and source document.

    The third element is the exact parsed on-disk representation that
    :func:`project_document_etag` hashed. A commit boundary persists it as the
    transaction ``base.json`` so recovery's
    ``project_document_etag(base.json) == journal.base_etag`` holds even when a
    load-time repair changed a *stored* field (e.g. muting an older overlapping
    narration); the migrated ``model_dump`` would otherwise diverge from the
    source the ETag was taken over and brick crash recovery.
    """

    raw = _parse_project_json(payload)
    project = load_project_document(raw)
    return (
        project,
        project_document_etag(raw, project=project, source_payload=payload),
        raw,
    )


def load_project_json_with_etag(
    payload: bytes | str,
) -> tuple[Project, str]:
    """Parse a Project and retain the persisted schema's semantic ETag."""

    project, etag, _source = load_project_json_with_source(payload)
    return project, etag


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
    "load_project_json_with_source",
    "project_document_etag",
    "project_etag",
    "project_file_bytes",
]
