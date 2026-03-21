# -*- coding: utf-8 -*-
"""API endpoints for environment variable management."""
from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...envs import load_envs, save_envs, delete_env_var

router = APIRouter(prefix="/envs", tags=["envs"])


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class EnvVar(BaseModel):
    """Single environment variable."""

    key: str = Field(..., description="Variable name")
    value: str = Field(..., description="Variable value")


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get(
    "",
    response_model=List[EnvVar],
    summary="List all environment variables",
)
async def list_envs() -> List[EnvVar]:
    """Return all configured env vars."""
    envs = load_envs()
    return [EnvVar(key=k, value=v) for k, v in sorted(envs.items())]


@router.put(
    "",
    response_model=List[EnvVar],
    summary="Batch save environment variables",
    description="Replace all environment variables with "
    "the provided dict. Keys not present are removed.",
)
async def batch_save_envs(
    body: Dict[str, str],
) -> List[EnvVar]:
    """Batch save – full replacement of all env vars."""
    # Validate keys
    for key in body:
        if not key.strip():
            raise HTTPException(
                400,
                detail="Key cannot be empty",
            )
    cleaned = {k.strip(): v for k, v in body.items()}
    save_envs(cleaned)
    return [EnvVar(key=k, value=v) for k, v in sorted(cleaned.items())]


@router.delete(
    "/{key}",
    response_model=List[EnvVar],
    summary="Delete an environment variable",
)
async def delete_env(key: str) -> List[EnvVar]:
    """Delete a single env var."""
    envs = load_envs()
    if key not in envs:
        raise HTTPException(
            404,
            detail=f"Env var '{key}' not found",
        )
    envs = delete_env_var(key)
    return [EnvVar(key=k, value=v) for k, v in sorted(envs.items())]
