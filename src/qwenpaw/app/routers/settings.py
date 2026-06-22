# -*- coding: utf-8 -*-
"""Global UI settings (language, theme, etc.).

Persisted in ``WORKING_DIR/settings.json``, independent of
per-agent configuration.  All endpoints are public (no auth required).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException

from ...agents.skill_system.registry import (
    set_builtin_skill_language_preference,
)
from ...constant import UPLOAD_MAX_SIZE_MB, WORKING_DIR

router = APIRouter(prefix="/settings", tags=["settings"])

_SETTINGS_FILE = WORKING_DIR / "settings.json"

_VALID_LANGUAGES = {"en", "zh", "ja", "ru", "pt-BR", "id"}


def _load() -> dict:
    if _SETTINGS_FILE.is_file():
        try:
            return json.loads(_SETTINGS_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        "utf-8",
    )


@router.get("/language", summary="Get UI language")
async def get_language() -> dict:
    return {"language": _load().get("language", "en")}


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
    data = _load()
    data["language"] = language
    _save(data)
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


@router.get("/close-behavior", summary="Get window close behavior")
async def get_close_behavior() -> dict:
    import sys

    # Default to minimize on macOS, quit on Windows/Linux
    default_behavior = "minimize" if sys.platform == "darwin" else "quit"
    return {"close_behavior": _load().get("close_behavior", default_behavior)}


@router.put("/close-behavior", summary="Update window close behavior")
async def put_close_behavior(
    body: dict = Body(..., description='e.g. {"close_behavior": "minimize"}'),
) -> dict:
    behavior = body.get("close_behavior", "").strip()
    if behavior not in {"minimize", "quit"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid close_behavior, must be 'minimize' or 'quit'",
        )
    data = _load()
    data["close_behavior"] = behavior
    _save(data)
    return {"close_behavior": behavior}
