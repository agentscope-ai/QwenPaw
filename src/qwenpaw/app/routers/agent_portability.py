# -*- coding: utf-8 -*-
"""Agent 可移植包导出和当前用户草稿导入 API。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ...access.agent_repository import AgentResourceRole, LegacyAgentRecord
from ...agents.portable_package import (
    MAX_TOTAL_BYTES,
    PortableAgentPackage,
    PortablePackageError,
    build_portable_package,
    read_portable_package,
)
from ...config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    generate_short_agent_id,
    load_agent_config,
    save_agent_config,
)
from ...config.utils import load_config, save_config
from ...constant import WORKING_DIR
from ...identity.runtime import is_multi_user_enabled
from .agents import (
    _get_agent_membership_service,
    _get_agent_metadata_repository,
    _normalized_agent_order,
    _request_actor,
)

router = APIRouter(prefix="/agents", tags=["agent-portability"])
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class AgentImportResponse(BaseModel):
    agent_id: str
    name: str
    status: str = "draft"
    requires_reauthorization: bool = True
    dependencies: dict[str, list[str]]


def _legacy_record(agent_id: str) -> LegacyAgentRecord:
    config = load_config()
    ref = config.agents.profiles.get(agent_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="agent_not_found")
    profile = load_agent_config(agent_id)
    return LegacyAgentRecord(
        key=agent_id,
        name=profile.name,
        description=profile.description or "",
        workspace_key=ref.workspace_dir,
        status="active" if ref.enabled else "disabled",
    )


async def _require_owner(agent_id: str, request: Request) -> LegacyAgentRecord:
    record = _legacy_record(agent_id)
    if not is_multi_user_enabled():
        return record
    try:
        await _get_agent_membership_service().require_role(
            actor=_request_actor(request),
            agent=record,
            allowed_roles={AgentResourceRole.OWNER},
        )
    except Exception as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    return record


@router.get("/{agent_id}/portable-package", summary="Export an Agent portable package")
async def export_agent_package(agent_id: str, request: Request) -> Response:
    record = await _require_owner(agent_id, request)
    profile = load_agent_config(agent_id)
    try:
        payload = build_portable_package(
            agent_config=profile.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            workspace_dir=Path(record.workspace_key).expanduser(),
        )
    except PortablePackageError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    safe_name = _SAFE_FILENAME.sub("-", profile.name).strip("-.") or agent_id
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.qwenpaw-agent.zip"',
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _read_upload(file: UploadFile) -> bytes:
    payload = await file.read(MAX_TOTAL_BYTES + 1)
    if len(payload) > MAX_TOTAL_BYTES:
        raise HTTPException(status_code=413, detail="package_too_large")
    return payload


def _write_workspace(package: PortableAgentPackage, workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=False)
    root = workspace.resolve()
    for relative, content in package.files.items():
        target = (workspace / Path(relative)).resolve()
        if root not in target.parents:
            raise PortablePackageError("unsafe_path")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _new_agent_id(existing_ids: set[str]) -> str:
    for _ in range(10):
        candidate = generate_short_agent_id()
        if candidate not in existing_ids:
            return candidate
    raise HTTPException(status_code=500, detail="agent_id_generation_failed")


@router.post(
    "/portable-package/import", status_code=201, summary="Import an Agent as a draft"
)
async def import_agent_package(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> AgentImportResponse:
    actor = _request_actor(request) if is_multi_user_enabled() else None
    try:
        package = read_portable_package(await _read_upload(file))
    except PortablePackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    config = load_config()
    new_id = _new_agent_id(set(config.agents.profiles))
    workspace = Path(WORKING_DIR).expanduser() / "workspaces" / new_id
    raw_profile: dict[str, Any] = dict(package.config)
    raw_profile.update(
        {
            "id": new_id,
            "name": (name or str(raw_profile.get("name") or "Imported Agent")).strip(),
            "workspace_dir": str(workspace),
            "project_dir": None,
            "active_model": None,
        }
    )
    try:
        profile = AgentProfileConfig.model_validate(raw_profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_agent_config") from exc

    try:
        _write_workspace(package, workspace)
        if is_multi_user_enabled():
            if actor is None or actor.user_id is None:
                raise HTTPException(status_code=401, detail="not_authenticated")
            repository = _get_agent_metadata_repository()
            draft = LegacyAgentRecord(
                key=new_id,
                name=profile.name,
                description=profile.description or "",
                workspace_key=str(workspace),
                status="draft",
            )
            await repository.register_owner(
                agent=draft,
                owner_user_id=actor.user_id,
                status="draft",
            )
            await repository.update_metadata(agent=draft)
            await repository.update_model_mode(new_id, "inherited")
        config.agents.profiles[new_id] = AgentProfileRef(
            id=new_id,
            workspace_dir=str(workspace),
            enabled=False,
        )
        config.agents.agent_order = _normalized_agent_order(config)
        save_config(config)
        save_agent_config(new_id, profile)
    except HTTPException:
        raise
    except (OSError, PortablePackageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AgentImportResponse(
        agent_id=new_id,
        name=profile.name,
        dependencies=package.dependencies,
    )
