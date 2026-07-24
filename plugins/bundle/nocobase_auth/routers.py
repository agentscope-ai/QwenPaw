# -*- coding: utf-8 -*-
"""FastAPI routers for the NocoBase auth plugin."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from .config import NocoBaseAuthConfig
from .engine import get_engine

logger = logging.getLogger(__name__)


def _require_engine():
    engine = get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Plugin not initialized")
    return engine


def build_router() -> APIRouter:
    """Build and return the plugin API router."""
    router = APIRouter(tags=["nocobase-auth"])

    @router.get("/status")
    async def status() -> Dict[str, Any]:
        engine = get_engine()
        if engine is None:
            return {
                "enabled": False,
                "configured": False,
                "error": "Plugin not initialized",
            }
        config = engine.config
        return {
            "enabled": config.enabled,
            "configured": bool(config.base_url and config.api_token),
            "base_url": config.base_url,
            "user_id_field": config.user_id_field,
        }

    @router.get("/users")
    async def list_users() -> List[Dict[str, Any]]:
        """Return NocoBase users, queried live. Errors instead of empty."""
        engine = _require_engine()
        try:
            return await engine.list_users()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=f"Failed to query NocoBase users: {exc}",
            ) from exc

    @router.get("/roles")
    async def list_roles() -> List[Dict[str, Any]]:
        """Return NocoBase roles, queried live. Errors instead of empty."""
        engine = _require_engine()
        try:
            return await engine.list_roles()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=f"Failed to query NocoBase roles: {exc}",
            ) from exc

    @router.get("/config")
    async def get_config() -> Dict[str, Any]:
        engine = _require_engine()
        return engine.config.to_dict()

    @router.put("/config")
    async def update_config(request: Request) -> Dict[str, Any]:
        engine = _require_engine()
        data = await request.json()
        try:
            config = NocoBaseAuthConfig.from_dict(data)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await engine.update_config(config)
        return {"status": "ok"}

    @router.post("/test-connection")
    async def test_connection() -> Dict[str, Any]:
        engine = _require_engine()
        return await engine.test_connection()

    return router
