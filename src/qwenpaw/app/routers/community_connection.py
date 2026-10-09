# -*- coding: utf-8 -*-
"""Local settings endpoints for an explicitly configured community client."""

from __future__ import annotations

import os
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..community_connection import (
    CommunityConnectionError,
    CommunityConnectionService,
)

router = APIRouter(prefix="/community/connection", tags=["community"])


def get_service(request: Request) -> CommunityConnectionService:
    """Share a single service with the runtime lifespan polling task."""
    service = getattr(request.app.state, "community_connection_service", None)
    if service is None:
        service = CommunityConnectionService()
        request.app.state.community_connection_service = service
    return service


def is_local_request(request: Request) -> bool:
    """Do not mistake a Hub proxy or arbitrary web origin for loopback UI."""
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if (
        os.getenv("QWENPAW_RUNTIME_INTERNAL_TOKEN")
        or not request.client
        or request.client.host not in local_hosts
        or request.url.hostname not in local_hosts
    ):
        return False
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        if parsed.hostname not in local_hosts and origin not in {
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        }:
            return False
        if parsed.scheme not in {"http", "https", "tauri"}:
            return False
    return True


async def _call(awaitable):
    try:
        return await awaitable
    except CommunityConnectionError as exc:
        raise HTTPException(
            # A Platform session is independent of QwenPaw's local login.
            # Do not let an upstream 401 log the user out of QwenPaw.
            status_code=409 if exc.status_code == 401 else exc.status_code,
            detail=exc.code,
        ) from exc


@router.get("")
async def get_connection_status(request: Request):
    return await _call(
        get_service(request).status(local=is_local_request(request)),
    )


@router.post("/start")
async def start_connection(request: Request):
    return await _call(
        get_service(request).start(local=is_local_request(request)),
    )


@router.get("/authorization/{flow_id}")
async def get_authorization_status(flow_id: str, request: Request):
    return await _call(get_service(request).authorization_status(flow_id))


@router.delete("/authorization/{flow_id}")
async def cancel_authorization(flow_id: str, request: Request):
    await _call(get_service(request).cancel(flow_id))
    return {"cancelled": True}


@router.delete("")
async def disconnect_community(request: Request):
    return await _call(get_service(request).disconnect())


class SyncSettings(BaseModel):
    enabled: bool | None = None
    message_types: (
        list[
            Literal[
                "comments",
                "mentions",
                "interactions",
                "feedback",
                "notifications",
            ]
        ]
        | None
    ) = None


@router.patch("/sync")
async def update_sync_settings(body: SyncSettings, request: Request):
    return await _call(
        get_service(request).set_sync(body.enabled, body.message_types),
    )


@router.post("/sync")
async def sync_community(request: Request):
    return await _call(get_service(request).sync_once())
