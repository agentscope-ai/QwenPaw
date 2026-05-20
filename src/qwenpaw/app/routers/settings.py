# -*- coding: utf-8 -*-
"""Global UI settings (language, theme, etc.).

Persisted in ``WORKING_DIR/settings.json``, independent of
per-agent configuration.  All endpoints are public (no auth required).
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException

from ...agents.skill_system.registry import (
    set_builtin_skill_language_preference,
)
from ...constant import PUBLIC_URL as _ENV_PUBLIC_URL, WORKING_DIR

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Public URL helper — used by OAuth redirect_uri logic in mcp.py
# ---------------------------------------------------------------------------


def _derive_url_from_startup_params() -> str:
    """Build a base URL from the ``--host`` / ``--port`` startup parameters."""
    try:
        from ...config.utils import read_last_api

        result = read_last_api()
        if result:
            host, port = result
            return f"http://{host}:{port}"
    except Exception:
        logger.debug("Could not read last_api for public URL fallback")
    return ""


def get_effective_public_url() -> str:
    """Return the explicitly configured public URL (settings or env only).

    This does NOT fall back to startup params or browser origin — those
    are handled separately in ``mcp.py`` so that ``browser_origin`` can
    sit between env and startup in the priority chain.

    Resolution order:
    1. ``public_url`` in settings.json (user-configured via UI)
    2. ``QWENPAW_PUBLIC_URL`` environment variable (deployment-time constant)
    3. Empty string → caller decides next fallback
    """
    stored = _load().get("public_url", "").strip().rstrip("/")
    if stored:
        return stored
    if _ENV_PUBLIC_URL:
        return _ENV_PUBLIC_URL
    return ""


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Public URL (OAuth redirect base)
# ---------------------------------------------------------------------------


@router.get("/public-url", summary="Get the public URL for OAuth callbacks")
async def get_public_url() -> dict:
    """Return the effective public URL and its source."""
    stored = _load().get("public_url", "").strip().rstrip("/")
    if stored:
        return {"public_url": stored, "source": "settings"}
    if _ENV_PUBLIC_URL:
        return {"public_url": _ENV_PUBLIC_URL, "source": "env"}
    derived = _derive_url_from_startup_params()
    if derived:
        return {"public_url": derived, "source": "startup"}
    return {"public_url": "", "source": "auto"}


@router.put("/public-url", summary="Set the public URL for OAuth callbacks")
async def put_public_url(
    body: dict = Body(
        ...,
        description=(
            'e.g. {"public_url": "https://gateway.example.com/copaw-a"}'
        ),
    ),
) -> dict:
    url = (body.get("public_url") or "").strip().rstrip("/")
    if not url:
        raise HTTPException(400, detail="public_url must not be empty")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            400,
            detail="public_url must be a valid HTTP(S) URL, "
            f"e.g. https://example.com — got: {url!r}",
        )

    data = _load()
    data["public_url"] = url
    _save(data)
    return {"public_url": url, "source": "settings"}


@router.delete("/public-url", summary="Clear the public URL setting")
async def delete_public_url() -> dict:
    """Remove the user-configured public URL; falls back to env or startup."""
    data = _load()
    data.pop("public_url", None)
    _save(data)
    if _ENV_PUBLIC_URL:
        return {"public_url": _ENV_PUBLIC_URL, "source": "env"}
    derived = _derive_url_from_startup_params()
    if derived:
        return {"public_url": derived, "source": "startup"}
    return {"public_url": "", "source": "auto"}
