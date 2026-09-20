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
from pathlib import Path
from typing import Any, Literal

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field

from ..constant import EnvVarLoader, WORKING_DIR
from .provider import ModelInfo

CATALOG_SCHEMA_VERSION = 1
PACKAGED_CATALOG_PATH = Path(__file__).parent / "data" / "model_catalog.json"
CATALOG_CACHE_DIR = WORKING_DIR / "model_catalog"
OTA_CATALOG_PATH = CATALOG_CACHE_DIR / "model_catalog.json"
LOCAL_CATALOG_PATH = CATALOG_CACHE_DIR / "model_catalog.local.json"
CATALOG_URL_ENV = "QWENPAW_MODEL_CATALOG_URL"
CATALOG_SHA256_ENV = "QWENPAW_MODEL_CATALOG_SHA256"

logger = logging.getLogger(__name__)


class CatalogDocument(BaseModel):
    """Validated model catalog document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=CATALOG_SCHEMA_VERSION)
    catalog_version: str
    published_at: str | None = None
    providers: dict[str, list[ModelInfo]] = Field(default_factory=dict)


def _read_document(path: Path) -> CatalogDocument:
    payload = json.loads(path.read_text(encoding="utf-8"))
    document = CatalogDocument.model_validate(payload)
    if document.schema_version != CATALOG_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported model catalog schema: {document.schema_version}",
        )
    return document


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
    for provider_id, models in document.providers.items():
        providers[provider_id] = []
        for model in models:
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
) -> dict[str, list[ModelInfo]]:
    """Load packaged, OTA, and local model catalogs in priority order."""
    packaged = _read_document(packaged_path)
    catalog = _with_output_source(packaged, "catalog")
    if ota_path.is_file():
        try:
            overlay = _read_document(ota_path)
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
            local = _read_document(local_path)
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
        for model in load_model_catalog().get(catalog_key, [])
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
    document = CatalogDocument.model_validate_json(payload)
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

    install_catalog_payload(
        payload,
        destination,
        expected_sha256=None,
        label="Model catalog",
    )
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
        providers=providers,
    )
    return document.model_dump(mode="json", exclude_none=True)
