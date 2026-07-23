# -*- coding: utf-8 -*-
"""Coding harness catalog and authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..agent_context import get_agent_for_request
from ...harnesses.registry import get_provider

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


def _supported_provider(provider_id: str):
    """Resolve an enabled provider or return a client-facing error."""
    try:
        provider = get_provider(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if provider.coming_soon:
        raise HTTPException(
            status_code=409,
            detail=f"{provider.name} is not available yet",
        )
    return provider


@router.get("/{provider_id}/models")
async def get_harness_models(
    provider_id: str,
    request: Request,
) -> dict:
    """Return provider-owned models for the current account."""
    _supported_provider(provider_id)
    workspace = await get_agent_for_request(request)
    adapter = workspace.harness_runtime.adapter(provider_id)
    models = await adapter.models()
    return {"models": [item.model_dump() for item in models]}


@router.post("/{provider_id}/login")
async def post_harness_login(
    provider_id: str,
    body: HarnessLoginRequest,
    request: Request,
) -> dict:
    """Start a provider-owned login flow."""
    _supported_provider(provider_id)
    workspace = await get_agent_for_request(request)
    adapter = workspace.harness_runtime.adapter(provider_id)
    return await adapter.start_login(device_code=body.device_code)


@router.post("/{provider_id}/logout")
async def post_harness_logout(
    provider_id: str,
    request: Request,
) -> dict:
    """Log out through the provider-owned runtime."""
    _supported_provider(provider_id)
    workspace = await get_agent_for_request(request)
    adapter = workspace.harness_runtime.adapter(provider_id)
    await adapter.logout()
    return {"ok": True}


__all__ = ["router"]
