# -*- coding: utf-8 -*-
"""FastAPI routers for the NocoBase auth plugin."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from .config import NocoBaseAuthConfig
from .sync_engine import get_sync_engine

logger = logging.getLogger(__name__)

# Hold strong references to background webhook sync tasks so they are not
# garbage-collected before completion.
_webhook_tasks: set[asyncio.Task] = set()


def build_router() -> APIRouter:
    """Build and return the plugin API router."""
    router = APIRouter(tags=["nocobase-auth"])

    @router.get("/status")
    async def status() -> Dict[str, Any]:
        """Return connection status and last sync info."""
        engine = get_sync_engine()
        if engine is None:
            return {
                "enabled": False,
                "configured": False,
                "error": "Plugin not initialized",
            }

        config = engine.config
        sync_status = engine.store.get_last_sync_status()
        return {
            "enabled": config.enabled,
            "configured": bool(config.base_url and config.api_token),
            "base_url": config.base_url,
            "user_id_field": config.user_id_field,
            **sync_status,
        }

    @router.post("/sync")
    async def sync() -> Dict[str, Any]:
        """Trigger a full sync from NocoBase."""
        engine = get_sync_engine()
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail="Plugin not initialized",
            )
        return await engine.sync()

    @router.post("/webhook")
    async def webhook(payload: Dict[str, Any]) -> Dict[str, str]:
        """Receive a NocoBase webhook push and trigger a sync."""
        engine = get_sync_engine()
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail="Plugin not initialized",
            )

        logger.info("Received NocoBase webhook: %s", payload.get("event"))
        # Run sync in background so we return quickly. Keep a strong reference
        # to avoid the task being garbage-collected before completion.
        task = asyncio.create_task(engine.sync())
        _webhook_tasks.add(task)
        task.add_done_callback(_webhook_tasks.discard)
        return {"status": "accepted"}

    @router.get("/users")
    async def list_users() -> List[Dict[str, Any]]:
        """Return cached NocoBase users."""
        engine = get_sync_engine()
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail="Plugin not initialized",
            )
        return engine.store.list_users()

    @router.get("/roles")
    async def list_roles() -> List[Dict[str, Any]]:
        """Return cached NocoBase roles."""
        engine = get_sync_engine()
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail="Plugin not initialized",
            )
        return engine.store.list_roles()

    @router.get("/config")
    async def get_config() -> Dict[str, Any]:
        """Return current plugin configuration."""
        engine = get_sync_engine()
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail="Plugin not initialized",
            )
        return engine.config.to_dict()

    @router.put("/config")
    async def update_config(request: Request) -> Dict[str, Any]:
        """Update plugin configuration and persist role mappings."""
        engine = get_sync_engine()
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail="Plugin not initialized",
            )

        data = await request.json()
        try:
            config = NocoBaseAuthConfig.from_dict(data)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        engine.update_config(config)

        # Persist role channel map separately in the permission store.
        role_map = {
            mapping.role_name: {
                "allowed": mapping.allowed_channels,
                "denied": mapping.denied_channels,
            }
            for mapping in config.role_channel_map
        }
        engine.store.set_role_channel_map(role_map)

        return {"status": "ok"}

    @router.post("/test-connection")
    async def test_connection() -> Dict[str, Any]:
        """Test NocoBase connectivity with current config."""
        engine = get_sync_engine()
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail="Plugin not initialized",
            )
        return await engine.test_connection()

    return router
