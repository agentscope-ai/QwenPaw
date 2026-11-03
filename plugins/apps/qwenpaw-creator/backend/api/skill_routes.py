# -*- coding: utf-8 -*-
# The host runtime is a plain third-party dependency of this plugin; pylint
# resolves it as first-party from the repo root; the order check is off.
# pylint: disable=wrong-import-order
"""Skill listing, content view, save, toggle and delete endpoints.

Backs the "Skills" pane of the model-configuration modal. User skills are
content-based (name + SKILL.md body) and persisted under the data root;
builtin skills ship with the code tree and are read-only here.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from qwenpaw.exceptions import AppBaseException
from starlette.datastructures import UploadFile

from services.external_skills import (
    _BUILTIN_SKILLS_ROOT,
    LoadedSkill,
    SkillExecutionError,
    load_skills,
    parse_skill_md,
    read_skill_content,
)
from services.media_files.user_skills import (
    MAX_SKILL_ZIP_BYTES,
    UserSkillError,
    delete_user_skill,
    import_skills_from_zip_bytes,
    install_skill_from_hub_bundle,
    save_user_skill,
    set_user_skill_enabled,
    zip_too_large_detail,
)
from services.skill_hub import (
    SkillHubTimeout,
    SkillHubUnavailable,
    SkillHubUrlError,
    fetch_skill_bundle,
)
from services.storage_root import CreatorDataRootError

router = APIRouter(prefix="/skills", tags=["skills"])


def _is_builtin(skill: LoadedSkill) -> bool:
    try:
        skill.root.resolve().relative_to(_BUILTIN_SKILLS_ROOT.resolve())
        return True
    except (ValueError, OSError):
        return False


def _resolve_description(skill: LoadedSkill) -> str | None:
    """Config description first, else the SKILL.md front matter.

    Builtin entries are constructed without a description, so their
    front matter is the source of truth. Mirrors _skill_context_block
    so the UI shows the same text the agent sees in its prompt.
    """

    configured = (skill.entry.description or "").strip()
    if configured:
        return configured
    try:
        parsed = parse_skill_md(skill.skill_md).get("description", "")
    except Exception:
        parsed = ""
    return parsed.strip() or None


def _item(skill: LoadedSkill) -> dict[str, Any]:
    return {
        "name": skill.entry.name,
        "description": _resolve_description(skill),
        "enabled": skill.entry.enabled,
        "status": skill.status,
        "reason": skill.reason,
        "builtin": _is_builtin(skill),
    }


def _data_root_guard(action):
    try:
        return action()
    except CreatorDataRootError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except UserSkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_skills() -> dict[str, Any]:
    items = await asyncio.to_thread(
        lambda: [_item(skill) for skill in load_skills()],
    )
    return {"items": items}


@router.get("/{name}/content")
async def get_skill_content(name: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(read_skill_content, skill_name=name)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class SaveSkillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1)
    # Only the client knows which operation it means: the editor fixes the
    # name when editing an existing skill and leaves it free when creating one,
    # so creating must never be allowed to replace a same-named skill.
    overwrite: bool = False


@router.post("")
async def save_skill(request: SaveSkillRequest) -> dict[str, Any]:
    # Every writer here takes the module-wide skills_config lock and does
    # blocking disk IO, so none of it may run on the ASGI event loop: waiting
    # for a lock held by a ZIP import worker would stall every other request.
    entry = await asyncio.to_thread(
        _data_root_guard,
        lambda: save_user_skill(
            request.name.strip(),
            request.content,
            overwrite=request.overwrite,
        ),
    )
    return {"ok": True, "name": entry.name}


@router.post("/upload")
async def upload_skill_zip(request: Request) -> dict[str, Any]:
    """Import one or more skills from an uploaded zip (SKILL.md bundle)."""

    # Refuse an oversized body before parsing it: the multipart reader spools
    # the upload to a temporary file and read() then pulls it into memory, so
    # without this the importer's own size check ran only after both had
    # happened. A chunked upload declares no length and falls through to the
    # bounded read below.
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit():
        if int(declared) > MAX_SKILL_ZIP_BYTES:
            raise HTTPException(400, detail=zip_too_large_detail())
    form = await request.form()
    upload = next(
        (
            value
            for _, value in form.multi_items()
            if isinstance(value, UploadFile)
        ),
        None,
    )
    if upload is None:
        raise HTTPException(status_code=400, detail="未找到上传的文件")
    filename = Path(upload.filename or "").name
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .zip 文件")
    # One byte past the cap is enough to refuse and keeps an over-limit body
    # out of memory. The importer re-checks: it is also reachable without
    # this route.
    data = await upload.read(MAX_SKILL_ZIP_BYTES + 1)
    return await asyncio.to_thread(
        _data_root_guard,
        lambda: import_skills_from_zip_bytes(data),
    )


class ImportSkillUrlRequest(BaseModel):
    bundle_url: str = Field(min_length=1, max_length=2048)
    # Pins the skill name instead of inheriting whatever the remote bundle
    # declares, mirroring the Pool's own target_name escape hatch.
    target_name: str | None = Field(default=None, max_length=64)
    version: str = Field(default="", max_length=64)


@router.post("/import-url")
async def import_skill_from_url(
    request: ImportSkillUrlRequest,
) -> dict[str, Any]:
    """Import one skill from a Skills Hub URL, as the Skill Pool does.

    Only the write is Creator's. Routing the URL to its market, fetching and
    capping the package and sanitising its paths all stay in the host, so a
    hub import lands on exactly the same strict create that refuses a
    duplicate name for a hand-authored skill.
    """

    target = (request.target_name or "").strip() or None
    try:
        bundle = await fetch_skill_bundle(
            request.bundle_url,
            version=request.version,
            target_name=target,
        )
    except SkillHubUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SkillHubUnavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except SkillHubTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (ValueError, AppBaseException) as exc:
        # The host reports a bad URL, an unreachable market or an unusable
        # bundle through these, the same pair its own Pool route maps to 400.
        raise HTTPException(
            status_code=400,
            detail=f"从 URL 导入失败：{exc}",
        ) from exc
    # Off the event loop like every other writer here: this takes the
    # module-wide skills_config lock and does blocking disk IO.
    return await asyncio.to_thread(
        _data_root_guard,
        lambda: install_skill_from_hub_bundle(bundle),
    )


class ToggleSkillRequest(BaseModel):
    enabled: bool


@router.patch("/{name}")
async def toggle_skill(
    name: str,
    request: ToggleSkillRequest,
) -> dict[str, Any]:
    changed = await asyncio.to_thread(
        _data_root_guard,
        lambda: set_user_skill_enabled(name, request.enabled),
    )
    if not changed:
        raise HTTPException(status_code=404, detail=f"技能不存在或为内置: {name}")
    return {"ok": True, "name": name, "enabled": request.enabled}


@router.delete("/{name}")
async def remove_skill(name: str) -> dict[str, Any]:
    deleted = await asyncio.to_thread(
        _data_root_guard,
        lambda: delete_user_skill(name),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail=f"技能不存在或为内置: {name}")
    return {"deleted": name}


__all__ = ["router"]
