# -*- coding: utf-8 -*-
"""Global UI settings (language, theme, etc.).

Persisted in ``WORKING_DIR/settings.json``, independent of
per-agent configuration.  All endpoints are public (no auth required).
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from ...agents.skill_system.registry import (
    set_builtin_skill_language_preference,
)
from ...constant import UPLOAD_MAX_SIZE_MB, WORKING_DIR
from ...utils.io_utils import (
    get_path_lock,
    path_exists_async,
    read_json_async,
    write_json_atomic_async,
)

router = APIRouter(prefix="/settings", tags=["settings"])

_SETTINGS_FILE = WORKING_DIR / "settings.json"

_VALID_LANGUAGES = {"en", "zh", "ja", "ru", "pt-BR", "id"}


async def _load() -> dict:
    if not await path_exists_async(_SETTINGS_FILE):
        return {}
    try:
        data = await read_json_async(_SETTINGS_FILE)
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


async def _save(data: dict) -> None:
    await write_json_atomic_async(
        _SETTINGS_FILE,
        data,
        indent=2,
        new_file_mode=0o644,
    )


@router.get("/language", summary="Get UI language")
async def get_language() -> dict:
    async with get_path_lock(_SETTINGS_FILE):
        settings = await _load()
    return {"language": settings.get("language", "en")}


@router.put("/language", summary="Update UI language")
async def put_language(
    body: dict = Body(..., description='e.g. {"language": "zh"}'),
) -> dict:
    language = body.get("language", "").strip()
    if language not in _VALID_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid language, must be one of "
            f"{sorted(_VALID_LANGUAGES)}",
        )
    async with get_path_lock(_SETTINGS_FILE):
        data = await _load()
        data["language"] = language
        await _save(data)
    # Update cached builtin preference since it falls back to UI language.
    if not data.get("builtin_skill_language"):
        set_builtin_skill_language_preference(
            "zh" if language.startswith("zh") else "en",
        )
    return {"language": language}


@router.get("/upload-limit", summary="Get upload size limit")
async def get_upload_limit() -> dict:
    """Return the configured upload size limit (MB), or null if unlimited."""
    return {"upload_max_size_mb": UPLOAD_MAX_SIZE_MB}


# ─── Offload policy ───


class OffloadPolicyRequest(BaseModel):
    default_action: str = Field(
        default="keep_foreground",
        pattern="^(keep_foreground|offload)$",
    )


@router.get("/offload-policy", summary="Get offload default policy")
async def get_offload_policy() -> dict[str, str]:
    async with get_path_lock(_SETTINGS_FILE):
        settings = await _load()
    return {
        "default_action": settings.get(
            "offload_policy",
            "keep_foreground",
        ),
    }


@router.put("/offload-policy", summary="Update offload default policy")
async def set_offload_policy(
    body: OffloadPolicyRequest,
    request: Request,
) -> dict[str, str]:
    async with get_path_lock(_SETTINGS_FILE):
        settings = await _load()
        settings["offload_policy"] = body.default_action
        await _save(settings)

    app_services = getattr(request.app.state, "app_services", None)
    if app_services:
        coordinator = getattr(app_services, "tool_coordinator", None)
        if coordinator:
            coordinator.offload_on_deadline = body.default_action == "offload"

    return {"default_action": body.default_action}
