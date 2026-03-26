# -*- coding: utf-8 -*-
"""Multi-agent management API.

Provides RESTful API for managing multiple agent instances.
"""
import json
import logging
import shutil
from pathlib import Path
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, field_validator

from ..utils import schedule_agent_reload
from ...config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    load_agent_config,
    save_agent_config,
    generate_short_agent_id,
)
from ...config.utils import load_config, save_config
from ...agents.memory.agent_md_manager import AgentMdManager
from ...agents.skills_manager import (
    prune_active_skills,
    sync_skills_to_working_dir,
)
from ...agents.utils import copy_builtin_qa_md_files
from ..multi_agent_manager import MultiAgentManager
from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentSummary(BaseModel):
    """Agent summary information."""

    id: str
    name: str
    description: str
    workspace_dir: str
    enabled: bool


class AgentListResponse(BaseModel):
    """Response for listing agents."""

    agents: list[AgentSummary]


class CreateAgentRequest(BaseModel):
    """Request model for creating a new agent (id is auto-generated)."""

    name: str
    description: str = ""
    workspace_dir: str | None = None
    language: str = "en"

    @field_validator("workspace_dir", mode="before")
    @classmethod
    def strip_workspace_dir(cls, value: str | None) -> str | None:
        """Strip accidental whitespace"""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value


class MdFileInfo(BaseModel):
    """Markdown file metadata."""

    filename: str
    path: str
    size: int
    created_time: str
    modified_time: str


class MdFileContent(BaseModel):
    """Markdown file content."""

    content: str


def _get_multi_agent_manager(request: Request) -> MultiAgentManager:
    """Get MultiAgentManager from app state."""
    if not hasattr(request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    return request.app.state.multi_agent_manager


def _read_profile_description(workspace_dir: str) -> str:
    """Read description from PROFILE.md if exists.

    Extracts identity section from PROFILE.md as fallback description.

    Args:
        workspace_dir: Path to agent workspace

    Returns:
        Description text from PROFILE.md, or empty string if not found
    """
    try:
        profile_path = Path(workspace_dir) / "PROFILE.md"
        if not profile_path.exists():
            return ""

        content = profile_path.read_text(encoding="utf-8")
        lines = []
        in_identity = False

        for line in content.split("\n"):
            if line.strip().startswith("## 身份") or line.strip().startswith(
                "## Identity",
            ):
                in_identity = True
                continue
            if in_identity:
                if line.strip().startswith("##"):
                    break
                if line.strip() and not line.strip().startswith("#"):
                    lines.append(line.strip())

        return " ".join(lines)[:200] if lines else ""
    except Exception:  # noqa: E722
        return ""


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List all agents",
    description="Get list of all configured agents",
)
async def list_agents() -> AgentListResponse:
    """List all configured agents."""
    config = load_config()

    agents = []
    for agent_id, agent_ref in config.agents.profiles.items():
        # Load agent config to get name and description
        try:
            agent_config = load_agent_config(agent_id)
            description = agent_config.description or ""

            # Always read PROFILE.md and append/merge
            profile_desc = _read_profile_description(agent_ref.workspace_dir)
            if profile_desc:
                if description.strip():
                    # Both exist: merge with separator
                    description = f"{description.strip()} | {profile_desc}"
                else:
                    # Only PROFILE.md exists
                    description = profile_desc

            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_config.name,
                    description=description,
                    workspace_dir=agent_ref.workspace_dir,
                    enabled=getattr(agent_ref, "enabled", True),
                ),
            )
        except Exception:  # noqa: E722
            # If agent config load fails, use basic info
            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_id.title(),
                    description="",
                    workspace_dir=agent_ref.workspace_dir,
                    enabled=getattr(agent_ref, "enabled", True),
                ),
            )

    return AgentListResponse(
        agents=agents,
    )


@router.get(
    "/{agentId}",
    response_model=AgentProfileConfig,
    summary="Get agent details",
    description="Get complete configuration for a specific agent",
)
async def get_agent(agentId: str = PathParam(...)) -> AgentProfileConfig:
    """Get agent configuration."""
    try:
        agent_config = load_agent_config(agentId)
        return agent_config
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "",
    response_model=AgentProfileRef,
    status_code=201,
    summary="Create new agent",
    description="Create a new agent (ID is auto-generated by server)",
)
async def create_agent(
    request: CreateAgentRequest = Body(...),
) -> AgentProfileRef:
    """Create a new agent with auto-generated ID."""
    config = load_config()

    # Always generate a unique short UUID (6 characters)
    max_attempts = 10
    new_id = None
    for _ in range(max_attempts):
        candidate_id = generate_short_agent_id()
        if candidate_id not in config.agents.profiles:
            new_id = candidate_id
            break

    if new_id is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate unique agent ID after 10 attempts",
        )

    # Create workspace directory
    workspace_dir = Path(
        request.workspace_dir or f"{WORKING_DIR}/workspaces/{new_id}",
    ).expanduser()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Build complete agent config with generated ID
    from ...config.config import (
        ChannelConfig,
        MCPConfig,
        HeartbeatConfig,
        ToolsConfig,
    )

    agent_config = AgentProfileConfig(
        id=new_id,
        name=request.name,
        description=request.description,
        workspace_dir=str(workspace_dir),
        language=request.language,
        channels=ChannelConfig(),
        mcp=MCPConfig(),
        heartbeat=HeartbeatConfig(),
        tools=ToolsConfig(),
    )

    # Initialize workspace with default files
    _initialize_agent_workspace(workspace_dir, agent_config)

    # Save agent configuration to workspace/agent.json
    agent_ref = AgentProfileRef(
        id=new_id,
        workspace_dir=str(workspace_dir),
        enabled=True,
    )

    # Add to root config
    config.agents.profiles[new_id] = agent_ref
    save_config(config)

    # Save agent config to workspace
    save_agent_config(new_id, agent_config)

    logger.info(f"Created new agent: {new_id} (name={request.name})")

    return agent_ref


@router.put(
    "/{agentId}",
    response_model=AgentProfileConfig,
    summary="Update agent",
    description="Update agent configuration and trigger reload",
)
async def update_agent(
    agentId: str = PathParam(...),
    agent_config: AgentProfileConfig = Body(...),
    request: Request = None,
) -> AgentProfileConfig:
    """Update agent configuration."""
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    # Load existing complete configuration
    existing_config = load_agent_config(agentId)

    # Merge updates: only update fields that are explicitly set
    update_data = agent_config.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key != "id":
            setattr(existing_config, key, value)

    # Ensure ID doesn't change
    existing_config.id = agentId

    # Save merged configuration
    save_agent_config(agentId, existing_config)

    # Trigger hot reload if agent is running (async, non-blocking)
    schedule_agent_reload(request, agentId)

    return agent_config


@router.delete(
    "/{agentId}",
    summary="Delete agent",
    description="Delete agent and workspace (cannot delete default agent)",
)
async def delete_agent(
    agentId: str = PathParam(...),
    request: Request = None,
) -> dict:
    """Delete an agent."""
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    if agentId == "default":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the default agent",
        )

    # Stop agent instance if running
    manager = _get_multi_agent_manager(request)
    await manager.stop_agent(agentId)

    # Remove from config
    del config.agents.profiles[agentId]
    save_config(config)

    # Note: We don't delete the workspace directory for safety
    # Users can manually delete it if needed

    return {"success": True, "agent_id": agentId}


@router.patch(
    "/{agentId}/toggle",
    summary="Toggle agent enabled state",
    description="Enable or disable an agent (cannot disable default agent)",
)
async def toggle_agent_enabled(
    agentId: str = PathParam(...),
    enabled: bool = Body(..., embed=True),
    request: Request = None,
) -> dict:
    """Toggle agent enabled state.

    When disabling an agent:
    1. Stop the agent instance if running
    2. Update enabled field in config.json

    When enabling an agent:
    1. Update enabled field in config.json
    2. Agent will be started immediately
    """
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    if agentId == "default":
        raise HTTPException(
            status_code=400,
            detail="Cannot disable the default agent",
        )

    agent_ref = config.agents.profiles[agentId]
    manager = _get_multi_agent_manager(request)

    # If disabling, stop the agent instance
    if not enabled and getattr(agent_ref, "enabled", True):
        await manager.stop_agent(agentId)

    # Update enabled status
    agent_ref.enabled = enabled
    save_config(config)

    # If enabling, start the agent instance immediately
    if enabled:
        try:
            await manager.get_agent(agentId)
            logger.info(f"Agent {agentId} started successfully")
        except Exception as e:
            logger.error(f"Failed to start agent {agentId}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Agent enabled but failed to start: {str(e)}",
            ) from e

    return {
        "success": True,
        "agent_id": agentId,
        "enabled": enabled,
    }


@router.get(
    "/{agentId}/files",
    response_model=list[MdFileInfo],
    summary="List agent workspace files",
    description="List all markdown files in agent's workspace",
)
async def list_agent_files(
    agentId: str = PathParam(...),
    request: Request = None,
) -> list[MdFileInfo]:
    """List agent workspace files."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    workspace_manager = AgentMdManager(str(workspace.workspace_dir))

    try:
        files = [
            MdFileInfo.model_validate(file)
            for file in workspace_manager.list_working_mds()
        ]
        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/{agentId}/files/{filename}",
    response_model=MdFileContent,
    summary="Read agent workspace file",
    description="Read a markdown file from agent's workspace",
)
async def read_agent_file(
    agentId: str = PathParam(...),
    filename: str = PathParam(...),
    request: Request = None,
) -> MdFileContent:
    """Read agent workspace file."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    workspace_manager = AgentMdManager(str(workspace.workspace_dir))

    try:
        content = workspace_manager.read_working_md(filename)
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"File '{filename}' not found",
        ) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put(
    "/{agentId}/files/{filename}",
    response_model=dict,
    summary="Write agent workspace file",
    description="Create or update a markdown file in agent's workspace",
)
async def write_agent_file(
    agentId: str = PathParam(...),
    filename: str = PathParam(...),
    file_content: MdFileContent = Body(...),
    request: Request = None,
) -> dict:
    """Write agent workspace file."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    workspace_manager = AgentMdManager(str(workspace.workspace_dir))

    try:
        workspace_manager.write_working_md(filename, file_content.content)
        return {"written": True, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/{agentId}/memory",
    response_model=list[MdFileInfo],
    summary="List agent memory files",
    description="List all memory files for an agent",
)
async def list_agent_memory(
    agentId: str = PathParam(...),
    request: Request = None,
) -> list[MdFileInfo]:
    """List agent memory files."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    workspace_manager = AgentMdManager(str(workspace.workspace_dir))

    try:
        files = [
            MdFileInfo.model_validate(file)
            for file in workspace_manager.list_memory_mds()
        ]
        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _ensure_default_heartbeat_md(workspace_dir: Path, language: str) -> None:
    """Write a default HEARTBEAT.md when the workspace has none."""
    heartbeat_file = workspace_dir / "HEARTBEAT.md"
    if heartbeat_file.exists():
        return
    default_by_lang = {
        "zh": """# Heartbeat checklist
- 扫描收件箱紧急邮件
- 查看未来 2h 的日历
- 检查待办是否卡住
- 若安静超过 8h，轻量 check-in
""",
        "en": """# Heartbeat checklist
- Scan inbox for urgent email
- Check calendar for next 2h
- Check tasks for blockers
- Light check-in if quiet for 8h
""",
        "ru": """# Heartbeat checklist
- Проверить входящие на срочные письма
- Просмотреть календарь на ближайшие 2 часа
- Проверить задачи на наличие блокировок
- Лёгкая проверка при отсутствии активности более 8 часов
""",
    }
    content = default_by_lang.get(language, default_by_lang["en"])
    with open(heartbeat_file, "w", encoding="utf-8") as f:
        f.write(content.strip())


def _initialize_agent_workspace(  # pylint: disable=too-many-branches
    workspace_dir: Path,
    agent_config: AgentProfileConfig,  # pylint: disable=unused-argument
    *,
    active_skill_names: list[str] | None = None,
    builtin_qa_md_seed: bool = False,
) -> None:
    """Initialize agent workspace (similar to copaw init --defaults).

    Args:
        workspace_dir: Path to agent workspace
        agent_config: Agent configuration (reserved for future use)
        active_skill_names: If set, only these skills are synced to
            ``active_skills``; others are removed. If ``None``, copy all
            builtin skills when missing (default for new agents).
        builtin_qa_md_seed: If True, seed the builtin QA persona from
            ``md_files/qa/<lang>/`` (AGENTS, PROFILE, SOUL), copy MEMORY and
            HEARTBEAT from the normal language pack, and **omit** BOOTSTRAP.md
            so bootstrap mode never triggers.
    """
    from ...config import load_config as load_global_config

    workspace_dir = Path(workspace_dir).expanduser()

    # Create essential subdirectories
    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    (workspace_dir / "active_skills").mkdir(exist_ok=True)
    (workspace_dir / "customized_skills").mkdir(exist_ok=True)

    # Get language from global config
    config = load_global_config()
    language = config.agents.language or "zh"

    package_agents_root = Path(__file__).parent.parent.parent / "agents"
    md_files_dir = package_agents_root / "md_files" / language

    if builtin_qa_md_seed:
        copy_builtin_qa_md_files(
            language,
            workspace_dir,
            only_if_missing=True,
        )
    elif md_files_dir.exists():
        for md_file in md_files_dir.glob("*.md"):
            target_file = workspace_dir / md_file.name
            if not target_file.exists():
                try:
                    shutil.copy2(md_file, target_file)
                except Exception as e:
                    logger.warning(
                        f"Failed to copy {md_file.name}: {e}",
                    )

    _ensure_default_heartbeat_md(workspace_dir, language)

    builtin_skills_dir = package_agents_root / "skills"
    if active_skill_names is not None:
        synced, skipped = sync_skills_to_working_dir(
            workspace_dir,
            skill_names=active_skill_names,
            force=True,
        )
        logger.debug(
            "Synced skills for %s: synced=%s skipped=%s names=%s",
            workspace_dir,
            synced,
            skipped,
            active_skill_names,
        )
        prune_active_skills(workspace_dir, set(active_skill_names))
    elif builtin_skills_dir.exists():
        for skill_dir in builtin_skills_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                target_skill_dir = (
                    workspace_dir / "active_skills" / skill_dir.name
                )
                if not target_skill_dir.exists():
                    try:
                        shutil.copytree(skill_dir, target_skill_dir)
                    except Exception as e:
                        logger.warning(
                            f"Failed to copy skill {skill_dir.name}: {e}",
                        )

    # Create empty jobs.json for cron jobs
    jobs_file = workspace_dir / "jobs.json"
    if not jobs_file.exists():
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 1, "jobs": []},
                f,
                ensure_ascii=False,
                indent=2,
            )

    # Create empty chats.json for chat history
    chats_file = workspace_dir / "chats.json"
    if not chats_file.exists():
        with open(chats_file, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 1, "chats": []},
                f,
                ensure_ascii=False,
                indent=2,
            )

    # Create empty token_usage.json
    token_usage_file = workspace_dir / "token_usage.json"
    if not token_usage_file.exists():
        with open(token_usage_file, "w", encoding="utf-8") as f:
            f.write("[]")
