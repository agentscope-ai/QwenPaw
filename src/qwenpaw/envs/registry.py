# -*- coding: utf-8 -*-
"""Metadata and validation for environment settings exposed by Console."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Literal


_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

EnvMutability = Literal["hot_runtime", "startup_only"]
EnvReadonlyReason = Literal["startup", "initial_default"]
EnvValueType = Literal["string", "float", "integer", "boolean"]


@dataclass(frozen=True, slots=True)
class EnvVarSpec:
    """Describe ownership and runtime behavior of one known setting."""

    key: str
    default: str
    mutability: EnvMutability
    value_type: EnvValueType = "string"
    readonly_reason_code: EnvReadonlyReason | None = None

    @property
    def editable(self) -> bool:
        """Return whether Console may persist an override."""
        return self.mutability == "hot_runtime"


ENV_VAR_SPECS = (
    EnvVarSpec(
        "QWENPAW_LLM_STREAM_FIRST_CONTENT_TIMEOUT",
        "30",
        "hot_runtime",
        "float",
    ),
    EnvVarSpec(
        "QWENPAW_LLM_STREAM_IDLE_TIMEOUT",
        "30",
        "hot_runtime",
        "float",
    ),
    EnvVarSpec(
        "QWENPAW_LLM_MAX_RETRIES",
        "3",
        "startup_only",
        "integer",
        "initial_default",
    ),
    EnvVarSpec(
        "QWENPAW_LLM_BACKOFF_BASE",
        "1",
        "startup_only",
        "float",
        "initial_default",
    ),
    EnvVarSpec(
        "QWENPAW_LLM_BACKOFF_CAP",
        "10",
        "startup_only",
        "float",
        "initial_default",
    ),
    EnvVarSpec(
        "QWENPAW_LLM_MAX_CONCURRENT",
        "10",
        "startup_only",
        "integer",
        "initial_default",
    ),
    EnvVarSpec(
        "QWENPAW_LLM_MAX_QPM",
        "600",
        "startup_only",
        "integer",
        "initial_default",
    ),
    EnvVarSpec(
        "QWENPAW_LLM_RATE_LIMIT_PAUSE",
        "5",
        "startup_only",
        "float",
        "initial_default",
    ),
    EnvVarSpec(
        "QWENPAW_LLM_RATE_LIMIT_JITTER",
        "1",
        "startup_only",
        "float",
        "initial_default",
    ),
    EnvVarSpec(
        "QWENPAW_LLM_ACQUIRE_TIMEOUT",
        "300",
        "startup_only",
        "float",
        "initial_default",
    ),
    EnvVarSpec(
        "QWENPAW_WORKING_DIR",
        "~/.qwenpaw",
        "startup_only",
        readonly_reason_code="startup",
    ),
    EnvVarSpec(
        "QWENPAW_SECRET_DIR",
        "~/.qwenpaw.secret",
        "startup_only",
        readonly_reason_code="startup",
    ),
    EnvVarSpec(
        "QWENPAW_CONFIG_FILE",
        "config.json",
        "startup_only",
        readonly_reason_code="startup",
    ),
    EnvVarSpec(
        "QWENPAW_JOBS_FILE",
        "jobs.json",
        "startup_only",
        readonly_reason_code="startup",
    ),
    EnvVarSpec(
        "QWENPAW_CHATS_FILE",
        "chats.json",
        "startup_only",
        readonly_reason_code="startup",
    ),
    EnvVarSpec(
        "QWENPAW_OPENAPI_DOCS",
        "false",
        "startup_only",
        "boolean",
        "startup",
    ),
    EnvVarSpec(
        "QWENPAW_RUNNING_IN_CONTAINER",
        "false",
        "startup_only",
        "boolean",
        "startup",
    ),
)

ENV_VAR_SPECS_BY_KEY = {spec.key: spec for spec in ENV_VAR_SPECS}

_INTERNAL_KEYS = frozenset(
    {
        "QWENPAW_RUNTIME_INTERNAL_TOKEN",
        "QWENPAW_RUNTIME_READY_FILE",
    },
)
_PROTECTED_BOOTSTRAP_KEYS = frozenset(
    {
        "QWENPAW_WORKING_DIR",
        "QWENPAW_SECRET_DIR",
        *_INTERNAL_KEYS,
    },
)


def env_key_identity(key: str) -> str:
    """Return the portable, case-insensitive identity for an env key."""
    return key.upper()


def is_internal_env_key(key: str) -> bool:
    """Return whether an env key is reserved for internal runtime use."""
    return env_key_identity(key) in _INTERNAL_KEYS


def is_bootstrap_protected_env_key(key: str) -> bool:
    """Return whether persisted data must not override a startup value."""
    return env_key_identity(key) in _PROTECTED_BOOTSTRAP_KEYS


def validate_unique_env_keys(keys: Iterable[str]) -> None:
    """Reject keys that differ only by letter case."""
    seen: dict[str, str] = {}
    for key in keys:
        identity = env_key_identity(key)
        existing = seen.get(identity)
        if existing is not None and existing != key:
            raise ValueError(
                f"Environment variable names conflict: {existing}, {key}",
            )
        seen[identity] = key


def validate_env_key(key: str) -> None:
    """Reject malformed, internal, and non-editable known keys."""
    if not _ENV_KEY_RE.fullmatch(key):
        raise ValueError(f"Invalid environment variable name: {key}")
    identity = env_key_identity(key)
    if identity.startswith("QWENPAW_") and key != identity:
        raise ValueError(
            f"QwenPaw environment variable must be uppercase: {key}",
        )
    if is_internal_env_key(key):
        raise ValueError(f"Environment variable is managed internally: {key}")
    spec = ENV_VAR_SPECS_BY_KEY.get(identity)
    if spec is not None and not spec.editable:
        raise ValueError(f"Environment variable is read-only: {key}")


def validate_env_value(key: str, value: str) -> None:
    """Validate the value of a known editable setting."""
    if not isinstance(value, str):
        raise ValueError(f"Environment variable value must be text: {key}")
    spec = ENV_VAR_SPECS_BY_KEY.get(key)
    if spec is None or spec.value_type == "string":
        return
    try:
        if spec.value_type == "float":
            parsed = float(value)
            if parsed < 0 or not math.isfinite(parsed):
                raise ValueError
        elif spec.value_type == "integer":
            int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {spec.value_type} value for {key}") from exc
