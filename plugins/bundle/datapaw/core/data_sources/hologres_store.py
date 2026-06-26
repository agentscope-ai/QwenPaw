# -*- coding: utf-8 -*-
"""Hologres table persistence for data-source records (plaintext config)."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional
from urllib.parse import urlparse

import psycopg2
from psycopg2 import extras
from psycopg2 import errors as pg_errors

from ...constants import (
    DATAPAW_HOLOGRES_DB_ENV,
    DATAPAW_HOLOGRES_HOST_ENV,
    DATAPAW_HOLOGRES_JDBC_URL_ENV,
    DATAPAW_HOLOGRES_PASSWORD_ENV,
    DATAPAW_HOLOGRES_PORT_ENV,
    DATAPAW_HOLOGRES_USER_ENV,
    DEFAULT_DATAPAW_HOLOGRES_DB,
    DEFAULT_DATAPAW_HOLOGRES_HOST,
    DEFAULT_DATAPAW_HOLOGRES_PORT,
)
from .masking import mask_config, restore_config_values
from .models import (
    DataSourceCreateRequest,
    DataSourceRecord,
    DataSourceUpdateRequest,
    _utc_now_iso,
    validate_config_for_type,
)
from .store import DataSourceConflictError, DataSourceNotFoundError

logger = logging.getLogger(__name__)

TABLE_NAME = "datapaw_data_source"

_SELECT_COLUMNS = "id, type, name, config, created_at, updated_at"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS datapaw_data_source (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    name        TEXT NOT NULL,
    config      JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
)
"""

_table_ready = False


def _parse_jdbc_url(jdbc_url: str) -> dict[str, Any]:
    """Parse ``jdbc:postgresql://host:port/dbname`` into connect kwargs."""
    raw = jdbc_url.strip()
    if raw.lower().startswith("jdbc:"):
        raw = raw[5:]
    parsed = urlparse(raw)
    dbname = parsed.path.lstrip("/") if parsed.path else DEFAULT_DATAPAW_HOLOGRES_DB
    port = parsed.port or DEFAULT_DATAPAW_HOLOGRES_PORT
    if not parsed.hostname:
        raise ValueError("Invalid DATAPAW_HOLOGRES_JDBC_URL: missing host")
    return {
        "host": parsed.hostname,
        "port": port,
        "dbname": dbname,
    }


def hologres_connect_kwargs() -> dict[str, Any]:
    """Build psycopg2 connect kwargs from environment variables."""
    jdbc_url = (os.environ.get(DATAPAW_HOLOGRES_JDBC_URL_ENV) or "").strip()
    if jdbc_url:
        params = _parse_jdbc_url(jdbc_url)
    else:
        params = {
            "host": (
                os.environ.get(DATAPAW_HOLOGRES_HOST_ENV)
                or DEFAULT_DATAPAW_HOLOGRES_HOST
            ),
            "port": int(
                os.environ.get(DATAPAW_HOLOGRES_PORT_ENV) or DEFAULT_DATAPAW_HOLOGRES_PORT
            ),
            "dbname": (
                os.environ.get(DATAPAW_HOLOGRES_DB_ENV) or DEFAULT_DATAPAW_HOLOGRES_DB
            ),
        }

    user = (os.environ.get(DATAPAW_HOLOGRES_USER_ENV) or "").strip()
    password = os.environ.get(DATAPAW_HOLOGRES_PASSWORD_ENV) or ""
    if not user or not password:
        raise RuntimeError(
            "Hologres credentials missing: set "
            f"{DATAPAW_HOLOGRES_USER_ENV} and {DATAPAW_HOLOGRES_PASSWORD_ENV}"
        )

    params["user"] = user
    params["password"] = password
    return params


def _connect():
    return psycopg2.connect(**hologres_connect_kwargs())


def ensure_data_source_table() -> None:
    """Create ``datapaw_data_source`` if missing (idempotent)."""
    global _table_ready  # pylint: disable=global-statement
    if _table_ready:
        return

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
        conn.commit()
        _table_ready = True
        logger.info("Ensured Hologres table exists: %s", TABLE_NAME)
    finally:
        conn.close()


def _row_to_record(row: tuple[Any, ...]) -> DataSourceRecord:
    record_id, ds_type, name, config, created_at, updated_at = row
    if isinstance(config, str):
        config = json.loads(config)
    return DataSourceRecord(
        id=record_id,
        type=ds_type,
        name=name,
        config=dict(config),
        created_at=created_at.isoformat()
        if hasattr(created_at, "isoformat")
        else str(created_at),
        updated_at=updated_at.isoformat()
        if hasattr(updated_at, "isoformat")
        else str(updated_at),
    )


class HologresDataSourceStore:
    """CRUD over ``datapaw_data_source`` in Hologres (config stored in plaintext)."""

    def list_all(self, *, masked: bool = True) -> List[DataSourceRecord]:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM {TABLE_NAME}
                    ORDER BY updated_at DESC
                    """
                )
                records = [_row_to_record(row) for row in cur.fetchall()]
        finally:
            conn.close()

        if not masked:
            return records
        return [self._mask_record(record) for record in records]

    def get(self, record_id: str, *, masked: bool = True) -> DataSourceRecord:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM {TABLE_NAME}
                    WHERE id = %s
                    """,
                    (record_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if row is None:
            raise DataSourceNotFoundError(record_id)

        record = _row_to_record(row)
        return self._mask_record(record) if masked else record

    def create(self, payload: DataSourceCreateRequest) -> DataSourceRecord:
        validate_config_for_type(payload.type, payload.config)
        record = DataSourceRecord.new(
            ds_type=payload.type,
            name=payload.name,
            config=dict(payload.config),
        )

        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT 1 FROM {TABLE_NAME}
                    WHERE lower(trim(name)) = lower(trim(%s))
                    LIMIT 1
                    """,
                    (payload.name,),
                )
                if cur.fetchone():
                    raise DataSourceConflictError(payload.name)

                cur.execute(
                    f"""
                    INSERT INTO {TABLE_NAME}
                        (id, type, name, config, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.id,
                        record.type,
                        record.name,
                        extras.Json(record.config),
                        record.created_at,
                        record.updated_at,
                    ),
                )
            conn.commit()
        except pg_errors.UniqueViolation as exc:
            conn.rollback()
            raise DataSourceConflictError(payload.name) from exc
        finally:
            conn.close()

        return self._mask_record(record)

    def update(
        self,
        record_id: str,
        payload: DataSourceUpdateRequest,
    ) -> DataSourceRecord:
        existing = self.get(record_id, masked=False)
        new_name = payload.name if payload.name is not None else existing.name

        if new_name.strip().casefold() != existing.name.strip().casefold():
            conn = _connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT 1 FROM {TABLE_NAME}
                        WHERE lower(trim(name)) = lower(trim(%s))
                          AND id <> %s
                        LIMIT 1
                        """,
                        (new_name, record_id),
                    )
                    if cur.fetchone():
                        raise DataSourceConflictError(new_name)
            finally:
                conn.close()

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

        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {TABLE_NAME}
                    SET name = %s, config = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        updated.name,
                        extras.Json(updated.config),
                        updated.updated_at,
                        record_id,
                    ),
                )
                if cur.rowcount == 0:
                    raise DataSourceNotFoundError(record_id)
            conn.commit()
        except pg_errors.UniqueViolation as exc:
            conn.rollback()
            raise DataSourceConflictError(new_name) from exc
        finally:
            conn.close()

        return self._mask_record(updated)

    def delete(self, record_id: str) -> None:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {TABLE_NAME} WHERE id = %s",
                    (record_id,),
                )
                if cur.rowcount == 0:
                    raise DataSourceNotFoundError(record_id)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _mask_record(record: DataSourceRecord) -> DataSourceRecord:
        return record.model_copy(
            update={"config": mask_config(record.config)},
        )
