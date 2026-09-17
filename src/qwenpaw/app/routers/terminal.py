# -*- coding: utf-8 -*-
"""Interactive terminal endpoints for chat sessions."""
from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...config.config import load_agent_config
from ..agent_context import get_agent_for_request, get_project_dir_for_request
from ..terminal_runtime import TerminalManager

if TYPE_CHECKING:
    from ..workspace import Workspace

router = APIRouter(prefix="/workspace/terminal", tags=["terminal"])
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
SessionId = Annotated[str, Path(min_length=1, max_length=256)]
TerminalId = Annotated[str, Path(pattern=r"^term_[a-f0-9]{32}$")]


class TerminalCreate(BaseModel):
    """Validated dimensions; cwd and shell remain server-owned."""

    cols: int = Field(default=100, ge=20, le=400)
    rows: int = Field(default=30, ge=5, le=200)


class TerminalWrite(BaseModel):
    """Bounded interactive input."""

    data: str = Field(max_length=16384)


class TerminalResize(BaseModel):
    """Validated terminal viewport dimensions."""

    cols: int = Field(ge=20, le=400)
    rows: int = Field(ge=5, le=200)


def _validate_session_id(session_id: str) -> str:
    if not _IDENTIFIER_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=422, detail="INVALID_SESSION_ID")
    return session_id


async def _terminal_enabled_for_workspace(workspace: "Workspace") -> bool:
    cached = getattr(workspace, "terminal_enabled", None)
    if isinstance(cached, bool):
        return cached
    config = await asyncio.to_thread(load_agent_config, workspace.agent_id)
    enabled = bool(config.coding_mode.terminal_enabled)
    workspace.terminal_enabled = enabled
    return enabled


def terminal_gate_lock(workspace: "Workspace") -> asyncio.Lock:
    """Return the lock serializing terminal creation and gate changes."""
    lock = getattr(workspace, "terminal_gate_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        workspace.terminal_gate_lock = lock
    return lock


async def _require_terminal_enabled(request: Request) -> "Workspace":
    workspace = await get_agent_for_request(request)
    if not await _terminal_enabled_for_workspace(workspace):
        raise HTTPException(status_code=403, detail="TERMINAL_DISABLED")
    return workspace


async def get_terminal_manager(
    request: Request,
    workspace: "Workspace" | None = None,
) -> TerminalManager:
    """Return the terminal registry owned by the selected agent."""
    workspace = workspace or await get_agent_for_request(request)
    existing = getattr(workspace, "terminal_manager", None)
    if isinstance(existing, TerminalManager):
        return existing
    manager = TerminalManager()
    workspace.terminal_manager = manager
    managers = getattr(request.app.state, "terminal_managers", None)
    if managers is None:
        managers = set()
        request.app.state.terminal_managers = managers
    managers.add(manager)
    return manager


def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc).strip("'"))


@router.get("/capability")
async def terminal_capability(request: Request) -> dict:
    """Report both configured permission and native availability."""
    workspace = await get_agent_for_request(request)
    capability = TerminalManager.capability()
    enabled = await _terminal_enabled_for_workspace(workspace)
    return {
        **capability,
        "enabled": enabled,
        "reason": (
            capability["reason"]
            if not capability["available"]
            else ("TERMINAL_DISABLED" if not enabled else "")
        ),
    }


@router.get("/sessions/{session_id}")
async def list_terminals(session_id: SessionId, request: Request) -> list[dict]:
    """List attachable terminals owned by one conversation session."""
    _validate_session_id(session_id)
    workspace = await _require_terminal_enabled(request)
    manager = await get_terminal_manager(request, workspace)
    return [
        {"terminal_id": item.id, "closed": item.closed}
        for item in manager.list_session(session_id)
    ]


@router.post("/sessions/{session_id}", status_code=201)
async def create_terminal(
    session_id: SessionId,
    command: TerminalCreate,
    request: Request,
) -> dict:
    """Create a shell in the session's effective project directory."""
    _validate_session_id(session_id)
    capability = TerminalManager.capability()
    if not capability["available"]:
        raise HTTPException(status_code=501, detail=capability["reason"])
    workspace = await get_agent_for_request(request)
    async with terminal_gate_lock(workspace):
        if not await _terminal_enabled_for_workspace(workspace):
            raise HTTPException(status_code=403, detail="TERMINAL_DISABLED")
        cwd = await get_project_dir_for_request(request, workspace)
        try:
            session = await (
                await get_terminal_manager(request, workspace)
            ).create(session_id, cwd, command.cols, command.rows)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "terminal_id": session.id,
        "backend": capability["backend"],
    }


@router.get("/sessions/{session_id}/{terminal_id}/events")
async def terminal_events(
    session_id: SessionId,
    terminal_id: TerminalId,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """Attach an isolated SSE subscriber with bounded replay."""
    _validate_session_id(session_id)
    workspace = await _require_terminal_enabled(request)
    try:
        session = (await get_terminal_manager(request, workspace)).get(
            session_id,
            terminal_id,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc

    async def generate():
        async for event in session.subscribe(after_seq):
            payload = json.dumps(event.as_dict(), ensure_ascii=False)
            yield f"id: {event.seq}\ndata: {payload}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _owned_terminal(
    request: Request,
    session_id: str,
    terminal_id: str,
):
    _validate_session_id(session_id)
    workspace = await _require_terminal_enabled(request)
    try:
        return (await get_terminal_manager(request, workspace)).get(
            session_id,
            terminal_id,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.post("/sessions/{session_id}/{terminal_id}/write")
async def write_terminal(
    session_id: SessionId,
    terminal_id: TerminalId,
    command: TerminalWrite,
    request: Request,
) -> dict:
    """Write bounded user input to one session-owned terminal."""
    await (await _owned_terminal(request, session_id, terminal_id)).write(
        command.data,
    )
    return {"accepted": True}


@router.post("/sessions/{session_id}/{terminal_id}/resize")
async def resize_terminal(
    session_id: SessionId,
    terminal_id: TerminalId,
    command: TerminalResize,
    request: Request,
) -> dict:
    """Resize one session-owned terminal."""
    await (await _owned_terminal(request, session_id, terminal_id)).resize(
        command.cols,
        command.rows,
    )
    return {"accepted": True}


@router.delete("/sessions/{session_id}/{terminal_id}", status_code=204)
async def close_terminal(
    session_id: SessionId,
    terminal_id: TerminalId,
    request: Request,
) -> None:
    """Terminate one session-owned terminal process group."""
    _validate_session_id(session_id)
    workspace = await _require_terminal_enabled(request)
    try:
        await (await get_terminal_manager(request, workspace)).close(
            session_id,
            terminal_id,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
