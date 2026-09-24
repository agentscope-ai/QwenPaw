# -*- coding: utf-8 -*-
"""Capability bridge used by isolated PawApp runtimes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .capabilities import CapabilityError

router = APIRouter(prefix="/pawapp-capabilities", tags=["pawapp-capabilities"])


class InvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any] = Field(default_factory=dict)


def _broker(request: Request):
    broker = getattr(request.app.state, "pawapp_capabilities", None)
    if broker is None:
        raise HTTPException(
            status_code=503, detail="capability_broker_unavailable"
        )
    return broker


def _token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or not header[7:]:
        raise HTTPException(status_code=401, detail="invalid_capability_token")
    return header[7:]


def _error(exc: CapabilityError) -> HTTPException:
    status = 404 if exc.code == "capability_not_found" else 403
    if exc.code in {"invalid_tool_input", "skill_too_large"}:
        status = 422
    elif exc.code in {"workspace_unavailable", "tool_failed"}:
        status = 503
    return HTTPException(status_code=status, detail=exc.code)


async def _scope(request: Request):
    try:
        return await _broker(request).authorize_token(_token(request))
    except CapabilityError as exc:
        raise _error(exc) from None


@router.get("/catalog")
async def catalog(request: Request):
    try:
        scope = await _scope(request)
        descriptors = await _broker(request).catalog(scope)
        return {
            "protocol_version": 1,
            "capabilities": [
                item.model_dump(mode="json") for item in descriptors
            ],
        }
    except CapabilityError as exc:
        raise _error(exc) from None


@router.get("/capabilities/{capability_id:path}")
async def describe(request: Request, capability_id: str):
    try:
        scope = await _scope(request)
        descriptor = await _broker(request).describe(scope, capability_id)
        return {
            "protocol_version": 1,
            "capability": descriptor.model_dump(mode="json"),
        }
    except CapabilityError as exc:
        raise _error(exc) from None


@router.post("/tools/{capability_id:path}/invoke")
async def invoke(request: Request, capability_id: str, body: InvokeRequest):
    try:
        scope = await _scope(request)
        result = await _broker(request).invoke(
            scope, capability_id, body.params
        )
        return {"protocol_version": 1, **result}
    except CapabilityError as exc:
        raise _error(exc) from None


@router.get("/skills/{capability_id:path}")
async def load_skill(request: Request, capability_id: str):
    try:
        scope = await _scope(request)
        result = await _broker(request).load_skill(scope, capability_id)
        return {"protocol_version": 1, **result}
    except CapabilityError as exc:
        raise _error(exc) from None


__all__ = ["router"]
