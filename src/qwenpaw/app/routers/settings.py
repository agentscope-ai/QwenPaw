# -*- coding: utf-8 -*-
"""Global UI settings (language, theme, etc.).

Persisted in ``WORKING_DIR/settings.json``, independent of
per-agent configuration.  All endpoints are public (no auth required).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException

from ...agents.skills_manager import set_builtin_skill_language_preference
from ...constant import WORKING_DIR

router = APIRouter(prefix="/settings", tags=["settings"])

_SETTINGS_FILE = WORKING_DIR / "settings.json"

_VALID_LANGUAGES = {"en", "zh", "ja", "ru"}


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
