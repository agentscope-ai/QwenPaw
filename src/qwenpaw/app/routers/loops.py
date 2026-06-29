# -*- coding: utf-8 -*-
"""Loop management API — CRUD for user-defined loops.

Endpoints:
    GET    /api/loops          — list all available loops
    POST   /api/loops          — create a user-defined loop
    PUT    /api/loops/{name}   — update a user-defined loop
    DELETE /api/loops/{name}   — delete a user-defined loop
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...loop.schema import LoopSkillConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/loops", tags=["loops"])

USER_LOOPS_DIR_NAME = ".qwenpaw/user-loops"

BUILTIN_LOOP = {
    "name": "goal",
    "slash_command": "goal",
    "description": ("Set a goal — agent works until done."),
    "source": "builtin",
}


class LoopCreateRequest(BaseModel):
    """Request body for creating a user loop."""

    name: str
    slash_command: str
    description: str = ""
    skill_prompt: str = ""
    rubric: dict = {}
    state: dict = {}
    doom_loop: dict = {}
    safety: dict = {}
    priority: int = 100


class LoopResponse(BaseModel):
    """Serialized loop info for frontend."""

    name: str
    slash_command: str
    description: str = ""
    source: str = "user"


def _get_user_loops_dir() -> Path:
    """Resolve the user loops directory."""
    from ...constant import WORKING_DIR

    wd = Path(WORKING_DIR)
    loops_dir = wd / USER_LOOPS_DIR_NAME
    loops_dir.mkdir(parents=True, exist_ok=True)
    return loops_dir


def _list_user_loops() -> list[dict[str, Any]]:
    """List all user-defined loop configs."""
    loops_dir = _get_user_loops_dir()
    result = []
    for f in sorted(loops_dir.glob("*.json")):
        try:
            data = json.loads(
                f.read_text(encoding="utf-8"),
            )
            data["source"] = "user"
            result.append(data)
        except Exception as exc:
            logger.warning(
                "Failed to read loop %s: %s",
                f.name,
                exc,
            )
    return result


def _list_plugin_loops() -> list[dict[str, Any]]:
    """List loops registered by plugins."""
    result = []
    try:
        from ...plugins.registry import PluginRegistry

        mgr = PluginRegistry().get_workspace_manager()
        if mgr is None:
            return result
        for ws in getattr(
            mgr,
            "workspaces",
            {},
        ).values():
            plugins = getattr(ws, "plugins", None)
            if plugins is None:
                continue
            for h in getattr(
                plugins,
                "stop_handlers",
                [],
            ):
                meta = getattr(h, "metadata", {})
                if meta.get("loop_name"):
                    result.append(
                        {
                            "name": meta["loop_name"],
                            "slash_command": (
                                meta.get(
                                    "slash_command",
                                    meta["loop_name"],
                                )
                            ),
                            "description": meta.get(
                                "description",
                                "",
                            ),
                            "source": "plugin",
                        },
                    )
    except Exception as exc:
        logger.warning(
            "Failed to list plugin loops: %s",
            exc,
        )
    return result


@router.get("")
async def list_loops() -> list[dict[str, Any]]:
    """List all available loops (builtin + plugin + user)."""
    result = [BUILTIN_LOOP]
    result.extend(_list_plugin_loops())
    result.extend(_list_user_loops())

    seen = set()
    deduped = []
    for loop in result:
        key = loop.get("slash_command", loop["name"])
        if key not in seen:
            seen.add(key)
            deduped.append(loop)
    return deduped


@router.post("")
async def create_loop(
    req: LoopCreateRequest,
) -> dict[str, Any]:
    """Create a user-defined loop."""
    loops_dir = _get_user_loops_dir()
    filepath = loops_dir / f"{req.name}.json"

    if filepath.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Loop '{req.name}' already exists.",
        )

    config = LoopSkillConfig(
        name=req.name,
        slash_command=req.slash_command,
        description=req.description,
        skill_prompt=req.skill_prompt,
        rubric=req.rubric,
        state=req.state,
        doom_loop=req.doom_loop,
        safety=req.safety,
        priority=req.priority,
    )

    filepath.write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )

    _register_user_loop(config)

    return {
        "status": "created",
        "name": req.name,
        "slash_command": req.slash_command,
    }


@router.put("/{name}")
async def update_loop(
    name: str,
    req: LoopCreateRequest,
) -> dict[str, Any]:
    """Update a user-defined loop."""
    loops_dir = _get_user_loops_dir()
    filepath = loops_dir / f"{name}.json"

    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Loop '{name}' not found.",
        )

    config = LoopSkillConfig(
        name=req.name,
        slash_command=req.slash_command,
        description=req.description,
        skill_prompt=req.skill_prompt,
        rubric=req.rubric,
        state=req.state,
        doom_loop=req.doom_loop,
        safety=req.safety,
        priority=req.priority,
    )

    filepath.write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return {
        "status": "updated",
        "name": req.name,
    }


@router.delete("/{name}")
async def delete_loop(name: str) -> dict[str, str]:
    """Delete a user-defined loop."""
    loops_dir = _get_user_loops_dir()
    filepath = loops_dir / f"{name}.json"

    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Loop '{name}' not found.",
        )

    filepath.unlink()
    return {"status": "deleted", "name": name}


def _register_user_loop(
    config: LoopSkillConfig,
) -> None:
    """Register a user loop into the running system."""
    try:
        from ...plugins.registry import PluginRegistry

        reg = PluginRegistry()
        mgr = reg.get_workspace_manager()
        if mgr is None:
            return

        from ...plugins.api import PluginApi
        from ...loop.loader import LoopLoader

        api = PluginApi(
            plugin_id=f"user-loop-{config.name}",
            config={},
        )
        loader = LoopLoader(api)
        loader.load_from_dict(
            config.model_dump(),
        )
    except Exception as exc:
        logger.warning(
            "Failed to register user loop '%s': %s",
            config.name,
            exc,
        )


def load_user_loops_on_startup() -> None:
    """Load all user-defined loops from disk on startup."""
    loops_dir = _get_user_loops_dir()
    count = 0
    for f in sorted(loops_dir.glob("*.json")):
        try:
            data = json.loads(
                f.read_text(encoding="utf-8"),
            )
            config = LoopSkillConfig(**data)
            _register_user_loop(config)
            count += 1
        except Exception as exc:
            logger.warning(
                "Failed to load user loop %s: %s",
                f.name,
                exc,
            )
    if count > 0:
        logger.info(
            "Loaded %d user-defined loop(s)",
            count,
        )
