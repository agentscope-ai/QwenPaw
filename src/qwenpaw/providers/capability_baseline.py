# -*- coding: utf-8 -*-
"""Capability baseline — expected multimodal capabilities and discrepancy
reporting for all built-in providers.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ..constant import EnvVarLoader, WORKING_DIR
from .model_catalog import install_catalog_payload, verify_catalog_hash

CAPABILITY_SCHEMA_VERSION = 1
PACKAGED_CAPABILITY_PATH = (
    Path(__file__).parent / "data" / "model_capabilities.json"
)
CAPABILITY_CACHE_DIR = WORKING_DIR / "model_catalog"
OTA_CAPABILITY_PATH = CAPABILITY_CACHE_DIR / "model_capabilities.json"
LOCAL_CAPABILITY_PATH = CAPABILITY_CACHE_DIR / "model_capabilities.local.json"
CAPABILITY_URL_ENV = "QWENPAW_MODEL_CAPABILITY_URL"
CAPABILITY_SHA256_ENV = "QWENPAW_MODEL_CAPABILITY_SHA256"


@dataclass
class ExpectedCapability:
    """Expected multimodal capability of a model based on official docs."""

    provider_id: str
    model_id: str
    expected_image: bool | None  # None = not specified in docs
    expected_video: bool | None
    doc_url: str = ""
    note: str = ""


class CapabilityEntry(BaseModel):
    """Strict capability catalog entry."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    expected_image: StrictBool | None
    expected_video: StrictBool | None
    doc_url: str = ""
    note: str = ""


class CapabilityDocument(BaseModel):
    """Validated capability catalog document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=CAPABILITY_SCHEMA_VERSION)
    catalog_version: str
    published_at: str | None = None
    capabilities: list[CapabilityEntry] = Field(default_factory=list)


@dataclass
class DiscrepancyLog:
    """Record of a mismatch between probe result and expected capability."""

    provider_id: str
    model_id: str
    field: str  # "image" or "video"
    expected: bool | None
    actual: bool
    discrepancy_type: str  # "false_negative" or "false_positive"


class ExpectedCapabilityRegistry:
    """Registry of expected multimodal capabilities
    for all built-in provider models.

    Internally stores
    ``{(provider_id, model_id): ExpectedCapability}`` dict.
    """

    def __init__(
        self,
        packaged_path: Path = PACKAGED_CAPABILITY_PATH,
        ota_path: Path = OTA_CAPABILITY_PATH,
        local_path: Path = LOCAL_CAPABILITY_PATH,
    ) -> None:
        self._packaged_path = packaged_path
        self._ota_path = ota_path
        self._local_path = local_path
        self._data = self._load_snapshot(strict_overlays=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_expected(
        self,
        provider_id: str,
        model_id: str,
    ) -> ExpectedCapability | None:
        """Look up expected capability for a model.

        Returns None if not found.
        """
        return self._data.get((provider_id, model_id))

    def get_all_for_provider(
        self,
        provider_id: str,
    ) -> list[ExpectedCapability]:
        """Get all expected capabilities for a given provider."""
        return [
            cap for (pid, _), cap in self._data.items() if pid == provider_id
        ]

    def reload(self) -> None:
        """Atomically replace the registry with a validated snapshot."""
        self._data = self._load_snapshot(strict_overlays=True)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_snapshot(
        self,
        *,
        strict_overlays: bool,
    ) -> dict[tuple[str, str], ExpectedCapability]:
        """Build a validated packaged, OTA, and local snapshot."""
        entries: dict[tuple[str, str], dict[str, Any]] = {}
        for index, path in enumerate(
            (self._packaged_path, self._ota_path, self._local_path),
        ):
            if index > 0 and not path.is_file():
                continue
            try:
                document = _read_capability_document(path)
            except (OSError, ValueError, json.JSONDecodeError):
                if index == 0 or strict_overlays:
                    raise
                continue
            for item in document.capabilities:
                payload = item.model_dump()
                key = (item.provider_id, item.model_id)
                entries[key] = {**entries.get(key, {}), **payload}
        snapshot: dict[tuple[str, str], ExpectedCapability] = {}
        for item in entries.values():
            capability = ExpectedCapability(**item)
            snapshot[
                (capability.provider_id, capability.model_id)
            ] = capability
        return snapshot


def _read_capability_document(path: Path) -> CapabilityDocument:
    payload = json.loads(path.read_text(encoding="utf-8"))
    document = CapabilityDocument.model_validate(payload)
    if document.schema_version != CAPABILITY_SCHEMA_VERSION:
        raise ValueError("Unsupported capability catalog schema")
    return document


def _download_capability_bytes(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "QwenPaw-Capability-Catalog/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def update_capability_catalog(
    url: str | None = None,
    expected_sha256: str | None = None,
    timeout: float = 10,
    destination: Path = OTA_CAPABILITY_PATH,
) -> CapabilityDocument:
    """Download, validate, and atomically install capability metadata."""
    resolved_url = url or EnvVarLoader.get_str(CAPABILITY_URL_ENV)
    if not resolved_url:
        raise ValueError(f"{CAPABILITY_URL_ENV} is not configured")
    digest = expected_sha256 or EnvVarLoader.get_str(
        CAPABILITY_SHA256_ENV,
    )
    payload = _download_capability_bytes(resolved_url, timeout)
    verify_catalog_hash(payload, digest, label="Capability catalog")
    document = CapabilityDocument.model_validate_json(payload)
    if document.schema_version != CAPABILITY_SCHEMA_VERSION:
        raise ValueError("Unsupported capability catalog schema")
    install_catalog_payload(
        payload,
        destination,
        expected_sha256=None,
        label="Capability catalog",
    )
    return document


def compare_probe_result(
    expected: ExpectedCapability,
    actual_image: bool,
    actual_video: bool,
) -> list[DiscrepancyLog]:
    """Compare a single model's probe result against expected capability.

    Skips comparison when expected_image/expected_video is None.
    When expected != actual, generates a DiscrepancyLog with type:
      - false_negative: expected=True, actual=False (missed detection)
      - false_positive: expected=False, actual=True (wrong detection)
    """
    logs: list[DiscrepancyLog] = []

    for field_name, expected_val, actual_val in [
        ("image", expected.expected_image, actual_image),
        ("video", expected.expected_video, actual_video),
    ]:
        if expected_val is None:
            continue
        if expected_val == actual_val:
            continue
        discrepancy_type = (
            "false_negative" if expected_val is True else "false_positive"
        )
        logs.append(
            DiscrepancyLog(
                provider_id=expected.provider_id,
                model_id=expected.model_id,
                field=field_name,
                expected=expected_val,
                actual=actual_val,
                discrepancy_type=discrepancy_type,
            ),
        )

    return logs
