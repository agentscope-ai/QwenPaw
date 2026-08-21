# -*- coding: utf-8 -*-
"""Strict startup configuration for QwenPaw Hub."""

from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .database import (
    connect_hub_database,
    initialize_hub_database,
    utc_now,
)

_DOCKER_IMAGE_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,511}$",
)
_DOCKER_SOURCE_REPOSITORIES = {
    "docker_hub": "docker.io/agentscope/qwenpaw",
    "aliyun_acr": (
        "agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/"
        "qwenpaw"
    ),
}


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


class RateLimitConfig(BaseModel):
    """One fixed-window abuse protection policy."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_attempts: int = Field(default=10, ge=1, le=10000)
    window_seconds: int = Field(default=300, ge=1, le=86400)
    block_seconds: int = Field(default=900, ge=1, le=604800)


class AccessSecurityConfig(BaseModel):
    """Network-level protection for public authentication endpoints."""

    model_config = ConfigDict(extra="forbid")

    ip_blacklist: list[str] = Field(default_factory=list)
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    login_rate_limit: RateLimitConfig = Field(
        default_factory=RateLimitConfig,
    )
    registration_rate_limit: RateLimitConfig = Field(
        default_factory=lambda: RateLimitConfig(
            max_attempts=5,
            window_seconds=3600,
            block_seconds=3600,
        ),
    )

    @field_validator("ip_blacklist", "trusted_proxy_ips")
    @classmethod
    def validate_networks(cls, values: list[str]) -> list[str]:
        """Normalize unique IPv4 and IPv6 addresses or CIDR networks."""
        normalized: list[str] = []
        for value in values:
            try:
                network = ipaddress.ip_network(value.strip(), strict=False)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid IP address or CIDR: {value}",
                ) from exc
            text = str(network)
            if text not in normalized:
                normalized.append(text)
        return normalized


class RuntimeProxyConfig(BaseModel):
    """Bound resources used while proxying personal runtime traffic."""

    model_config = ConfigDict(extra="forbid")

    max_request_size_mb: int = Field(default=1024, ge=1, le=102400)
    request_idle_timeout_seconds: float = Field(
        default=60,
        gt=0,
        le=3600,
    )
    response_header_timeout_seconds: float = Field(
        default=300,
        gt=0,
        le=3600,
    )
    connect_timeout_seconds: float = Field(default=10, gt=0, le=300)
    websocket_max_message_size_mb: int = Field(
        default=16,
        ge=1,
        le=1024,
    )

    @property
    def max_request_size_bytes(self) -> int:
        """Return the configured request limit in bytes."""
        return self.max_request_size_mb * 1024 * 1024

    @property
    def websocket_max_message_size_bytes(self) -> int:
        """Return the configured WebSocket message limit in bytes."""
        return self.websocket_max_message_size_mb * 1024 * 1024


class ControlPlaneConfig(BaseModel):
    """Configuration-managed control-plane settings."""

    model_config = ConfigDict(extra="forbid")

    public_base_url: str | None = None
    registration: RegistrationConfig = Field(
        default_factory=RegistrationConfig,
    )
    security: AccessSecurityConfig = Field(
        default_factory=AccessSecurityConfig,
    )
    proxy: RuntimeProxyConfig = Field(default_factory=RuntimeProxyConfig)

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str | None) -> str | None:
        """Validate and normalize the browser-reachable control URL."""
        if value is None:
            return None
        stripped = value.strip()
        parsed = urlsplit(stripped)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(
                "public_base_url must be an absolute HTTP(S) URL",
            )
        if parsed.username or parsed.password:
            raise ValueError("public_base_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError(
                "public_base_url must not contain query or fragment",
            )
        normalized_path = parsed.path.rstrip("/")
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                normalized_path,
                "",
                "",
            ),
        )


class DockerRuntimeConfig(BaseModel):
    """Docker runtime defaults and host resource limits."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["docker_hub", "aliyun_acr", "custom"] = "docker_hub"
    image: str = "docker.io/agentscope/qwenpaw:latest"
    pull_policy: Literal[
        "always",
        "if_not_present",
        "never",
    ] = "if_not_present"
    cpu_limit: float | None = Field(default=2.0, gt=0, le=128)
    memory_limit_mb: int | None = Field(default=4096, ge=256)
    pids_limit: int | None = Field(default=1024, ge=64)
    shm_size_mb: int = Field(default=512, ge=64)

    @field_validator("image")
    @classmethod
    def validate_default_image(cls, value: str) -> str:
        """Reject empty or whitespace-padded image references."""
        if value != value.strip() or not _DOCKER_IMAGE_PATTERN.fullmatch(
            value,
        ):
            raise ValueError("image must be a valid Docker image reference")
        return value

    @model_validator(mode="after")
    def validate_source_and_image(self) -> DockerRuntimeConfig:
        """Keep official sources aligned with their image repository."""
        repository = _DOCKER_SOURCE_REPOSITORIES.get(self.source)
        if repository and not (
            self.image.startswith(f"{repository}:")
            or self.image.startswith(f"{repository}@")
        ):
            raise ValueError(
                f"image does not match configured source: {self.source}",
            )
        return self


class RuntimeConfig(BaseModel):
    """Deployment-neutral runtime provisioner selection."""

    model_config = ConfigDict(extra="forbid")

    provisioner: Literal["local", "docker"] = "local"
    docker: DockerRuntimeConfig = Field(default_factory=DockerRuntimeConfig)


class RuntimeCapacityConfig(BaseModel):
    """Global admission limit for concurrently active runtimes."""

    model_config = ConfigDict(extra="forbid")

    max_running_runtimes: int | None = Field(default=None, ge=0)


class HubConfig(BaseModel):
    """Versioned QwenPaw Hub configuration with strict fields."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    control_plane: ControlPlaneConfig = Field(
        default_factory=ControlPlaneConfig,
    )
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    capacity: RuntimeCapacityConfig = Field(
        default_factory=RuntimeCapacityConfig,
    )

    @property
    def default_provisioner(self) -> str:
        """Return the administrator-selected runtime provisioner."""
        return self.runtime.provisioner


class HubConfigStore:
    """Persist Hub settings with an optional startup YAML authority."""

    _CONFIG_KEY = "hub_config"

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        initialize_hub_database(database_path)

    def _connect(self) -> sqlite3.Connection:
        return connect_hub_database(self.database_path)

    def resolve(
        self,
        path: Path | None,
        available_provisioners: set[str] | None = None,
    ) -> HubConfig:
        """Apply explicit YAML or return the database-owned settings."""
        overlay = load_hub_config(path) if path is not None else None
        if overlay is not None and available_provisioners is not None:
            _validate_provisioners(overlay, available_provisioners)
        with self._connect() as connection:
            persisted = self._load_persisted(connection)
            if overlay is not None:
                if persisted is None:
                    self._insert_config(connection, overlay)
                else:
                    self._replace_config(connection, overlay)
                self._sync_registration(connection, overlay)
                return self._with_registration(connection, overlay)
            if persisted is not None:
                effective = self._with_registration(
                    connection,
                    HubConfig.model_validate(persisted),
                )
                if available_provisioners is not None:
                    _validate_provisioners(
                        effective,
                        available_provisioners,
                    )
                return effective
            effective = HubConfig()
            if available_provisioners is not None:
                _validate_provisioners(effective, available_provisioners)
            self._insert_config(connection, effective)
            self._sync_registration(connection, effective)
            return self._with_registration(connection, effective)

    def _replace_config(
        self,
        connection: sqlite3.Connection,
        config: HubConfig,
    ) -> None:
        """Replace persisted settings from an explicit startup YAML."""
        connection.execute(
            "UPDATE hub_settings SET value_json = ?, "
            "schema_version = 1, revision = revision + 1, "
            "updated_by_user_id = NULL, updated_at = ? WHERE key = ?",
            (
                config.model_dump_json(exclude_none=True),
                utc_now(),
                self._CONFIG_KEY,
            ),
        )

    def snapshot(self) -> tuple[HubConfig, int, str]:
        """Return the effective configuration and concurrency metadata."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json, revision, updated_at FROM hub_settings "
                "WHERE key = ?",
                (self._CONFIG_KEY,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Hub configuration is not initialized")
            config = self._with_registration(
                connection,
                HubConfig.model_validate_json(str(row["value_json"])),
            )
        return config, int(row["revision"]), str(row["updated_at"])

    def ensure(
        self,
        config: HubConfig,
        *,
        available_provisioners: set[str],
    ) -> HubConfig:
        """Initialize missing settings without replacing persisted values."""
        _validate_provisioners(config, available_provisioners)
        with self._connect() as connection:
            persisted = self._load_persisted(connection)
            if persisted is None:
                self._insert_config(connection, config)
                self._sync_registration(connection, config)
                return self._with_registration(connection, config)
            effective = self._with_registration(
                connection,
                HubConfig.model_validate(persisted),
            )
        _validate_provisioners(effective, available_provisioners)
        return effective

    def update(
        self,
        config: HubConfig,
        *,
        expected_revision: int,
        available_provisioners: set[str],
        updated_by_user_id: str,
    ) -> tuple[HubConfig, int, str]:
        """Persist one validated configuration with optimistic locking."""
        _validate_provisioners(config, available_provisioners)
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE hub_settings SET value_json = ?, "
                "revision = revision + 1, updated_by_user_id = ?, "
                "updated_at = ? WHERE key = ? AND revision = ?",
                (
                    config.model_dump_json(exclude_none=True),
                    updated_by_user_id,
                    now,
                    self._CONFIG_KEY,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Hub configuration changed concurrently")
            self._sync_registration(connection, config)
            effective = self._with_registration(connection, config)
        return effective, expected_revision + 1, now

    def _load_persisted(
        self,
        connection: sqlite3.Connection,
    ) -> dict[str, object] | None:
        row = connection.execute(
            "SELECT value_json FROM hub_settings WHERE key = ?",
            (self._CONFIG_KEY,),
        ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(str(row["value_json"]))
        except json.JSONDecodeError as exc:
            raise ValueError("Persisted Hub config is invalid") from exc
        if not isinstance(value, dict):
            raise ValueError("Persisted Hub config must be an object")
        return value

    def _insert_config(
        self,
        connection: sqlite3.Connection,
        config: HubConfig,
    ) -> None:
        connection.execute(
            "INSERT INTO hub_settings("
            "key, value_json, schema_version, revision, updated_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (
                self._CONFIG_KEY,
                config.model_dump_json(exclude_none=True),
                utc_now(),
            ),
        )

    def _sync_registration(
        self,
        connection: sqlite3.Connection,
        config: HubConfig,
    ) -> None:
        registration = config.control_plane.registration
        if registration.enabled is not None:
            self._write_setting(
                connection,
                "registration_enabled",
                registration.enabled,
            )
        if registration.default_role is not None:
            self._write_setting(
                connection,
                "registration_default_role",
                registration.default_role,
            )

    @staticmethod
    def _with_registration(
        connection: sqlite3.Connection,
        config: HubConfig,
    ) -> HubConfig:
        registration = config.control_plane.registration
        values: dict[str, object] = {}
        for field_name, key in (
            ("enabled", "registration_enabled"),
            ("default_role", "registration_default_role"),
        ):
            row = connection.execute(
                "SELECT value_json FROM hub_settings WHERE key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                values[field_name] = json.loads(str(row["value_json"]))
        if not values:
            return config
        return config.model_copy(
            update={
                "control_plane": config.control_plane.model_copy(
                    update={
                        "registration": registration.model_copy(
                            update=values,
                        ),
                    },
                ),
            },
        )

    @staticmethod
    def _write_setting(
        connection: sqlite3.Connection,
        key: str,
        value: object,
    ) -> None:
        connection.execute(
            "INSERT INTO hub_settings("
            "key, value_json, schema_version, revision, updated_at) "
            "VALUES (?, ?, 1, 1, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value_json = excluded.value_json, "
            "revision = hub_settings.revision + 1, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value), utc_now()),
        )


def load_hub_config(path: Path | None) -> HubConfig:
    """Load one strict YAML file or return built-in defaults."""
    if path is None:
        return HubConfig()
    resolved = path.expanduser().resolve()
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(
            f"Unable to load Hub config {resolved}: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"Hub config must contain a YAML mapping: {resolved}",
        )
    if "version" not in raw:
        raise ValueError(f"Hub config is missing version: {resolved}")
    try:
        config = HubConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid Hub config {resolved}: {exc}") from exc
    return config


def _validate_provisioners(
    config: HubConfig,
    available_provisioners: set[str],
) -> None:
    """Reject unavailable or internally inconsistent provisioner policy."""
    if config.runtime.provisioner not in available_provisioners:
        raise ValueError(
            "Unknown runtime provisioner: " f"{config.runtime.provisioner}",
        )
