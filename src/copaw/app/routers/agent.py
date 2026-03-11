# -*- coding: utf-8 -*-
"""Agent file management API."""

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from ...config import (
    load_config,
    save_config,
    AgentsRunningConfig,
)

from ...agents.memory.agent_md_manager import AGENT_MD_MANAGER

router = APIRouter(prefix="/agent", tags=["agent"])


class MdFileInfo(BaseModel):
    """Markdown file metadata."""

    filename: str = Field(..., description="File name")
    path: str = Field(..., description="File path")
    size: int = Field(..., description="Size in bytes")
    created_time: str = Field(..., description="Created time")
    modified_time: str = Field(..., description="Modified time")


class MdFileContent(BaseModel):
    """Markdown file content."""

    content: str = Field(..., description="File content")


@router.get(
    "/files",
    response_model=list[MdFileInfo],
    summary="List working files",
    description="List all working files",
)
async def list_working_files() -> list[MdFileInfo]:
    """List working directory markdown files."""
    try:
        files = [
            MdFileInfo.model_validate(file)
            for file in AGENT_MD_MANAGER.list_working_mds()
        ]
        return files
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/files/{md_name}",
    response_model=MdFileContent,
    summary="Read a working file",
    description="Read a working markdown file",
)
async def read_working_file(
    md_name: str,
) -> MdFileContent:
    """Read a working directory markdown file."""
    try:
        content = AGENT_MD_MANAGER.read_working_md(md_name)
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "/files/{md_name}",
    response_model=dict,
    summary="Write a working file",
    description="Create or update a working file",
)
async def write_working_file(
    md_name: str,
    request: MdFileContent,
) -> dict:
    """Write a working directory markdown file."""
    try:
        AGENT_MD_MANAGER.write_working_md(md_name, request.content)
        return {"written": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/memory",
    response_model=list[MdFileInfo],
    summary="List memory files",
    description="List all memory files",
)
async def list_memory_files() -> list[MdFileInfo]:
    """List memory directory markdown files."""
    try:
        files = [
            MdFileInfo.model_validate(file)
            for file in AGENT_MD_MANAGER.list_memory_mds()
        ]
        return files
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/memory/{md_name}",
    response_model=MdFileContent,
    summary="Read a memory file",
    description="Read a memory markdown file",
)
async def read_memory_file(
    md_name: str,
) -> MdFileContent:
    """Read a memory directory markdown file."""
    try:
        content = AGENT_MD_MANAGER.read_memory_md(md_name)
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "/memory/{md_name}",
    response_model=dict,
    summary="Write a memory file",
    description="Create or update a memory file",
)
async def write_memory_file(
    md_name: str,
    request: MdFileContent,
) -> dict:
    """Write a memory directory markdown file."""
    try:
        AGENT_MD_MANAGER.write_memory_md(md_name, request.content)
        return {"written": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/running-config",
    response_model=AgentsRunningConfig,
    summary="Get agent running config",
    description="Retrieve agent runtime behavior configuration",
)
async def get_agents_running_config() -> AgentsRunningConfig:
    """Get agent running configuration."""
    config = load_config()
    return config.agents.running


@router.put(
    "/running-config",
    response_model=AgentsRunningConfig,
    summary="Update agent running config",
    description="Update agent runtime behavior configuration",
)
async def put_agents_running_config(
    running_config: AgentsRunningConfig = Body(
        ...,
        description="Updated agent running configuration",
    ),
) -> AgentsRunningConfig:
    """Update agent running configuration."""
    config = load_config()
    config.agents.running = running_config
    save_config(config)
    return running_config


@router.get(
    "/system-prompt-files",
    response_model=list[str],
    summary="Get system prompt files",
    description="Get list of markdown files enabled for system prompt",
)
async def get_system_prompt_files() -> list[str]:
    """Get list of enabled system prompt files."""
    config = load_config()
    return config.agents.system_prompt_files


@router.put(
    "/system-prompt-files",
    response_model=list[str],
    summary="Update system prompt files",
    description="Update list of markdown files enabled for system prompt",
)
async def put_system_prompt_files(
    files: list[str] = Body(
        ...,
        description="List of markdown filenames to load into system prompt",
    ),
) -> list[str]:
    """Update list of enabled system prompt files."""
    config = load_config()
    config.agents.system_prompt_files = files
    save_config(config)
    return files
