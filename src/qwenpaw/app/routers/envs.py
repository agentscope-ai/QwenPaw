# -*- coding: utf-8 -*-
"""API endpoints for environment variable management."""
from __future__ import annotations

import os
from typing import Dict, List, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...envs import delete_env_var, load_envs, save_envs, update_env_vars
from ...envs.registry import (
    ENV_VAR_SPECS,
    ENV_VAR_SPECS_BY_KEY,
    EnvReadonlyReason,
    validate_env_key,
    validate_env_value,
    validate_unique_env_keys,
)

router = APIRouter(prefix="/envs", tags=["envs"])


class EnvVar(BaseModel):
    """Single persisted environment variable."""

    key: str = Field(..., description="Variable name")
    value: str = Field(..., description="Variable value")


class EnvSpecResponse(BaseModel):
    """Known environment setting and its ownership metadata."""

    key: str
    default: str
    effective_value: str
    source: Literal["default", "system", "user"]
    description_key: str
    editable: bool
    value_type: Literal["string", "float", "integer", "boolean"]
    readonly_reason_code: EnvReadonlyReason | None
    mutability: Literal["hot_runtime", "startup_only"]
    configured: bool


def _items(envs: dict[str, str]) -> List[EnvVar]:
    return [
        EnvVar(key=key, value=value) for key, value in sorted(envs.items())
    ]


def _validate_updates(body: Dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for raw_key, value in body.items():
        key = raw_key.strip()
        try:
            validate_env_key(key)
            validate_env_value(key, value)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        if key in cleaned:
            raise HTTPException(
                400,
                detail=f"Environment variable names conflict: {key}",
            )
        cleaned[key] = value
    try:
        validate_unique_env_keys(cleaned)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    return cleaned


@router.get("", response_model=List[EnvVar])
def list_envs() -> List[EnvVar]:
    """Return values explicitly configured through QwenPaw."""
    return _items(load_envs())


@router.get("/catalog", response_model=List[EnvSpecResponse])
def list_env_catalog() -> List[EnvSpecResponse]:
    """Return dynamic, initialization-default, and startup settings."""
    configured = load_envs()
    result = []
    for spec in ENV_VAR_SPECS:
        if spec.key in configured:
            value = configured[spec.key]
            source = "user"
        elif spec.key in os.environ:
            value = os.environ[spec.key]
            source = "system"
        else:
            value = spec.default
            source = "default"
        result.append(
            EnvSpecResponse(
                key=spec.key,
                default=spec.default,
                effective_value=value,
                source=source,
                description_key=(
                    f"environments.variableDescriptions.{spec.key}"
                ),
                editable=spec.editable,
                value_type=spec.value_type,
                readonly_reason_code=spec.readonly_reason_code,
                mutability=spec.mutability,
                configured=spec.key in configured,
            ),
        )
    return result


@router.patch("", response_model=List[EnvVar])
def patch_envs(body: Dict[str, str]) -> List[EnvVar]:
    """Merge submitted values without deleting omitted variables."""
    try:
        return _items(update_env_vars(_validate_updates(body)))
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.put("", response_model=List[EnvVar])
def batch_save_envs(body: Dict[str, str]) -> List[EnvVar]:
    """Replace all persisted values through the legacy batch endpoint."""
    cleaned = _validate_updates(body)
    try:
        save_envs(cleaned)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    return _items(cleaned)


@router.post("/{key}/reset", response_model=List[EnvVar])
def reset_env(key: str) -> List[EnvVar]:
    """Remove a known global override and restore its inherited value."""
    spec = ENV_VAR_SPECS_BY_KEY.get(key)
    if spec is None:
        raise HTTPException(400, detail=f"Variable cannot be reset: {key}")
    envs = load_envs()
    if key not in envs:
        return _items(envs)
    return _items(delete_env_var(key))


@router.delete("/{key}", response_model=List[EnvVar])
def delete_env(key: str) -> List[EnvVar]:
    """Delete one custom variable."""
    if key in ENV_VAR_SPECS_BY_KEY:
        raise HTTPException(400, detail=f"Known variable must be reset: {key}")
    envs = load_envs()
    if key not in envs:
        raise HTTPException(404, detail=f"Env var '{key}' not found")
    return _items(delete_env_var(key))
