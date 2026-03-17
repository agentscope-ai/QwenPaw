# -*- coding: utf-8 -*-
"""Agent file management API."""

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from ...config import (
    load_config,
    save_config,
    AgentsRunningConfig,
)
from ...knowledge.module_skills import sync_knowledge_module_skills

from ...agents.memory.agent_md_manager import AGENT_MD_MANAGER

router = APIRouter(prefix="/agent", tags=["agent"])


def _migrate_knowledge_automation_to_running(config) -> bool:
    """Compat: migrate deprecated knowledge.automation to agents.running."""
    changed = False
    defaults = AgentsRunningConfig()
    running = config.agents.running
    legacy = getattr(config.knowledge, "automation", None)
    if legacy is None:
        return False

    if (
        running.knowledge_enabled == defaults.knowledge_enabled
        and config.knowledge.enabled != defaults.knowledge_enabled
    ):
        running.knowledge_enabled = config.knowledge.enabled
        changed = True

    if (
        running.knowledge_auto_collect_chat_files == defaults.knowledge_auto_collect_chat_files
        and legacy.knowledge_auto_collect_chat_files != defaults.knowledge_auto_collect_chat_files
    ):
        running.knowledge_auto_collect_chat_files = legacy.knowledge_auto_collect_chat_files
        changed = True

    if (
        running.knowledge_auto_collect_chat_urls == defaults.knowledge_auto_collect_chat_urls
        and legacy.knowledge_auto_collect_chat_urls != defaults.knowledge_auto_collect_chat_urls
    ):
        running.knowledge_auto_collect_chat_urls = legacy.knowledge_auto_collect_chat_urls
        changed = True

    if (
        running.knowledge_auto_collect_long_text == defaults.knowledge_auto_collect_long_text
        and legacy.knowledge_auto_collect_long_text != defaults.knowledge_auto_collect_long_text
    ):
        running.knowledge_auto_collect_long_text = legacy.knowledge_auto_collect_long_text
        changed = True

    if (
        running.knowledge_long_text_min_chars == defaults.knowledge_long_text_min_chars
        and legacy.knowledge_long_text_min_chars != defaults.knowledge_long_text_min_chars
    ):
        running.knowledge_long_text_min_chars = legacy.knowledge_long_text_min_chars
        changed = True

    knowledge_index = getattr(config.knowledge, "index", None)
    if (
        knowledge_index is not None
        and running.knowledge_chunk_size == defaults.knowledge_chunk_size
        and knowledge_index.chunk_size != defaults.knowledge_chunk_size
    ):
        running.knowledge_chunk_size = knowledge_index.chunk_size
        changed = True

    return changed


def _sync_running_to_knowledge_automation(config) -> None:
    """Compat: keep deprecated knowledge.automation in sync."""
    legacy = getattr(config.knowledge, "automation", None)
    if legacy is None:
        return
    running = config.agents.running
    config.knowledge.enabled = running.knowledge_enabled
    legacy.knowledge_auto_collect_chat_files = running.knowledge_auto_collect_chat_files
    legacy.knowledge_auto_collect_chat_urls = running.knowledge_auto_collect_chat_urls
    legacy.knowledge_auto_collect_long_text = running.knowledge_auto_collect_long_text
    legacy.knowledge_long_text_min_chars = running.knowledge_long_text_min_chars
    config.knowledge.index.chunk_size = running.knowledge_chunk_size


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
    "/language",
    summary="Get agent language",
    description="Get the language setting for agent MD files (en/zh/ru)",
)
async def get_agent_language() -> dict:
    """Get agent language setting."""
    config = load_config()
    return {"language": config.agents.language}


@router.put(
    "/language",
    summary="Update agent language",
    description=(
        "Update the language for agent MD files (en/zh/ru). "
        "Optionally copies MD files for the new language."
    ),
)
async def put_agent_language(
    body: dict = Body(
        ...,
        description='Language setting, e.g. {"language": "zh"}',
    ),
) -> dict:
    """Update agent language and optionally re-copy MD files."""
    language = (body.get("language") or "").strip().lower()
    valid = {"zh", "en", "ru"}
    if language not in valid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid language '{language}'. "
                f"Must be one of: {', '.join(sorted(valid))}"
            ),
        )
    config = load_config()
    old_language = config.agents.language
    config.agents.language = language
    save_config(config)

    copied_files: list[str] = []
    if old_language != language:
        from ...agents.utils import copy_md_files

        copied_files = copy_md_files(language) or []
        if copied_files:
            config = load_config()
            config.agents.installed_md_files_language = language
            save_config(config)

    return {
        "language": language,
        "copied_files": copied_files,
    }


@router.get(
    "/running-config",
    response_model=AgentsRunningConfig,
    summary="Get agent running config",
    description="Retrieve agent runtime behavior configuration",
)
async def get_agents_running_config() -> AgentsRunningConfig:
    """Get agent running configuration."""
    config = load_config()
    if _migrate_knowledge_automation_to_running(config):
        _sync_running_to_knowledge_automation(config)
        save_config(config)
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
    previous_enabled = bool(getattr(config.agents.running, "knowledge_enabled", True))
    config.agents.running = running_config
    _sync_running_to_knowledge_automation(config)
    if previous_enabled != running_config.knowledge_enabled:
        sync_knowledge_module_skills(running_config.knowledge_enabled)
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
