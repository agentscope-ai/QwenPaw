# -*- coding: utf-8 -*-
"""API endpoints for managing coding CLIs in the worker container."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...coding_cli.registry import get_cli
from ...coding_cli.service import (
    CodingCliService,
    InstallBusyError,
)

router = APIRouter(prefix="/coding-cli", tags=["coding-cli"])


def _get_service(request: Request) -> CodingCliService:
    return request.app.state.coding_cli_service


def _require_cli(cli_id: str):
    spec = get_cli(cli_id)
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown coding CLI: {cli_id}",
        )
    return spec


class SettingsPatch(BaseModel):
    """Partial settings to merge into the CLI settings file."""

    settings: dict[str, Any] = Field(default_factory=dict)


class InstallRequest(BaseModel):
    """Install/upgrade request.

    ``tag`` accepts an npm dist-tag (``latest``, ``nightly``) or a
    concrete version string (``0.25.0``).
    """

    tag: str = "latest"


@router.get("")
async def list_coding_clis(request: Request) -> dict:
    """Probe and summarize all registered coding CLIs."""
    from ...coding_cli.registry import CLIS

    service = _get_service(request)
    clis = [await service.probe(spec) for spec in CLIS.values()]
    return {"clis": clis}


@router.get("/{cli_id}/settings")
async def get_coding_cli_settings(cli_id: str, request: Request) -> dict:
    """Read CLI settings with credentials redacted."""
    spec = _require_cli(cli_id)
    service = _get_service(request)
    settings = await service.read_settings(spec)
    return {"cli": spec.id, "settings": settings}


@router.put("/{cli_id}/settings")
async def put_coding_cli_settings(
    cli_id: str,
    body: SettingsPatch,
    request: Request,
) -> dict:
    """Merge settings; ``"***"`` values keep the existing secret."""
    spec = _require_cli(cli_id)
    service = _get_service(request)
    try:
        settings = await service.write_settings(spec, body.settings)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write settings: {exc}",
        ) from exc
    return {"cli": spec.id, "settings": settings}


@router.post("/{cli_id}/install", status_code=202)
async def post_coding_cli_install(
    cli_id: str,
    body: InstallRequest,
    request: Request,
) -> dict:
    """Start an async npm install/upgrade for the CLI."""
    spec = _require_cli(cli_id)
    service = _get_service(request)
    try:
        task_id = await service.start_install(spec, body.tag)
    except InstallBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": task_id, "cli": spec.id, "tag": body.tag}


@router.get("/{cli_id}/install/{task_id}")
async def get_coding_cli_install(
    cli_id: str,
    task_id: str,
    request: Request,
) -> dict:
    """Report install task state."""
    spec = _require_cli(cli_id)
    service = _get_service(request)
    task = service.install_status(task_id)
    if task is None or task["cli"] != spec.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


__all__ = ["router"]
