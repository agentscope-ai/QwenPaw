# -*- coding: utf-8 -*-
"""JSON-file persistence for data-source records."""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from qwenpaw.constant import SECRET_DIR, WORKING_DIR

from ...constants import BUILTIN_DATAPAW_AGENT_ID, DATAPAW_DATA_SOURCE_BACKEND_ENV
from .masking import mask_config, restore_config_values
from .models import (
    DataSourceCreateRequest,
    DataSourceRecord,
    DataSourceUpdateRequest,
    _utc_now_iso,
    validate_config_for_type,
)
from .secrets import (
    config_has_plaintext_secrets,
    decrypt_config,
    encrypt_config,
)

logger = logging.getLogger(__name__)


class DataSourceStoreError(Exception):
    """Base error for store operations."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class DataSourceNotFoundError(DataSourceStoreError):
    """Raised when a record id does not exist."""

    def __init__(self, record_id: str) -> None:
        super().__init__("notFound", f"Data source '{record_id}' not found")
        self.record_id = record_id


class DataSourceConflictError(DataSourceStoreError):
    """Raised when a duplicate name would be created."""

    def __init__(self, name: str) -> None:
        super().__init__("nameConflict", f"Data source name '{name}' already exists")
        self.name = name


def default_store_path() -> Path:
    """Return the default encrypted store path under ``SECRET_DIR``."""
    return (SECRET_DIR / "datapaw" / "data_sources.json").expanduser().resolve()


def legacy_store_path() -> Path:
    """Previous plaintext location (pre-encryption migration)."""
    return (
        Path(WORKING_DIR)
        / "workspaces"
        / BUILTIN_DATAPAW_AGENT_ID
        / "data_sources.json"
    ).expanduser().resolve()


class JsonDataSourceStore:
    """CRUD over an encrypted JSON file of data-source records."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or default_store_path()
        self._migrate_legacy_store_if_needed()

    @property
    def path(self) -> Path:
        return self._path

    def _migrate_legacy_store_if_needed(self) -> None:
        if self._path.exists():
            return
        legacy = legacy_store_path()
        if not legacy.exists():
            return
        try:
            self._ensure_parent()
            shutil.copy2(legacy, self._path)
            self._chmod_file(self._path)
            logger.info("Migrated data sources from legacy path: %s", legacy)
        except OSError as exc:
            logger.warning("Failed to migrate legacy data sources file: %s", exc)

    def _ensure_parent(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._path.parent, 0o700)
        except OSError:
            pass

    @staticmethod
    def _chmod_file(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _read_raw(self) -> List[DataSourceRecord]:
        if not self._path.exists():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read %s: %s", self._path, exc)
            return []

        items = payload.get("items", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []

        records: List[DataSourceRecord] = []
        needs_rewrite = False
        for item in items:
            if not isinstance(item, dict):
                continue
            config = item.get("config")
            if isinstance(config, dict) and config_has_plaintext_secrets(config):
                needs_rewrite = True
            try:
                record = DataSourceRecord.model_validate(item)
                record = record.model_copy(
                    update={"config": decrypt_config(record.config)},
                )
                records.append(record)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Skipping invalid data-source record: %s", exc)

        if needs_rewrite:
            try:
                self._write_raw(records)
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug(
                    "Deferred plaintext→encrypted migration for data sources: %s",
                    exc,
                )

        return records

    def _write_raw(self, records: List[DataSourceRecord]) -> None:
        self._ensure_parent()
        payload = {
            "items": [
                {
                    **record.model_dump(by_alias=False, mode="json"),
                    "config": encrypt_config(record.config),
                }
                for record in records
            ],
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._chmod_file(self._path)

    def list_all(self, *, masked: bool = True) -> List[DataSourceRecord]:
        records = self._read_raw()
        if not masked:
            return records
        return [self._mask_record(record) for record in records]

    def get(self, record_id: str, *, masked: bool = True) -> DataSourceRecord:
        record = self._find(record_id)
        return self._mask_record(record) if masked else record

    def create(self, payload: DataSourceCreateRequest) -> DataSourceRecord:
        validate_config_for_type(payload.type, payload.config)
        records = self._read_raw()
        if self._name_exists(records, payload.name):
            raise DataSourceConflictError(payload.name)

        record = DataSourceRecord.new(
            ds_type=payload.type,
            name=payload.name,
            config=dict(payload.config),
        )
        records.insert(0, record)
        self._write_raw(records)
        return self._mask_record(record)

    def update(
        self,
        record_id: str,
        payload: DataSourceUpdateRequest,
    ) -> DataSourceRecord:
        records = self._read_raw()
        index = self._index_of(records, record_id)
        if index is None:
            raise DataSourceNotFoundError(record_id)

        existing = records[index]
        new_name = payload.name if payload.name is not None else existing.name
        if self._name_exists(records, new_name, exclude_id=record_id):
            raise DataSourceConflictError(new_name)

        new_config = dict(existing.config)
        if payload.config is not None:
            merged = restore_config_values(payload.config, existing.config)
            new_config = {**existing.config, **merged}
            validate_config_for_type(existing.type, new_config)

        updated = existing.model_copy(
            update={
                "name": new_name,
                "config": new_config,
                "updated_at": _utc_now_iso(),
            },
        )
        records[index] = updated
        self._write_raw(records)
        return self._mask_record(updated)

    def delete(self, record_id: str) -> None:
        records = self._read_raw()
        index = self._index_of(records, record_id)
        if index is None:
            raise DataSourceNotFoundError(record_id)
        records.pop(index)
        self._write_raw(records)

    def _find(self, record_id: str) -> DataSourceRecord:
        records = self._read_raw()
        index = self._index_of(records, record_id)
        if index is None:
            raise DataSourceNotFoundError(record_id)
        return records[index]

    @staticmethod
    def _index_of(
        records: List[DataSourceRecord],
        record_id: str,
    ) -> Optional[int]:
        for idx, record in enumerate(records):
            if record.id == record_id:
                return idx
        return None

    @staticmethod
    def _name_exists(
        records: List[DataSourceRecord],
        name: str,
        *,
        exclude_id: Optional[str] = None,
    ) -> bool:
        target = name.strip().casefold()
        for record in records:
            if exclude_id and record.id == exclude_id:
                continue
            if record.name.strip().casefold() == target:
                return True
        return False

    @staticmethod
    def _mask_record(record: DataSourceRecord) -> DataSourceRecord:
        return record.model_copy(
            update={"config": mask_config(record.config)},
        )


DataSourceStore = JsonDataSourceStore


def create_data_source_store(path: Optional[Path] = None):
    """Return JSON or Hologres store based on ``DATAPAW_DATA_SOURCE_BACKEND``."""
    backend = (
        os.environ.get(DATAPAW_DATA_SOURCE_BACKEND_ENV) or "json"
    ).strip().lower()
    if backend == "hologres":
        from .hologres_store import HologresDataSourceStore  # pylint: disable=import-outside-toplevel

        return HologresDataSourceStore()
    return JsonDataSourceStore(path=path)
