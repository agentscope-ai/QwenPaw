# -*- coding: utf-8 -*-
"""API router for channel access control (whitelist / blacklist / pending)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from ..channels.access_control import get_access_control_store

router = APIRouter(prefix="/access-control", tags=["access-control"])


async def _get_store(request: Request):
    """Get the AccessControlStore for the current workspace."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    return get_access_control_store(workspace_dir)


# ── Request / Response schemas ──────────────────────────────────────────────


class ACLResponse(BaseModel):
    whitelist: Dict[str, str] = Field(default_factory=dict)
    blacklist: Dict[str, str] = Field(default_factory=dict)
    pending: List[dict] = Field(default_factory=list)


class UserListBody(BaseModel):
    user_ids: List[str]


class PendingActionEntry(BaseModel):
    channel: str
    user_id: str
    remark: str = ""


class PendingActionBody(BaseModel):
    """Unified body for single or batch pending operations."""
    entries: List[PendingActionEntry]


class UpdateRemarkBody(BaseModel):
    channel: str
    user_id: str
    remark: str


class PendingEntry(BaseModel):
    user_id: str
    channel: str
    timestamp: float
    first_message: str = ""


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="Get all access control lists",
    response_model=dict,
)
async def get_all_acls(request: Request):
    """Return channels that have data OR have access control enabled."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    store = get_access_control_store(Path(workspace.workspace_dir))
    raw_acls = store.get_all_acls()

    # Collect enabled channel names
    enabled_channels: set = set()
    service_manager = getattr(workspace, "_service_manager", None)
    if service_manager:
        cm = service_manager.services.get("channel_manager")
        if cm:
            for ch in cm.channels:
                if ch.access_control_enabled:
                    enabled_channels.add(ch.channel)

    # Only return channels that are non-empty OR have access control on
    result = {}
    for key, data in raw_acls.items():
        has_data = (
            data.get("whitelist")
            or data.get("blacklist")
            or data.get("pending")
        )
        if has_data or key in enabled_channels:
            result[key] = data

    # Add enabled channels not yet in file
    for ch_name in enabled_channels:
        if ch_name not in result:
            result[ch_name] = {"whitelist": {}, "blacklist": {}, "pending": []}

    return result


# ── Pending routes MUST come before /{channel} to avoid path conflicts ──────


@router.get(
    "/pending/all",
    summary="Get all pending approval entries",
    response_model=List[PendingEntry],
)
async def get_all_pending(request: Request):
    store = await _get_store(request)
    return store.get_all_pending()


@router.post(
    "/pending/approve",
    summary="Approve one or more pending users (add to whitelist)",
)
async def approve_pending(request: Request, body: PendingActionBody):
    store = await _get_store(request)
    for entry in body.entries:
        store.approve_pending(entry.channel, entry.user_id, entry.remark)
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/pending/deny",
    summary="Deny one or more pending users (add to blacklist)",
)
async def deny_pending(request: Request, body: PendingActionBody):
    store = await _get_store(request)
    for entry in body.entries:
        store.deny_pending(entry.channel, entry.user_id, entry.remark)
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/pending/dismiss",
    summary="Dismiss one or more pending users (remove without action)",
)
async def dismiss_pending(request: Request, body: PendingActionBody):
    store = await _get_store(request)
    for entry in body.entries:
        store.dismiss_pending(entry.channel, entry.user_id)
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/pending/remark",
    summary="Update remark on a pending entry",
)
async def update_pending_remark(request: Request, body: UpdateRemarkBody):
    store = await _get_store(request)
    found = store.update_pending_remark(body.channel, body.user_id, body.remark)
    if not found:
        raise HTTPException(status_code=404, detail="Pending entry not found")
    return {"status": "ok"}


# ── Channel-specific routes (/{channel} is a catch-all path param) ──────────


@router.get(
    "/{channel}",
    summary="Get access control list for a channel",
    response_model=ACLResponse,
)
async def get_channel_acl(request: Request, channel: str):
    store = await _get_store(request)
    return store.get_acl(channel)


@router.put(
    "/{channel}/whitelist",
    summary="Set whitelist for a channel",
)
async def set_whitelist(request: Request, channel: str, body: UserListBody):
    store = await _get_store(request)
    store.set_whitelist(channel, body.user_ids)
    return {"status": "ok"}


@router.post(
    "/{channel}/whitelist/add",
    summary="Add a user to channel whitelist",
)
async def add_to_whitelist(
    request: Request,
    channel: str,
    user_id: str = Body(..., embed=True),
    remark: str = Body("", embed=True),
):
    store = await _get_store(request)
    store.add_to_whitelist(channel, user_id, remark)
    return {"status": "ok"}


@router.post(
    "/{channel}/whitelist/remove",
    summary="Remove a user from channel whitelist",
)
async def remove_from_whitelist(
    request: Request,
    channel: str,
    user_id: str = Body(..., embed=True),
):
    store = await _get_store(request)
    store.remove_from_whitelist(channel, user_id)
    return {"status": "ok"}


@router.put(
    "/{channel}/blacklist",
    summary="Set blacklist for a channel",
)
async def set_blacklist(request: Request, channel: str, body: UserListBody):
    store = await _get_store(request)
    store.set_blacklist(channel, body.user_ids)
    return {"status": "ok"}


@router.post(
    "/{channel}/blacklist/add",
    summary="Add a user to channel blacklist",
)
async def add_to_blacklist(
    request: Request,
    channel: str,
    user_id: str = Body(..., embed=True),
    remark: str = Body("", embed=True),
):
    store = await _get_store(request)
    store.add_to_blacklist(channel, user_id, remark)
    return {"status": "ok"}


@router.post(
    "/{channel}/blacklist/remove",
    summary="Remove a user from channel blacklist",
)
async def remove_from_blacklist(
    request: Request,
    channel: str,
    user_id: str = Body(..., embed=True),
):
    store = await _get_store(request)
    store.remove_from_blacklist(channel, user_id)
    return {"status": "ok"}


@router.post(
    "/{channel}/remark",
    summary="Update remark for a user in whitelist or blacklist",
)
async def update_remark(
    request: Request,
    channel: str,
    user_id: str = Body(..., embed=True),
    remark: str = Body("", embed=True),
):
    store = await _get_store(request)
    found = store.update_remark(channel, user_id, remark)
    if not found:
        raise HTTPException(
            status_code=404,
            detail="User not found in any list",
        )
    return {"status": "ok"}
