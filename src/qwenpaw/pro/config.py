# -*- coding: utf-8 -*-
"""Strict startup configuration for QwenPaw Pro."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class RegistrationConfig(BaseModel):
    """Configuration-managed account registration policy."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    default_role: Literal["user"] | None = None

    @model_validator(mode="after")
    def validate_explicit_values(self) -> RegistrationConfig:
        """Reject null for settings that cannot be cleared in SQLite."""
        for field_name in ("enabled", "default_role"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} must not be null")
        return self


class ControlPlaneConfig(BaseModel):
    """Configuration-managed control-plane settings."""

    model_config = ConfigDict(extra="forbid")

    registration: RegistrationConfig = Field(
        default_factory=RegistrationConfig,
    )


class RuntimeConfig(BaseModel):
    """Deployment-neutral runtime driver selection."""

    model_config = ConfigDict(extra="forbid")

    default_driver: str | None = None
    allowed_drivers: list[str] | None = None

    @field_validator("allowed_drivers")
    @classmethod
    def validate_allowed_drivers(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        """Reject empty or duplicate allowlists."""
        if value is None:
            return value
        if not value:
            raise ValueError("allowed_drivers must not be empty")
        if any(not item.strip() for item in value):
            raise ValueError("allowed_drivers must contain driver names")
        if len(set(value)) != len(value):
            raise ValueError("allowed_drivers must not contain duplicates")
        return value


class TenantQuota(BaseModel):
    """Runtime admission limits enforced for one tenant."""

    model_config = ConfigDict(extra="forbid")

    max_runtimes: int | None = Field(default=None, ge=0)
    max_running_runtimes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_running_limit(self) -> TenantQuota:
        """Ensure the running subset cannot exceed total runtimes."""
        if (
            self.max_runtimes is not None
            and self.max_running_runtimes is not None
            and self.max_running_runtimes > self.max_runtimes
        ):
            raise ValueError(
                "max_running_runtimes must not exceed max_runtimes",
            )
        return self

    def merge(self, override: TenantQuota | None) -> TenantQuota:
        """Apply field-level tenant values over global defaults."""
        if override is None:
            return self
        return TenantQuota(
            max_runtimes=(
                override.max_runtimes
                if override.max_runtimes is not None
                else self.max_runtimes
            ),
            max_running_runtimes=(
                override.max_running_runtimes
                if override.max_running_runtimes is not None
                else self.max_running_runtimes
            ),
        )


class ProConfig(BaseModel):
    """Versioned QwenPaw Pro configuration with strict fields."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    control_plane: ControlPlaneConfig = Field(
        default_factory=ControlPlaneConfig,
    )
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    tenant_defaults: TenantQuota = Field(default_factory=TenantQuota)
    tenants: dict[str, TenantQuota] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tenant_overrides(self) -> ProConfig:
        """Validate every merged quota before the server starts."""
        for tenant_id in self.tenants:
            self.quota_for(tenant_id)
        return self

    @property
    def default_driver(self) -> str:
        """Return the configured driver or the built-in local default."""
        return self.runtime.default_driver or "local"

    @property
    def allowed_drivers(self) -> frozenset[str] | None:
        """Return the optional configured driver allowlist."""
        if self.runtime.allowed_drivers is None:
            return None
        return frozenset(self.runtime.allowed_drivers)

    def quota_for(self, tenant_id: str) -> TenantQuota:
        """Resolve field-level tenant quota overrides."""
        return self.tenant_defaults.merge(self.tenants.get(tenant_id))


class ProConfigStore:
    """Merge startup YAML into persistent control-plane settings."""

    _CONFIG_KEY = "pro_config"

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS pro_settings ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def resolve(
        self,
        path: Path | None,
        available_drivers: set[str] | None = None,
    ) -> ProConfig:
        """Apply explicit YAML fields and return persisted effective values."""
        overlay = load_pro_config(path) if path is not None else None
        with self._connect() as connection:
            persisted = self._load_persisted(connection)
            if overlay is None:
                return ProConfig.model_validate(persisted)
            explicit = overlay.model_dump(exclude_unset=True)
            merged = _deep_merge(persisted, explicit)
            effective = ProConfig.model_validate(merged)
            if available_drivers is not None:
                _validate_drivers(effective, available_drivers)
            connection.execute(
                "INSERT OR REPLACE INTO pro_settings(key, value) "
                "VALUES (?, ?)",
                (
                    self._CONFIG_KEY,
                    effective.model_dump_json(exclude_none=True),
                ),
            )
            registration = explicit.get("control_plane", {}).get(
                "registration",
                {},
            )
            if "enabled" in registration:
                self._write_setting(
                    connection,
                    "registration_enabled",
                    "true" if registration["enabled"] else "false",
                )
            if "default_role" in registration:
                self._write_setting(
                    connection,
                    "registration_default_role",
                    str(registration["default_role"]),
                )
            return effective

    def _load_persisted(
        self,
        connection: sqlite3.Connection,
    ) -> dict[str, object]:
        row = connection.execute(
            "SELECT value FROM pro_settings WHERE key = ?",
            (self._CONFIG_KEY,),
        ).fetchone()
        if row is None:
            return {"version": 1}
        try:
            value = json.loads(str(row["value"]))
        except json.JSONDecodeError as exc:
            raise ValueError("Persisted Pro config is invalid") from exc
        if not isinstance(value, dict):
            raise ValueError("Persisted Pro config must be an object")
        return value

    @staticmethod
    def _write_setting(
        connection: sqlite3.Connection,
        key: str,
        value: str,
    ) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO pro_settings(key, value) VALUES (?, ?)",
            (key, value),
        )


def load_pro_config(path: Path | None) -> ProConfig:
    """Load one strict YAML file or return built-in defaults."""
    if path is None:
        return ProConfig()
    resolved = path.expanduser().resolve()
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(
            f"Unable to load Pro config {resolved}: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"Pro config must contain a YAML mapping: {resolved}",
        )
    if "version" not in raw:
        raise ValueError(f"Pro config is missing version: {resolved}")
    try:
        config = ProConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid Pro config {resolved}: {exc}") from exc
    return config


def _deep_merge(
    base: dict[str, object],
    override: dict[str, object],
) -> dict[str, object]:
    """Merge mappings recursively while replacing scalar and list values."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _validate_drivers(
    config: ProConfig,
    available_drivers: set[str],
) -> None:
    """Reject unavailable or internally inconsistent driver policy."""
    if config.default_driver not in available_drivers:
        raise ValueError(
            f"Unknown default runtime driver: {config.default_driver}",
        )
    allowed = config.allowed_drivers
    if allowed is None:
        return
    unknown = sorted(allowed - available_drivers)
    if unknown:
        raise ValueError(
            f"Unknown allowed runtime drivers: {', '.join(unknown)}",
        )
    if config.default_driver not in allowed:
        raise ValueError(
            "default_driver must be included in allowed_drivers",
        )
