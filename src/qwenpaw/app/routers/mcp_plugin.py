# -*- coding: utf-8 -*-
"""Explicit, offline installation from the trusted optional MCP resource."""

from fastapi import APIRouter, Request

from ..mcp.plugin_service import plugin_state, unavailable
from ..mcp_plugin_upgrade import get_coordinator

router = APIRouter(prefix="/mcp-plugin", tags=["mcp"])


@router.get("")
async def get_mcp_plugin(request: Request):
    return await plugin_state(request)


@router.post("/install")
async def install_mcp_plugin(request: Request):
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        raise unavailable()
    await get_coordinator(loader).install_explicitly()
    return await plugin_state(request)
