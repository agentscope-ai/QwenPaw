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

from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from ...agents.utils.file_handling import read_text_file_with_encoding_fallback
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
from ...agents.utils import copy_builtin_qa_md_files
from ...agents.skills_manager import SkillPoolService, get_workspace_skills_dir
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


class ReorderAgentsRequest(BaseModel):
    """Request model for persisting agent order."""

    agent_ids: list[str]


class CreateAgentRequest(BaseModel):
    """Request model for creating a new agent (id is auto-generated)."""

    name: str
    description: str = ""
    workspace_dir: str | None = None
    language: str = "en"
    skill_names: list[str] | None = None

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


def _normalized_agent_order(config) -> list[str]:
    """Return a deduplicated agent order covering every configured agent."""
    profile_ids = list(config.agents.profiles.keys())
    ordered_ids: list[str] = []

    for agent_id in config.agents.agent_order:
        if agent_id in config.agents.profiles and agent_id not in ordered_ids:
            ordered_ids.append(agent_id)

    for agent_id in profile_ids:
        if agent_id not in ordered_ids:
            ordered_ids.append(agent_id)

    return ordered_ids


def _read_profile_description(workspace_dir: str) -> str:
    """Read description from PROFILE.md if exists."""
    try:
        profile_path = Path(workspace_dir) / "PROFILE.md"
        if not profile_path.exists():
            return ""

        content = read_text_file_with_encoding_fallback(profile_path).strip()
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
    ordered_agent_ids = _normalized_agent_order(config)

    agents = []
    for agent_id in ordered_agent_ids:
        agent_ref = config.agents.profiles[agent_id]
        try:
            agent_config = load_agent_config(agent_id)
            description = agent_config.description or ""

            profile_desc = _read_profile_description(agent_ref.workspace_dir)
            if profile_desc:
                if description.strip():
                    description = f"{description.strip()} | {profile_desc}"
                else:
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
            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_id.title(),
                    description="",
                    workspace_dir=agent_ref.workspace_dir,
                    enabled=getattr(agent_ref, "enabled", True),
                ),
            )

    return AgentListResponse(agents=agents)


@router.put(
    "/order",
    summary="Persist agent order",
    description="Save the full ordered list of configured agent IDs",
)
async def reorder_agents(
    reorder_request: ReorderAgentsRequest = Body(...),
) -> dict:
    """Persist the full ordered list of agent IDs."""
    config = load_config()
    configured_ids = list(config.agents.profiles.keys())

    if len(reorder_request.agent_ids) != len(set(reorder_request.agent_ids)):
        raise HTTPException(
            status_code=400,
            detail="Each configured agent ID must appear exactly once.",
        )

    if set(reorder_request.agent_ids) != set(configured_ids):
        raise HTTPException(
            status_code=400,
            detail="Each configured agent ID must appear exactly once.",
        )

    config.agents.agent_order = list(reorder_request.agent_ids)
    save_config(config)

    return {"success": True, "agent_ids": config.agents.agent_order}


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
    except (ValueError, AppBaseException) as e:
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

    workspace_dir = Path(
        request.workspace_dir or f"{WORKING_DIR}/workspaces/{new_id}",
    ).expanduser()
    workspace_dir.mkdir(parents=True, exist_ok=True)

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

    _initialize_agent_workspace(
        workspace_dir,
        skill_names=(
            request.skill_names if request.skill_names is not None else []
        ),
    )

    agent_ref = AgentProfileRef(
        id=new_id,
        workspace_dir=str(workspace_dir),
        enabled=True,
    )

    config.agents.profiles[new_id] = agent_ref
    config.agents.agent_order = _normalized_agent_order(config)
    save_config(config)
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

    existing_config = load_agent_config(agentId)

    update_data = agent_config.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key != "id":
            setattr(existing_config, key, value)

    existing_config.id = agentId
    save_agent_config(agentId, existing_config)
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

    manager = _get_multi_agent_manager(request)
    await manager.stop_agent(agentId)

    del config.agents.profiles[agentId]
    config.agents.agent_order = _normalized_agent_order(config)
    save_config(config)

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
    """Toggle agent enabled state."""
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

    if not enabled and getattr(agent_ref, "enabled", True):
        await manager.stop_agent(agentId)

    agent_ref.enabled = enabled
    save_config(config)

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
    except (ValueError, AppBaseException) as e:
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
    except (ValueError, AppBaseException) as e:
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
    except (ValueError, AppBaseException) as e:
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
    except (ValueError, AppBaseException) as e:
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


def _seed_workspace_md_files(
    workspace_dir: Path,
    language: str,
    *,
    builtin_qa_md_seed: bool,
) -> None:
    """Seed workspace markdown files for a new agent."""
    if builtin_qa_md_seed:
        try:
            copy_builtin_qa_md_files(language, workspace_dir)
        except Exception as e:
            logger.warning("Failed to seed builtin QA md files: %s", e)
        return

    md_files_dir = (
        Path(__file__).parent.parent.parent / "agents" / "md_files" / language
    )
    if not md_files_dir.exists():
        return

    for md_file in md_files_dir.glob("*.md"):
        target_file = workspace_dir / md_file.name
        if target_file.exists():
            continue
        try:
            shutil.copy2(md_file, target_file)
        except Exception as e:
            logger.warning("Failed to copy %s: %s", md_file.name, e)


def _ensure_heartbeat_file(workspace_dir: Path, language: str) -> None:
    """Create the default HEARTBEAT.md if it is missing."""
    heartbeat_file = workspace_dir / "HEARTBEAT.md"
    if heartbeat_file.exists():
        return

    default_heartbeat_mds = {
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
    heartbeat_content = default_heartbeat_mds.get(
        language,
        default_heartbeat_mds["en"],
    )
    with open(heartbeat_file, "w", encoding="utf-8") as file:
        file.write(heartbeat_content.strip())


def _copy_builtin_skills(workspace_dir: Path) -> None:
    """Copy builtin skills into a new workspace when missing."""
    builtin_skills_dir = (
        Path(__file__).parent.parent.parent / "agents" / "skills"
    )
    if not builtin_skills_dir.exists():
        return

    target_skills_dir = get_workspace_skills_dir(workspace_dir)
    target_skills_dir.mkdir(parents=True, exist_ok=True)

    for skill_dir in builtin_skills_dir.iterdir():
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        target_skill_dir = target_skills_dir / skill_dir.name
        if target_skill_dir.exists():
            continue
        try:
            shutil.copytree(skill_dir, target_skill_dir)
        except Exception as e:
            logger.warning("Failed to copy skill %s: %s", skill_dir.name, e)


def _install_initial_skills(
    workspace_dir: Path,
    skill_names: list[str] | None,
) -> None:
    """Install requested initial skills from the skill pool."""
    if not skill_names:
        return

    pool_service = SkillPoolService()
    for skill_name in skill_names:
        try:
            result = pool_service.download_to_workspace(
                skill_name=skill_name,
                workspace_dir=workspace_dir,
                overwrite=False,
            )
            if result.get("success"):
                continue
            logger.warning(
                "Failed to install initial skill %s for %s: %s",
                skill_name,
                workspace_dir,
                result.get("reason", "unknown"),
            )
        except Exception as e:
            logger.warning(
                "Failed to install initial skill %s for %s: %s",
                skill_name,
                workspace_dir,
                e,
            )


def _initialize_agent_workspace(
    workspace_dir: Path,
    skill_names: list[str] | None = None,
    builtin_qa_md_seed: bool = False,
) -> None:
    """Initialize agent workspace (similar to qwenpaw init --defaults)."""
    from ...config import load_config as load_global_config

    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    get_workspace_skills_dir(workspace_dir).mkdir(exist_ok=True)

    config = load_global_config()
    language = config.agents.language or "zh"

    _seed_workspace_md_files(
        workspace_dir,
        language,
        builtin_qa_md_seed=builtin_qa_md_seed,
    )
    _ensure_heartbeat_file(workspace_dir, language)
    _copy_builtin_skills(workspace_dir)
    _install_initial_skills(workspace_dir, skill_names)

    jobs_file = workspace_dir / "jobs.json"
    if not jobs_file.exists():
        with open(jobs_file, "w", encoding="utf-8") as file:
            json.dump(
                {"version": 1, "jobs": []},
                file,
                ensure_ascii=False,
                indent=2,
            )

    chats_file = workspace_dir / "chats.json"
    if not chats_file.exists():
        with open(chats_file, "w", encoding="utf-8") as file:
            json.dump(
                {"version": 1, "chats": []},
                file,
                ensure_ascii=False,
                indent=2,
            )
