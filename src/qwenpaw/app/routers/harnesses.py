# -*- coding: utf-8 -*-
"""Coding harness catalog and authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..agent_context import get_agent_for_request

router = APIRouter(prefix="/harnesses", tags=["harnesses"])


class HarnessLoginRequest(BaseModel):
    """Options for starting a provider login."""

    device_code: bool = False


@router.get("")
async def get_harnesses(request: Request) -> dict:
    """Return supported and planned third-party agent backends."""
    workspace = await get_agent_for_request(request)
    providers = await workspace.harness_runtime.providers()
    return {"providers": [item.model_dump() for item in providers]}


@router.post("/codex/login")
async def post_codex_login(
    body: HarnessLoginRequest,
    request: Request,
) -> dict:
    """Start Codex-managed ChatGPT OAuth."""
    workspace = await get_agent_for_request(request)
    adapter = workspace.harness_runtime.adapter("codex")
    return await adapter.start_login(device_code=body.device_code)


@router.post("/codex/logout")
async def post_codex_logout(request: Request) -> dict:
    """Log the local Codex runtime out of ChatGPT."""
    workspace = await get_agent_for_request(request)
    adapter = workspace.harness_runtime.adapter("codex")
    await adapter.logout()
    return {"ok": True}


__all__ = ["router"]
