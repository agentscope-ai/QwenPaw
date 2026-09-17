# -*- coding: utf-8 -*-
"""API endpoints for environment variable management."""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ...access.dependencies import (
    get_actor,  # noqa: F401 -- exposed for dependency overrides in tests
    require_platform_settings_manage,
)
from ...envs import load_envs, save_envs

router = APIRouter(
    prefix="/envs",
    tags=["envs"],
    dependencies=[Depends(require_platform_settings_manage)],
)


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class EnvVar(BaseModel):
    """不包含明文的环境变量状态。"""

    key: str = Field(..., description="Variable name")
    configured: bool = Field(..., description="Whether a value is configured")


class EnvOperation(BaseModel):
    """对单个环境变量执行的显式操作。"""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., description="Variable name")
    action: Literal["keep", "replace", "delete"]
    value: str | None = Field(default=None, description="New write-only value")


class EnvUpdateRequest(BaseModel):
    """环境变量增量更新。未提及的键保持不变。"""

    model_config = ConfigDict(extra="forbid")

    operations: list[EnvOperation]


def _status(envs: dict[str, str]) -> list[EnvVar]:
    return [EnvVar(key=key, configured=True) for key in sorted(envs)]


def _validate_operations(operations: list[EnvOperation]) -> None:
    seen: set[str] = set()
    for operation in operations:
        key = operation.key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid environment variable key",
            )
        if key in seen:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate operation for '{key}'",
            )
        seen.add(key)
        if operation.action == "replace" and operation.value is None:
            raise HTTPException(status_code=400, detail="Replace requires a value")
        if operation.action != "replace" and operation.value is not None:
            raise HTTPException(
                status_code=400,
                detail=f"{operation.action.title()} does not accept a value",
            )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get(
    "",
    response_model=list[EnvVar],
    summary="List all environment variables",
)
async def list_envs() -> list[EnvVar]:
    """仅返回键名和配置状态，已保存的值始终不可回读。"""
    return _status(load_envs())


@router.put(
    "",
    response_model=list[EnvVar],
    summary="Batch save environment variables",
    description=(
        "Apply explicit keep, replace or delete operations. "
        "Unmentioned keys remain unchanged."
    ),
)
async def batch_save_envs(
    body: EnvUpdateRequest,
) -> list[EnvVar]:
    """增量更新环境变量，不把任何明文写入响应。"""
    _validate_operations(body.operations)
    updated = load_envs()
    for operation in body.operations:
        key = operation.key.strip()
        if operation.action == "keep":
            continue
        if operation.action == "delete":
            updated.pop(key, None)
            continue
        assert operation.value is not None
        updated[key] = operation.value
    if body.operations:
        save_envs(updated)
    return _status(updated)


@router.delete(
    "/{key}",
    response_model=list[EnvVar],
    summary="Delete an environment variable",
)
async def delete_env(key: str) -> list[EnvVar]:
    """Delete a single env var."""
    envs = load_envs()
    if key not in envs:
        raise HTTPException(
            404,
            detail=f"Env var '{key}' not found",
        )
    envs.pop(key)
    save_envs(envs)
    return _status(envs)
