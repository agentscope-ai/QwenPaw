# -*- coding: utf-8 -*-
"""REST API for DataPaw data-source management.

Mounted by the host at ``/api/datapaw/data-sources``.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path
from pydantic import ValidationError

from ..data_sources.cm_notifier import notify_cm
from ..data_sources.connection_testers import test_connection
from ..data_sources.models import (
    DataSourceCreateRequest,
    DataSourceListResponse,
    DataSourceRecord,
    DataSourceTestRequest,
    DataSourceTestResponse,
    DataSourceUpdateRequest,
    validate_config_for_type,
)
from ..data_sources.store import (
    DataSourceConflictError,
    DataSourceNotFoundError,
    create_data_source_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["datapaw-data-sources"])

_store = create_data_source_store()


def _safe_config_for_log(config: dict) -> dict:
    """Return non-sensitive config fields suitable for server logs."""
    hidden_keys = {"password", "access_key"}
    return {key: value for key, value in config.items() if key not in hidden_keys}


def _validation_http_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _store_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DataSourceNotFoundError):
        return HTTPException(status_code=404, detail=exc.code)
    if isinstance(exc, DataSourceConflictError):
        return HTTPException(status_code=409, detail=exc.code)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    logger.exception("Unexpected data-source store error")
    return HTTPException(status_code=500, detail="internalError")


@router.get(
    "",
    response_model=DataSourceListResponse,
    response_model_by_alias=True,
    summary="List configured data sources",
)
async def list_data_sources() -> DataSourceListResponse:
    """Return all data sources with sensitive config values masked."""
    items = _store.list_all(masked=True)
    return DataSourceListResponse(items=items)


@router.post(
    "/test",
    response_model=DataSourceTestResponse,
    response_model_by_alias=True,
    summary="Test a data-source connection",
)
async def test_data_source_connection(
    body: DataSourceTestRequest,
) -> DataSourceTestResponse:
    """Probe connectivity without persisting configuration."""
    started = time.monotonic()
    try:
        validate_config_for_type(body.type, body.config)
        success, message = test_connection(body.type, body.config)
    except ValueError as exc:
        return DataSourceTestResponse(
            success=False,
            message=str(exc),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Data source connection test failed")
        return DataSourceTestResponse(
            success=False,
            message=str(exc),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    if not success:
        logger.warning(
            "Data source connection test failed: type=%s config=%s message=%s",
            body.type,
            _safe_config_for_log(body.config),
            message,
        )

    return DataSourceTestResponse(
        success=success,
        message=message,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


@router.get(
    "/{record_id}",
    response_model=DataSourceRecord,
    response_model_by_alias=True,
    summary="Get one data source by id",
)
async def get_data_source(
    record_id: str = Path(..., description="Data source id"),
) -> DataSourceRecord:
    """Return one data source; sensitive config values are masked."""
    try:
        return _store.get(record_id, masked=True)
    except DataSourceNotFoundError as exc:
        raise _store_http_error(exc) from exc


@router.post(
    "",
    response_model=DataSourceRecord,
    response_model_by_alias=True,
    summary="Create a data source",
)
async def create_data_source(
    body: DataSourceCreateRequest,
    background_tasks: BackgroundTasks,
) -> DataSourceRecord:
    """Create and persist a new data source."""
    try:
        validate_config_for_type(body.type, body.config)
        created = _store.create(body)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc
    except ValueError as exc:
        raise _validation_http_error(exc) from exc
    except DataSourceConflictError as exc:
        raise _store_http_error(exc) from exc

    background_tasks.add_task(
        notify_cm, "created", _store.get(created.id, masked=False)
    )
    return created


@router.put(
    "/{record_id}",
    response_model=DataSourceRecord,
    response_model_by_alias=True,
    summary="Update a data source",
)
async def update_data_source(
    body: DataSourceUpdateRequest,
    background_tasks: BackgroundTasks,
    record_id: str = Path(..., description="Data source id"),
) -> DataSourceRecord:
    """Update name and/or config; masked secrets are preserved."""
    try:
        updated = _store.update(record_id, body)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc
    except (DataSourceNotFoundError, DataSourceConflictError, ValueError) as exc:
        raise _store_http_error(exc) from exc

    background_tasks.add_task(
        notify_cm, "updated", _store.get(record_id, masked=False)
    )
    return updated


@router.delete(
    "/{record_id}",
    status_code=204,
    summary="Delete a data source",
)
async def delete_data_source(
    background_tasks: BackgroundTasks,
    record_id: str = Path(..., description="Data source id"),
) -> None:
    """Remove a data source by id."""
    try:
        existing = _store.get(record_id, masked=False)
        _store.delete(record_id)
    except DataSourceNotFoundError as exc:
        raise _store_http_error(exc) from exc

    background_tasks.add_task(notify_cm, "deleted", existing)

