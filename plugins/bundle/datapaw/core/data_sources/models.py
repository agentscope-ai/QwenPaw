# -*- coding: utf-8 -*-
"""Pydantic models for data-source management."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

DataSourceType = Literal["mysql", "postgresql", "odps"]

MYSQL_PG_REQUIRED = ("host", "port", "user", "password", "db")
ODPS_REQUIRED = (
    "endpoint",
    "project_name",
    "app_name",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_config_for_type(
    ds_type: DataSourceType,
    config: Dict[str, Any],
) -> None:
    """Raise ValueError when required config fields are missing or invalid."""
    if ds_type in ("mysql", "postgresql"):
        required = MYSQL_PG_REQUIRED
    else:
        required = ODPS_REQUIRED

    for field in required:
        value = config.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"{field}Required")

    if ds_type in ("mysql", "postgresql"):
        try:
            port = int(config["port"])
        except (TypeError, ValueError) as exc:
            raise ValueError("portRequired") from exc
        if port < 1 or port > 65535:
            raise ValueError("portInvalid")


class DataSourceRecord(BaseModel):
    """Persisted data-source record."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: DataSourceType
    name: str
    config: Dict[str, Any]
    created_at: str = Field(serialization_alias="createdAt")
    updated_at: str = Field(serialization_alias="updatedAt")

    @classmethod
    def new(
        cls,
        *,
        ds_type: DataSourceType,
        name: str,
        config: Dict[str, Any],
    ) -> "DataSourceRecord":
        now = _utc_now_iso()
        return cls(
            id=f"{ds_type}-{uuid4().hex[:12]}",
            type=ds_type,
            name=name.strip(),
            config=config,
            created_at=now,
            updated_at=now,
        )


class DataSourceCreateRequest(BaseModel):
    """Request body for creating a data source."""

    type: DataSourceType
    name: str
    config: Dict[str, Any]

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("nameRequired")
        return stripped


class DataSourceUpdateRequest(BaseModel):
    """Request body for updating a data source."""

    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("nameRequired")
        return stripped


class DataSourceTestRequest(BaseModel):
    """Request body for testing a connection without persisting."""

    type: DataSourceType
    config: Dict[str, Any]


class DataSourceTestResponse(BaseModel):
    """Result of a connection test."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool
    message: str
    latency_ms: Optional[int] = Field(default=None, serialization_alias="latencyMs")


class DataSourceListResponse(BaseModel):
    """List response wrapper."""

    items: list[DataSourceRecord]
