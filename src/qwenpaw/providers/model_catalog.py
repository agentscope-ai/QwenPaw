# -*- coding: utf-8 -*-
"""Versioned model catalog loading and atomic OTA updates."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field

from ..constant import EnvVarLoader, WORKING_DIR
from .model_info import ModelInfo, release_date

CATALOG_SCHEMA_VERSION = 2
PACKAGED_CATALOG_PATH = Path(__file__).parent / f"data" / f"index.json"
CATALOG_CACHE_DIR = WORKING_DIR / "model_catalog"
OTA_CATALOG_PATH = CATALOG_CACHE_DIR / "model_catalog.json"
LOCAL_CATALOG_PATH = CATALOG_CACHE_DIR / "model_catalog.local.json"
CATALOG_URL_ENV = "QWENPAW_MODEL_CATALOG_URL"
CATALOG_SHA256_ENV = "QWENPAW_MODEL_CATALOG_SHA256"

logger = logging.getLogger(__name__)


class CatalogProvider(BaseModel):
    """One service's models, endpoint identity, and curated defaults."""

    model_config = ConfigDict(extra=f"forbid")
    api_urls: list[str] = Field(default_factory=list)
    remote_id: str | None = None
    protocols: dict[
        str, Literal["chat", "responses", "anthropic", "gemini"]
    ] = Field(default_factory=dict)
    template_owner: bool = False
    template_model_ids: list[str] | None = None
    template_families: list[str] = Field(default_factory=list)
    default_model_ids: list[str] | None = None
    models: list[ModelInfo] = Field(default_factory=list)


class CatalogDocument(BaseModel):
    """Validated model catalog document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=CATALOG_SCHEMA_VERSION)
    catalog_version: str
    published_at: str | None = None
    source_url: str | None = None
    providers: dict[str, CatalogProvider] = Field(default_factory=dict)


@lru_cache(maxsize=64)
def _read_json(path: Path, modified: int) -> dict:
    """Cache one immutable-on-disk catalog revision."""
    return json.loads(path.read_text(encoding=f"utf-8"))


def _read_document(
    path: Path,
    provider_ids: tuple[str, ...] | None = None,
    *,
    defaults_only: bool = False,
) -> CatalogDocument:
    payload = _read_json(path, path.stat().st_mtime_ns)
    entries = {}
    for key, entry in payload.get(f"providers", {}).items():
        if provider_ids is not None and key not in provider_ids:
            continue
        if defaults_only and f"defaults" in entry:
            entry = entry[f"defaults"]
        elif f"path" in entry:
            shard = (path.parent / entry[f"path"]).resolve()
            if not shard.is_relative_to(path.parent.resolve()):
                raise ValueError(f"Catalog shard escapes its directory")
            entry = _read_shard(
                shard,
                shard.stat().st_mtime_ns,
                entry[f"sha256"],
            )
        entries[key] = entry
    payload = {**payload, f"providers": entries}
    document = CatalogDocument.model_validate(payload)
    if document.schema_version != CATALOG_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported model catalog schema: {document.schema_version}",
        )
    return document


@lru_cache(maxsize=64)
def _read_shard(path: Path, modified: int, digest: str) -> dict:
    """Verify each provider shard once per revision."""
    payload = path.read_bytes()
    verify_catalog_hash(payload, digest, label=f"Provider shard")
    return json.loads(payload)


def matching_catalog_keys(
    provider_id: str,
    endpoint: str,
    model_id: str,
    template_id: str | None,
) -> tuple[str, ...]:
    """Locate exact service and template shards without reading cards."""
    keys = set()
    for path in (
        PACKAGED_CATALOG_PATH,
        METADATA_CACHE_PATH,
        OTA_CATALOG_PATH,
        LOCAL_CATALOG_PATH,
    ):
        try:
            payload = _read_json(path, path.stat().st_mtime_ns)
        except (OSError, ValueError):
            continue
        for key, entry in payload.get(f"providers", {}).items():
            templates = entry.get(f"templates")
            if templates is None:
                templates = entry.get(f"template_model_ids") or [
                    model[f"id"]
                    for model in entry.get(f"models", [])
                    if entry.get(f"template_owner")
                ]
            if (
                key == provider_id
                or endpoint in entry.get(f"api_urls", [])
                or (template_id and template_id.split(f"/", 1)[0] == key)
                or (not template_id and model_id in templates)
            ):
                keys.add(key)
    return tuple(sorted(keys))


def _catalog_version_key(value: str) -> Version | None:
    """Return a PEP 440 key when the catalog version is comparable."""
    try:
        return Version(value)
    except InvalidVersion:
        return None


def _published_at_key(value: str | None) -> datetime | None:
    """Return a normalized timestamp for catalog freshness comparison."""
    if value is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _catalog_freshness(
    candidate: CatalogDocument,
    baseline: CatalogDocument,
) -> Literal["current", "stale", "incomparable"]:
    """Compare catalog versions without treating opaque values as stale."""
    if candidate.catalog_version == baseline.catalog_version:
        return "current"

    candidate_key = _catalog_version_key(candidate.catalog_version)
    baseline_key = _catalog_version_key(baseline.catalog_version)
    if candidate_key is not None and baseline_key is not None:
        return "current" if candidate_key >= baseline_key else "stale"

    candidate_time = _published_at_key(candidate.published_at)
    baseline_time = _published_at_key(baseline.published_at)
    if candidate_time is not None and baseline_time is not None:
        return "current" if candidate_time >= baseline_time else "stale"
    return "incomparable"


def _with_output_source(
    document: CatalogDocument,
    source: Literal["catalog", "user"],
) -> dict[str, list[ModelInfo]]:
    """Attach field-level provenance to explicit output capabilities."""
    providers: dict[str, list[ModelInfo]] = {}
    for provider_id, entry in document.providers.items():
        providers[provider_id] = []
        for model in entry.models:
            if (
                entry.default_model_ids is not None
                and model.id not in entry.default_model_ids
            ):
                continue
            update: dict[str, Any] = {}
            if model.max_output_length is not None:
                update["max_output_length_source"] = source
                update["max_output_length_updated_at"] = document.published_at
            providers[provider_id].append(model.model_copy(update=update))
    return providers


def _merge_models(
    base: dict[str, list[ModelInfo]],
    overlay: dict[str, list[ModelInfo]],
) -> dict[str, list[ModelInfo]]:
    merged = {
        provider_id: [model.model_copy(deep=True) for model in models]
        for provider_id, models in base.items()
    }
    for provider_id, models in overlay.items():
        ordered_ids = [model.id for model in merged.get(provider_id, [])]
        by_id = {model.id: model for model in merged.get(provider_id, [])}
        for model in models:
            if model.id not in by_id:
                ordered_ids.append(model.id)
            previous = by_id.get(model.id)
            payload = previous.model_dump() if previous is not None else {}
            for field_name in model.model_fields_set:
                payload[field_name] = getattr(model, field_name)
            by_id[model.id] = ModelInfo.model_validate(payload)
        merged[provider_id] = [by_id[model_id] for model_id in ordered_ids]
    return merged


def load_model_catalog(
    packaged_path: Path = PACKAGED_CATALOG_PATH,
    ota_path: Path = OTA_CATALOG_PATH,
    local_path: Path = LOCAL_CATALOG_PATH,
    provider_ids: tuple[str, ...] | None = None,
    *,
    defaults_only: bool = False,
) -> dict[str, list[ModelInfo]]:
    """Load packaged, OTA, and local model catalogs in priority order."""
    packaged = _read_document(
        packaged_path,
        provider_ids,
        defaults_only=defaults_only,
    )
    catalog = _with_output_source(packaged, "catalog")
    if ota_path.is_file():
        try:
            overlay = _read_document(
                ota_path,
                provider_ids,
                defaults_only=defaults_only,
            )
        except (OSError, ValueError, json.JSONDecodeError):
            overlay = None
        if overlay is not None:
            freshness = _catalog_freshness(overlay, packaged)
            if freshness == "current":
                catalog = _merge_models(
                    catalog,
                    _with_output_source(overlay, "catalog"),
                )
            elif freshness == "incomparable":
                logger.warning(
                    "Ignoring OTA model catalog because versions %r and "
                    "%r cannot be compared",
                    overlay.catalog_version,
                    packaged.catalog_version,
                )
    if local_path.is_file():
        try:
            local = _read_document(local_path, provider_ids)
        except (OSError, ValueError, json.JSONDecodeError):
            local = None
        if local is not None:
            catalog = _merge_models(
                catalog,
                _with_output_source(local, "user"),
            )
    return catalog


def models_for_catalog_key(catalog_key: str) -> list[ModelInfo]:
    """Return independent model objects for one catalog key."""
    return [
        model.model_copy(deep=True)
        for model in load_model_catalog(
            provider_ids=(catalog_key,),
            defaults_only=True,
        ).get(catalog_key, [])
    ]


def _download_bytes(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "QwenPaw-Model-Catalog/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _replace_with_retry(
    source: Path,
    destination: Path,
    *,
    attempts: int = 5,
    delay: float = 0.1,
) -> None:
    """Atomically replace a catalog despite transient Windows locks."""
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def install_catalog_payload(
    payload: bytes,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    label: str = "Catalog",
) -> None:
    """Verify and atomically install one validated catalog payload."""
    verify_catalog_hash(payload, expected_sha256, label=label)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp_path, destination)
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                # Windows AV/indexers may still hold the handle; never
                # let cleanup mask the original install error.
                pass


def verify_catalog_hash(
    payload: bytes,
    expected_sha256: str | None,
    *,
    label: str,
) -> None:
    """Reject a catalog payload whose configured digest does not match."""
    if expected_sha256:
        actual = hashlib.sha256(payload).hexdigest()
        if actual.lower() != expected_sha256.strip().lower():
            raise ValueError(f"{label} SHA-256 mismatch")


def install_catalog_document(
    document: CatalogDocument,
    destination: Path,
) -> None:
    """Publish immutable provider shards before atomically switching index."""
    index = document.model_dump(mode=f"json", exclude_none=True)
    for key, provider in document.providers.items():
        payload = provider.model_dump_json(exclude_unset=True).encode(f"utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        relative = f"shards/{digest}.json"
        target = destination.parent / relative
        if not target.is_file():
            install_catalog_payload(payload, target, expected_sha256=digest)
        index[f"providers"][key] = {
            f"path": relative,
            f"sha256": digest,
            f"api_urls": provider.api_urls,
            f"defaults": {
                **provider.model_dump(mode=f"json", exclude_none=True),
                f"models": [
                    model.model_dump(mode=f"json", exclude_none=True)
                    for model in provider.models
                    if provider.default_model_ids is None
                    or model.id in provider.default_model_ids
                ],
            },
            f"templates": provider.template_model_ids
            or (
                [model.id for model in provider.models]
                if provider.template_owner
                else []
            ),
        }
    install_catalog_payload(
        json.dumps(index, ensure_ascii=False).encode(f"utf-8"),
        destination,
    )
    read_catalog_cached.cache_clear()


def _download_document(payload: bytes, url: str, timeout: float):
    """Validate remote shard references and hashes before publishing any."""
    data = json.loads(payload)
    for key, entry in data.get(f"providers", {}).items():
        if f"path" not in entry:
            continue
        relative = entry[f"path"]
        parts = urlsplit(relative)
        if (
            parts.scheme
            or parts.netloc
            or parts.query
            or parts.fragment
            or relative.startswith(f"/")
            or f"\\" in relative
            or f".." in relative.split(f"/")
        ):
            raise ValueError(f"Invalid catalog shard reference")
        shard = _download_bytes(urljoin(url, relative), timeout)
        verify_catalog_hash(shard, entry[f"sha256"], label=f"Remote shard")
        data[f"providers"][key] = json.loads(shard)
    return CatalogDocument.model_validate(data)


def update_model_catalog(
    url: str | None = None,
    expected_sha256: str | None = None,
    timeout: float = 10,
    destination: Path = OTA_CATALOG_PATH,
    packaged_path: Path = PACKAGED_CATALOG_PATH,
) -> CatalogDocument:
    """Download, verify, validate, and atomically install an OTA catalog."""
    resolved_url = url or EnvVarLoader.get_str(CATALOG_URL_ENV)
    if not resolved_url:
        raise ValueError(f"{CATALOG_URL_ENV} is not configured")
    digest = expected_sha256 or EnvVarLoader.get_str(CATALOG_SHA256_ENV)
    payload = _download_bytes(resolved_url, timeout)
    verify_catalog_hash(payload, digest, label="Model catalog")
    document = _download_document(payload, resolved_url, timeout)
    if document.schema_version != CATALOG_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported model catalog schema: {document.schema_version}",
        )
    packaged = _read_document(packaged_path)
    freshness = _catalog_freshness(document, packaged)
    if freshness == "stale":
        raise ValueError(
            "Model catalog version is older than the packaged catalog",
        )
    if freshness == "incomparable":
        raise ValueError(
            "Model catalog versions cannot be compared: "
            f"{document.catalog_version!r} and "
            f"{packaged.catalog_version!r}",
        )

    install_catalog_document(document, destination)
    return document


def catalog_payload(
    providers: dict[str, list[ModelInfo]],
    *,
    version: str,
    published_at: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable catalog payload."""
    document = CatalogDocument(
        catalog_version=version,
        published_at=published_at,
        providers={
            key: CatalogProvider(models=models)
            for key, models in providers.items()
        },
    )
    return document.model_dump(mode="json", exclude_none=True)


@lru_cache(maxsize=128)
def read_catalog_cached(
    path: Path,
    modified: int,
    provider_ids: tuple[str, ...] | None = None,
) -> CatalogDocument:
    """Read a validated document once per on-disk revision."""
    return _read_document(path, provider_ids)


def catalog_documents(
    provider_ids: tuple[str, ...] | None = None,
) -> list[tuple[CatalogDocument, str]]:
    """Return available metadata layers without network I/O."""
    documents = []
    for path, source in (
        (PACKAGED_CATALOG_PATH, f"catalog"),
        (METADATA_CACHE_PATH, f"catalog"),
        (OTA_CATALOG_PATH, f"catalog"),
        (LOCAL_CATALOG_PATH, f"user"),
    ):
        try:
            document = read_catalog_cached(
                path,
                path.stat().st_mtime_ns,
                provider_ids,
            )
        except (OSError, ValueError):
            continue
        if (
            source != f"user"
            and documents
            and _catalog_freshness(
                document,
                documents[0][0],
            )
            != f"current"
        ):
            continue
        documents.append((document, source))
    return documents


METADATA_CACHE_PATH = CATALOG_CACHE_DIR / f"model_info.remote.json"
METADATA_URL = f"https://models.dev/api.json"
METADATA_ENABLED_ENV = f"QWENPAW_MODEL_METADATA_ENABLED"
METADATA_REFRESH_INTERVAL = 24 * 60 * 60


def update_model_metadata(timeout: float = 10) -> None:
    """Refresh public metadata in the same schema as the packaged catalog."""
    destination = METADATA_CACHE_PATH
    if destination.is_file():
        age = time.time() - destination.stat().st_mtime
        if 0 <= age < METADATA_REFRESH_INTERVAL:
            try:
                _read_document(destination)
                return
            except (OSError, ValueError):
                pass
    payload = json.loads(_download_bytes(METADATA_URL, timeout))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid remote model metadata")
    baseline = _read_document(PACKAGED_CATALOG_PATH)
    providers = {}
    for key, provider in baseline.providers.items():
        remote = payload.get(provider.remote_id, {})
        if not isinstance(remote, dict):
            continue
        rows = remote.get(f"models", {})
        if not isinstance(rows, dict):
            continue
        models = []
        template_ids = []
        documented = {model.id: model for model in provider.models}
        for model_id, row in rows.items():
            if not isinstance(row, dict):
                continue
            limits = row.get(f"limit", {})
            if not isinstance(limits, dict):
                continue
            fields = {}
            released = release_date(row.get(f"release_date"))
            if released:
                fields[f"released_at"] = released
            if type(row.get(f"tool_call")) is bool:
                fields[f"supports_tool_calling"] = row[f"tool_call"]
            modalities = row.get(f"modalities")
            modalities = (
                modalities.get(f"input")
                if isinstance(modalities, dict)
                else None
            )
            if isinstance(modalities, list):
                for kind in (f"image", f"audio", f"video"):
                    fields[f"supports_{kind}"] = kind in modalities
            for source, target, minimum in (
                (f"context", f"max_input_length", 1000),
                (f"input", f"input_token_limit", 1),
                (f"output", f"max_output_length", 1),
            ):
                value = limits.get(source)
                if type(value) is int and value >= minimum:
                    fields[target] = value
            baseline_model = documented.get(model_id)
            provenance = {}
            if baseline_model is not None:
                for (
                    field,
                    origin,
                ) in baseline_model.capability_provenance.items():
                    if origin.get(f"source") == f"documentation":
                        fields[field] = getattr(baseline_model, field)
                        provenance[field] = origin
            if fields:
                if row.get(f"family") in provider.template_families:
                    template_ids.append(model_id)
                models.append(
                    ModelInfo(
                        id=model_id,
                        name=model_id,
                        capability_provenance=provenance,
                        **fields,
                    )
                )
        if models:
            providers[key] = provider.model_copy(
                update={
                    f"models": models,
                    f"default_model_ids": [],
                    f"template_model_ids": (
                        template_ids
                        if provider.template_families
                        else provider.template_model_ids
                    ),
                }
            )
    if not providers:
        raise ValueError(f"Remote catalog contains no model limits")
    document = CatalogDocument(
        schema_version=CATALOG_SCHEMA_VERSION,
        catalog_version=baseline.catalog_version,
        published_at=datetime.now(timezone.utc).isoformat(),
        source_url=METADATA_URL,
        providers=providers,
    )
    install_catalog_document(document, destination)
    read_catalog_cached.cache_clear()
