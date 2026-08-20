# -*- coding: utf-8 -*-
"""Multi-agent management API.

Provides RESTful API for managing multiple agent instances.
"""

import json
import logging
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, Field, field_validator, model_validator

from qwenpaw.exceptions import (
    AppBaseException,
)

from ...agents.utils.file_handling import read_text_file_with_encoding_fallback
from ..mail.driver_config import (
    ENTERPRISE_MAIL_PROVIDERS as _ENTERPRISE_MAIL_PROVIDERS,
    build_qwenpawmail_env as _build_qwenpawmail_env,
    generate_qwenpawmail_driver_card as _generate_qwenpawmail_driver_card,
    resolve_qwenpawmail_command as _resolve_qwenpawmail_command,
    sync_qwenpawmail_driver_card as _sync_qwenpawmail_driver_card,
)
from ..utils import safe_join, schedule_agent_reload
from ...config.config import (
    AgentMailConfig,
    AgentProfileConfig,
    AgentProfileRef,
    FallbackPolicyConfig,
    ModelSlotConfig,
    load_agent_config,
    mutate_agent_config,
    save_agent_mail_credentials,
    save_agent_config,
    update_agent_config_async,
    generate_short_agent_id,
    sanitize_agent_id,
    validate_agent_id,
)
from ...config.utils import load_config, mutate_config
from ...agents.utils import (
    copy_workspace_md_files,
    ensure_workspace_md_file,
    normalize_agent_language,
)
from ...agents.skill_system import SkillPoolService, get_workspace_skills_dir
from ...harnesses.registry import ProviderCatalogItem, get_provider
from ..agent_startup import AgentStartupStatus
from ..multi_agent_manager import MultiAgentManager
from ...constant import WORKING_DIR
from ...utils.io_utils import run_sync_io, write_json_atomic
from ...utils.logging import sanitize_log_value

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentSummary(BaseModel):
    """Agent summary information."""

    id: str
    name: str
    description: str
    workspace_dir: str
    enabled: bool
    pinned: bool
    startup_status: AgentStartupStatus
    backend: str = "qwenpaw"
    backend_capabilities: dict[str, Any] = Field(default_factory=dict)
    backend_model: str | None = None
    backend_reasoning_effort: str | None = None
    active_model: ModelSlotConfig | None = None
    managed_by_app: str | None = None
    available_in_chat: bool = True


class AgentListResponse(BaseModel):
    """Response for listing agents."""

    agents: list[AgentSummary]


class MemoryGraphNode(BaseModel):
    """One category root, indexed memory file, or unresolved target."""

    id: str
    path: str
    name: str = ""
    description: str = ""
    indexed: bool
    virtual: bool = False
    section: Literal["daily", "digest"] | None = None
    relative_path: str | None = None


class MemoryGraphEdge(BaseModel):
    """One directed wikilink in the memory graph."""

    source: str
    target: str
    target_anchor: str | None = None


class MemoryGraphSnapshot(BaseModel):
    """Complete graph snapshot returned by embedded ReMe."""

    version: Literal[1] = 1
    nodes: list[MemoryGraphNode]
    edges: list[MemoryGraphEdge]


class ReorderAgentsRequest(BaseModel):
    """Request model for persisting agent order."""

    agent_ids: list[str]


class BackendSettingsRequest(BaseModel):
    """Provider-owned settings updated from Chat controls."""

    model: str | None = None
    reasoning_effort: str | None = None


class AgentModelSettingsPatch(BaseModel):
    """Model-routing fields editable from the Chat model selector."""

    fallback_models: list[ModelSlotConfig] | None = None
    fallback_policy: FallbackPolicyConfig | None = None
    subagent_model: ModelSlotConfig | None = None
    thinking_level: (
        Literal[
            "inherit",
            "off",
            "low",
            "medium",
            "high",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def reject_null_non_nullable_fields(self):
        """Reject explicit null for non-null agent model settings."""
        non_nullable_fields = (
            "fallback_models",
            "fallback_policy",
            "thinking_level",
        )
        null_fields = [
            field
            for field in non_nullable_fields
            if field in self.model_fields_set and getattr(self, field) is None
        ]
        if null_fields:
            fields = ", ".join(null_fields)
            raise ValueError(f"Fields cannot be null: {fields}")
        return self


class ReMeComponentMemoryUsage(BaseModel):
    """Estimated memory owned by one ReMe component."""

    bytes: int
    human: str


class MemoryWorkerRuntimeStatus(BaseModel):
    """Sanitized state of the background memory worker."""

    status: Literal["idle", "busy", "stopping", "error"]
    queue_pending: int
    tasks_running: int


class MemoryCaptureTaskStatus(BaseModel):
    """One bounded memory-capture record, newest records returned first.

    Records share the summarize queue used by periodic auto-memory and the
    user-triggered ``/new`` and ``/compact`` commands.
    """

    task_id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    queued_at: str | None = None
    finished_at: str | None = None
    message_count: int = 0
    result: str | None = None
    error: str | None = None


class AutoMemoryRuntimeStatus(BaseModel):
    """Aggregate auto-memory progress without exposing session identity."""

    enabled: bool
    interval: int


class RecentMemoryRuntimeStatus(BaseModel):
    """Latest bounded error summary."""

    last_error: str | None = None


class MemoryRuntimeStatus(BaseModel):
    """Operational state surfaced to the Console."""

    worker: MemoryWorkerRuntimeStatus
    auto_memory: AutoMemoryRuntimeStatus
    tasks: list[MemoryCaptureTaskStatus] = Field(default_factory=list)
    recent: RecentMemoryRuntimeStatus
    reindexing: bool


class ReMeMemoryStatusResponse(BaseModel):
    """Structured memory information returned by ReMe's status job."""

    components: dict[str, dict[str, ReMeComponentMemoryUsage]]
    components_total: str
    process_rss: str
    runtime: MemoryRuntimeStatus


class CreateAgentRequest(BaseModel):
    """Request model for creating a new agent.

    The ``id`` field is optional.  When provided the server uses it as
    the agent identifier (after sanitization); when omitted a random
    short UUID is generated automatically.
    """

    id: str | None = None
    name: str
    description: str = ""
    workspace_dir: str | None = None
    language: str | None = None
    skill_names: list[str] | None = None
    active_model: ModelSlotConfig | None = None
    mail: AgentMailConfig | None = None
    backend: str = "qwenpaw"
    backend_settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", mode="before")
    @classmethod
    def sanitize_id(cls, value: str | None) -> str | None:
        """Strip whitespace from the custom ID."""
        if value is None:
            return None
        if isinstance(value, str):
            sanitized = sanitize_agent_id(value)
            return sanitized if sanitized else None
        return value

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


class CopyAgentRequest(BaseModel):
    """Request model for copying an existing agent's configuration files."""

    name: str | None = None
    copy_agent_json: Literal[True] = True
    copy_md_files: bool = True
    copy_skills: bool = False
    copy_jobs: bool = False


_COPYABLE_MD_FILES = (
    "AGENTS.md",
    "SOUL.md",
    "PROFILE.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
)


def _get_available_third_party_provider(
    backend: str,
) -> ProviderCatalogItem:
    """Resolve an available third-party backend for API mutations."""
    try:
        provider = get_provider(backend)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if provider.coming_soon:
        raise HTTPException(
            status_code=409,
            detail=f"{provider.name} is not available yet",
        )
    return provider


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


def _group_agent_order(config, ordered_ids: list[str]) -> list[str]:
    """Group a complete order by default, pinned, then regular."""
    pinned_ids = [
        agent_id
        for agent_id in ordered_ids
        if agent_id != "default"
        and getattr(config.agents.profiles[agent_id], "pinned", False)
    ]
    regular_ids = [
        agent_id
        for agent_id in ordered_ids
        if agent_id != "default" and agent_id not in pinned_ids
    ]
    default_ids = ["default"] if "default" in ordered_ids else []
    return [*default_ids, *pinned_ids, *regular_ids]


def _display_agent_order(config) -> list[str]:
    """Return stored order grouped by default, pinned, then regular."""
    return _group_agent_order(config, _normalized_agent_order(config))


def _is_valid_display_order(config, agent_ids: list[str]) -> bool:
    """Return whether an order respects default and pinned grouping."""
    return _group_agent_order(config, agent_ids) == agent_ids


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
async def list_agents(request: Request = None) -> AgentListResponse:
    """List all configured agents."""
    config = await run_sync_io(load_config)
    manager = (
        _get_multi_agent_manager(request) if request is not None else None
    )
    ordered_agent_ids = _display_agent_order(config)

    agents = []
    for agent_id in ordered_agent_ids:
        agent_ref = config.agents.profiles[agent_id]
        enabled = getattr(agent_ref, "enabled", True)
        pinned = agent_id == "default" or getattr(
            agent_ref,
            "pinned",
            False,
        )
        startup_status = (
            manager.get_agent_startup_status(agent_id, enabled=enabled)
            if manager is not None
            else (
                AgentStartupStatus.PENDING
                if enabled
                else AgentStartupStatus.DISABLED
            )
        )
        try:
            agent_config = await run_sync_io(load_agent_config, agent_id)
            description = agent_config.description or ""

            profile_desc = await run_sync_io(
                _read_profile_description,
                agent_ref.workspace_dir,
            )
            if profile_desc:
                if description.strip():
                    description = f"{description.strip()} | {profile_desc}"
                else:
                    description = profile_desc

            active_model = agent_config.active_model
            template_id = agent_config.template_id or ""
            managed_by_app = (
                template_id.removeprefix("pawapp:")
                if template_id.startswith("pawapp:")
                else None
            )
            if agent_config.backend == "qwenpaw":
                backend_capabilities = {"workspace_ui": True}
            else:
                try:
                    backend_capabilities = get_provider(
                        agent_config.backend,
                    ).capabilities.model_dump()
                except ValueError:
                    backend_capabilities = {}

            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_config.name,
                    description=description,
                    workspace_dir=agent_ref.workspace_dir,
                    enabled=enabled,
                    pinned=pinned,
                    startup_status=startup_status,
                    backend=agent_config.backend,
                    backend_capabilities=backend_capabilities,
                    backend_model=agent_config.backend_settings.get("model"),
                    backend_reasoning_effort=(
                        agent_config.backend_settings.get(
                            "reasoning_effort",
                        )
                    ),
                    active_model=active_model,
                    managed_by_app=managed_by_app,
                    available_in_chat=managed_by_app is None,
                ),
            )
        except Exception:  # noqa: E722
            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_id.title(),
                    description="",
                    workspace_dir=agent_ref.workspace_dir,
                    enabled=enabled,
                    pinned=pinned,
                    startup_status=startup_status,
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

    def apply_order(config: Any) -> None:
        configured_ids = list(config.agents.profiles.keys())
        agent_ids = reorder_request.agent_ids
        if len(agent_ids) != len(set(agent_ids)):
            raise HTTPException(
                status_code=400,
                detail="Each configured agent ID must appear exactly once.",
            )
        if set(agent_ids) != set(configured_ids):
            raise HTTPException(
                status_code=400,
                detail="Each configured agent ID must appear exactly once.",
            )
        if not _is_valid_display_order(config, agent_ids):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Agent order must keep default first and pinned agents "
                    "before unpinned agents."
                ),
            )
        config.agents.agent_order = list(agent_ids)

    config = await run_sync_io(mutate_config, apply_order)

    return {"success": True, "agent_ids": config.agents.agent_order}


@router.patch(
    "/{agentId}/pin",
    summary="Pin or unpin an agent",
    description="Persist an agent's pinned state in agent selectors",
)
async def set_agent_pinned(
    agentId: str = PathParam(...),
    pinned: bool = Body(..., embed=True),
) -> dict:
    """Persist an agent's pinned state without changing enabled state."""

    def apply_pinned(config: Any) -> None:
        if agentId not in config.agents.profiles:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{agentId}' not found",
            )
        if agentId == "default" and not pinned:
            raise HTTPException(
                status_code=400,
                detail="Cannot unpin the default agent",
            )
        if agentId != "default":
            config.agents.profiles[agentId].pinned = pinned
            config.agents.agent_order = _display_agent_order(config)

    await run_sync_io(mutate_config, apply_pinned)

    return {
        "success": True,
        "agent_id": agentId,
        "pinned": True if agentId == "default" else pinned,
    }


@router.get(
    "/{agentId}",
    response_model=AgentProfileConfig,
    summary="Get agent details",
    description="Get complete configuration for a specific agent",
)
async def get_agent(agentId: str = PathParam(...)) -> AgentProfileConfig:
    """Get agent configuration."""
    try:
        agent_config = await run_sync_io(load_agent_config, agentId)
        return agent_config
    except (ValueError, AppBaseException) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch(
    "/{agentId}/backend-settings",
    response_model=AgentProfileConfig,
    summary="Update third-party backend Chat settings",
)
async def update_backend_settings(
    body: BackendSettingsRequest,
    agentId: str = PathParam(...),
) -> AgentProfileConfig:
    """Persist model controls owned by a third-party agent backend."""
    # PATCH semantics: only fields the caller actually sent may change;
    # a field absent from the request body must survive untouched, and
    # an explicit null clears it.
    values = {field: getattr(body, field) for field in body.model_fields_set}

    def apply_settings(agent_config: AgentProfileConfig) -> None:
        if agent_config.backend == "qwenpaw":
            raise HTTPException(
                status_code=409,
                detail="QwenPaw models use the native model configuration",
            )
        provider = _get_available_third_party_provider(agent_config.backend)
        settings = dict(agent_config.backend_settings)
        if provider.capabilities.model_selection and "model" in values:
            if values["model"]:
                settings["model"] = values["model"]
            else:
                settings.pop("model", None)
        if (
            provider.capabilities.reasoning_effort
            and "reasoning_effort" in values
        ):
            if values["reasoning_effort"]:
                settings["reasoning_effort"] = values["reasoning_effort"]
            else:
                settings.pop("reasoning_effort", None)
        agent_config.backend_settings = settings

    try:
        return await run_sync_io(
            mutate_agent_config,
            agentId,
            apply_settings,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _resolve_custom_workspace_dir(raw_workspace_dir: str) -> Path:
    """Resolve a caller-supplied workspace directory safely.

    Guards against path traversal (the CodeQL uncontrolled-path
    finding): the raw value must not smuggle ``..`` segments, and a
    relative value is anchored to the QwenPaw working directory rather
    than the process CWD.  Any explicit absolute directory is otherwise
    legal -- deployments routinely keep workspaces on /data, /opt, or
    other non-home mounts, so a home/WORKING_DIR whitelist would reject
    previously valid setups.

    Raises:
        HTTPException(400): empty input or traversal segments.
    """
    raw = raw_workspace_dir.strip()
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="workspace_dir must not be empty",
        )
    raw_path = Path(raw)
    if ".." in raw_path.parts:
        raise HTTPException(
            status_code=400,
            detail="workspace_dir must not contain '..' path segments",
        )
    candidate = raw_path.expanduser()
    if not candidate.is_absolute():
        candidate = Path(WORKING_DIR).expanduser() / candidate
    return candidate.resolve()


def _generate_unique_id(existing_ids: set[str]) -> str:
    """Generate a unique random short agent ID.

    Raises:
        HTTPException: If a unique ID could not be generated.
    """
    max_attempts = 10
    for _ in range(max_attempts):
        candidate_id = generate_short_agent_id()
        if candidate_id not in existing_ids:
            return candidate_id
    raise HTTPException(
        status_code=500,
        detail="Failed to generate unique agent ID after 10 attempts",
    )


async def _require_qwenpawmail_driver_card(
    workspace_dir: Path,
    mail: AgentMailConfig,
    operation: str,
) -> None:
    """Generate a usable card before an agent create/copy is committed."""
    try:
        synced = await run_sync_io(
            _sync_qwenpawmail_driver_card,
            workspace_dir,
            mail,
            "qwenpaw",
            force_rewrite=True,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "Failed to prepare qwenpawmail driver during agent %s: %s",
            sanitize_log_value(operation),
            sanitize_log_value(exc),
        )
        synced = False
    if not synced:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Agent {operation} was not committed because the "
                "qwenpawmail driver card could not be generated. Check "
                "workspace permissions and retry."
            ),
        )


async def _rollback_qwenpawmail_update(
    agent_id: str,
    previous_config: AgentProfileConfig,
    workspace_dir: Path,
) -> tuple[bool, bool]:
    """Restore the config/card pair after a failed driver publication."""
    config_restored = True
    driver_restored = True
    try:
        await run_sync_io(save_agent_config, agent_id, previous_config)
    except Exception:  # pylint: disable=broad-except
        config_restored = False
        logger.exception(
            "Failed to roll back agent config after driver sync failure "
            "for %s",
            sanitize_log_value(agent_id),
        )

    if config_restored:
        try:
            driver_restored = await run_sync_io(
                _sync_qwenpawmail_driver_card,
                workspace_dir,
                previous_config.mail,
                previous_config.backend or "qwenpaw",
                force_rewrite=previous_config.mail is not None,
            )
        except Exception:  # pylint: disable=broad-except
            driver_restored = False
            logger.exception(
                "Failed to restore qwenpawmail driver for agent %s",
                sanitize_log_value(agent_id),
            )
    return config_restored, driver_restored


@router.post(
    "",
    response_model=AgentProfileRef,
    status_code=201,
    summary="Create new agent",
    description="Create a new agent with optional custom ID",
)
async def create_agent(
    request: CreateAgentRequest = Body(...),
    http_request: Request = None,
) -> AgentProfileRef:
    """Create a new agent.

    When ``request.id`` is provided, it is used as the agent identifier
    (validated for URL-safe characters, length, reserved words, and
    uniqueness).  Otherwise a random short UUID is generated.
    """
    _validate_mail_backend_compatibility(request.backend, request.mail)
    if request.backend != "qwenpaw":
        _get_available_third_party_provider(request.backend)

    config = await run_sync_io(load_config)
    existing_ids = set(config.agents.profiles.keys())

    if request.mail is not None:
        _validate_mail_config(request.mail)

    if request.id:
        try:
            validate_agent_id(request.id, existing_ids)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e),
            ) from e
        new_id = request.id
    else:
        new_id = _generate_unique_id(existing_ids)

    if request.workspace_dir:
        workspace_dir = await run_sync_io(
            _resolve_custom_workspace_dir,
            request.workspace_dir,
        )
    else:
        workspace_dir = await run_sync_io(
            safe_join,
            Path(f"{WORKING_DIR}/workspaces").expanduser(),
            new_id,
        )
    await run_sync_io(workspace_dir.mkdir, parents=True, exist_ok=True)

    from ...config.config import (
        ChannelConfig,
        MCPConfig,
        HeartbeatConfig,
        ToolsConfig,
    )

    language = normalize_agent_language(
        request.language or config.agents.language or "en",
    )

    active_model = (
        request.active_model if request.backend == "qwenpaw" else None
    )
    if request.backend == "qwenpaw" and (
        not active_model or not active_model.provider_id
    ):
        try:
            from ...providers import ProviderManager

            global_model = ProviderManager.get_instance().get_active_model()
            if global_model and global_model.provider_id:
                active_model = global_model
        except Exception:
            pass

    agent_config = AgentProfileConfig(
        id=new_id,
        name=request.name,
        description=request.description,
        workspace_dir=str(workspace_dir),
        backend=request.backend,
        backend_settings=request.backend_settings,
        language=language,
        channels=ChannelConfig(),
        mcp=MCPConfig(),
        heartbeat=HeartbeatConfig(),
        tools=ToolsConfig(),
        active_model=active_model,
        mail=request.mail,
    )

    await run_sync_io(
        _initialize_agent_workspace,
        workspace_dir,
        skill_names=(
            request.skill_names if request.skill_names is not None else []
        ),
        language=language,
    )

    if request.mail is not None:
        await _require_qwenpawmail_driver_card(
            workspace_dir,
            request.mail,
            "creation",
        )
        await run_sync_io(_ensure_contacts_file, workspace_dir, language)
        await run_sync_io(_ensure_mail_triage_file, workspace_dir, language)

    agent_ref = AgentProfileRef(
        id=new_id,
        workspace_dir=str(workspace_dir),
        enabled=True,
    )

    await run_sync_io(
        _persist_created_agent,
        new_id,
        agent_ref,
        agent_config,
    )

    logger.info(
        f"Created new agent: {sanitize_log_value(new_id)} "
        f"(name={sanitize_log_value(request.name)})",
    )

    if http_request is not None:
        manager = _get_multi_agent_manager(http_request)
        manager.schedule_agent_startup(new_id)

    return agent_ref


def _build_copied_agent_config(
    *,
    source_config: AgentProfileConfig,
    new_id: str,
    new_name: str,
    workspace_dir: Path,
) -> AgentProfileConfig:
    """Derive a new agent config from the parsed source profile."""
    from ...config.config import ChannelConfig

    agent_config = source_config.model_copy(deep=True)
    agent_config.id = new_id
    agent_config.name = new_name
    agent_config.workspace_dir = str(workspace_dir)
    agent_config.channels = ChannelConfig()
    # Mail is only supported for the qwenpaw backend; silently drop it so
    # copies of legacy "third-party backend + mail" profiles stay valid
    # and no qwenpawmail driver card is generated for the new agent.
    if agent_config.backend != "qwenpaw":
        agent_config.mail = None
    return agent_config


def _copy_selected_workspace_files(
    *,
    request: CopyAgentRequest,
    source_workspace: Path,
    workspace_dir: Path,
) -> None:
    """Copy selected whitelist files from source workspace to the new one."""
    if not source_workspace.is_dir():
        return

    if request.copy_md_files:
        for md_name in _COPYABLE_MD_FILES:
            src = source_workspace / md_name
            if src.is_file():
                shutil.copy2(src, workspace_dir / md_name)

    if request.copy_skills:
        src_skills = get_workspace_skills_dir(source_workspace)
        dst_skills = get_workspace_skills_dir(workspace_dir)
        if src_skills.is_dir():
            # Dest may already exist when create_skills_dir scaffolding ran.
            shutil.copytree(src_skills, dst_skills, dirs_exist_ok=True)
        src_manifest = source_workspace / "skill.json"
        if src_manifest.is_file():
            shutil.copy2(src_manifest, workspace_dir / "skill.json")

    if request.copy_jobs:
        src_jobs = source_workspace / "jobs.json"
        if src_jobs.is_file():
            shutil.copy2(src_jobs, workspace_dir / "jobs.json")


def _prepare_copied_workspace(
    request: CopyAgentRequest,
    source_workspace: Path,
    workspace_dir: Path,
    language: str,
) -> None:
    """Initialize and copy a new agent workspace synchronously."""
    _initialize_agent_workspace(
        workspace_dir,
        skill_names=[],
        language=language,
        apply_md_templates=request.copy_md_files,
        create_skills_dir=request.copy_skills,
        create_jobs_file=request.copy_jobs,
    )
    _copy_selected_workspace_files(
        request=request,
        source_workspace=source_workspace,
        workspace_dir=workspace_dir,
    )


def _persist_created_agent(
    agent_id: str,
    agent_ref: AgentProfileRef,
    agent_config: AgentProfileConfig,
) -> None:
    """Register a new agent under the root-config transaction lock."""

    def register_agent(config: Any) -> None:
        if agent_id in config.agents.profiles:
            raise HTTPException(
                status_code=400,
                detail=f"Agent ID '{agent_id}' already exists",
            )
        agent_path = Path(agent_ref.workspace_dir).expanduser() / "agent.json"
        if agent_config.mail is not None:
            save_agent_mail_credentials(agent_path.parent, agent_config.mail)
        write_json_atomic(
            agent_path,
            agent_config.model_dump(exclude_none=True),
        )
        config.agents.profiles[agent_id] = agent_ref
        config.agents.agent_order = _normalized_agent_order(config)

    mutate_config(register_agent)


@router.post(
    "/{agentId}/copy",
    response_model=AgentProfileRef,
    status_code=201,
    summary="Copy agent configuration",
    description=(
        "Copy selected configuration files from an existing agent into a new "
        "agent. Does not copy sessions, chats, media, or other runtime assets."
    ),
)
async def copy_agent(
    agentId: str = PathParam(...),
    request: CopyAgentRequest = Body(...),
    http_request: Request = None,
) -> AgentProfileRef:
    """Copy selected agent config files into a newly created agent."""
    config = await run_sync_io(load_config)

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    try:
        source_config = await run_sync_io(load_agent_config, agentId)
    except (ValueError, AppBaseException) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    source_workspace = Path(
        config.agents.profiles[agentId].workspace_dir,
    ).expanduser()

    existing_ids = set(config.agents.profiles.keys())
    new_id = _generate_unique_id(existing_ids)
    new_name = (request.name or "").strip() or f"{source_config.name} Copy"
    workspace_dir = Path(f"{WORKING_DIR}/workspaces/{new_id}").expanduser()
    await run_sync_io(workspace_dir.mkdir, parents=True, exist_ok=True)

    language = normalize_agent_language(
        source_config.language or config.agents.language or "en",
    )

    agent_config = _build_copied_agent_config(
        source_config=source_config,
        new_id=new_id,
        new_name=new_name,
        workspace_dir=workspace_dir,
    )

    await run_sync_io(
        _prepare_copied_workspace,
        request,
        source_workspace,
        workspace_dir,
        language,
    )

    if agent_config.mail is not None:
        await _require_qwenpawmail_driver_card(
            workspace_dir,
            agent_config.mail,
            "copy",
        )
        await run_sync_io(_ensure_contacts_file, workspace_dir, language)
        await run_sync_io(_ensure_mail_triage_file, workspace_dir, language)

    agent_ref = AgentProfileRef(
        id=new_id,
        workspace_dir=str(workspace_dir),
        enabled=True,
    )

    await run_sync_io(
        _persist_created_agent,
        new_id,
        agent_ref,
        agent_config,
    )

    logger.info(
        "Copied agent %s -> %s "
        "(name=%s, agent_json=%s, md=%s, skills=%s, jobs=%s)",
        sanitize_log_value(agentId),
        sanitize_log_value(new_id),
        sanitize_log_value(new_name),
        request.copy_agent_json,
        request.copy_md_files,
        request.copy_skills,
        request.copy_jobs,
    )

    if http_request is not None:
        manager = _get_multi_agent_manager(http_request)
        manager.schedule_agent_startup(new_id)

    return agent_ref


@router.put(
    "/{agentId}",
    response_model=AgentProfileConfig,
    summary="Update agent",
    description="Update agent configuration and trigger reload",
)
async def update_agent(  # pylint: disable=too-many-statements
    agentId: str = PathParam(...),
    agent_config: AgentProfileConfig = Body(...),
    request: Request = None,
) -> AgentProfileConfig:
    """Update agent configuration."""
    config = await run_sync_io(load_config)

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    # The root profile is the canonical workspace location.  Updating an
    # agent does not move its workspace, so request-body workspace_dir must
    # never redirect driver-card or template writes to another path.
    workspace_dir = Path(
        config.agents.profiles[agentId].workspace_dir,
    ).expanduser()
    canonical_workspace_dir = str(workspace_dir)

    existing_config_snap = deepcopy(
        await run_sync_io(load_agent_config, agentId),
    )
    # Older versions allowed the request body to drift from the registered
    # workspace. Keep rollback snapshots on the canonical path too.
    existing_config_snap.workspace_dir = canonical_workspace_dir

    effective_backend = (
        agent_config.backend
        if "backend" in agent_config.model_fields_set
        else getattr(existing_config_snap, "backend", "qwenpaw")
    ) or "qwenpaw"
    mail_was_set = "mail" in agent_config.model_fields_set
    existing_mail_snap = getattr(existing_config_snap, "mail", None)
    effective_mail = (
        _merge_unchanged_mail_secrets(
            agent_config.mail,
            existing_mail_snap,
        )
        if mail_was_set and agent_config.mail is not None
        else (None if mail_was_set else existing_mail_snap)
    )
    _validate_mail_backend_compatibility(
        effective_backend,
        effective_mail,
    )

    if effective_mail is not None:
        _validate_mail_config(effective_mail)

    update_data = agent_config.model_dump(exclude_unset=True)
    previous_config = existing_config_snap

    def apply_update(existing_config: AgentProfileConfig) -> None:
        nonlocal previous_config
        previous_config = deepcopy(existing_config)
        previous_config.workspace_dir = canonical_workspace_dir

        requested = AgentProfileConfig.model_validate(
            {**existing_config.model_dump(), **update_data},
        )
        if mail_was_set:
            requested.mail = (
                _merge_unchanged_mail_secrets(
                    agent_config.mail,
                    existing_config.mail,
                )
                if agent_config.mail is not None
                else None
            )
        else:
            # Secret fields are intentionally excluded from model_dump(), so
            # restore the authoritative in-memory mail model after validating
            # the ordinary merged fields.
            requested.mail = deepcopy(existing_config.mail)
        # Re-check the backend/mail exclusivity on the merged config
        # inside the file lock: a concurrent update may have switched
        # the persisted backend after the unlocked snapshot check.
        _validate_mail_backend_compatibility(
            requested.backend,
            requested.mail,
        )
        if requested.mail is not None:
            _validate_mail_config(requested.mail)
        old_memory = existing_config.running.reme_light_memory_config
        old_embedding = old_memory.embedding_model_config
        requested_running = update_data.get("running")
        if requested_running is not None:
            new_memory = requested.running.reme_light_memory_config
            new_embedding = new_memory.embedding_model_config
            if old_embedding != new_embedding:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Embedding configuration must be updated through "
                        "/workspace/running-config so the live ReMe runtime "
                        "can be changed transactionally"
                    ),
                )
        for key in update_data:
            if key not in {"id", "workspace_dir"}:
                setattr(existing_config, key, getattr(requested, key))
        existing_config.id = agentId
        existing_config.workspace_dir = canonical_workspace_dir

    try:
        updated_config = await update_agent_config_async(
            agentId,
            apply_update,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Keep the secret-free DriverCard and encrypted credential in lockstep with
    # *persisted* final configuration.  In particular, an explicit mail=null
    # or a backend switch must revoke the old MCP capability before reload.
    try:
        driver_card_synced = await run_sync_io(
            _sync_qwenpawmail_driver_card,
            workspace_dir,
            updated_config.mail,
            updated_config.backend,
            force_rewrite=mail_was_set,
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Failed to synchronize qwenpawmail driver for agent %s",
            sanitize_log_value(agentId),
            exc_info=True,
        )
        driver_card_synced = False

    if not driver_card_synced:
        # The runtime has not been reloaded yet, so restoring the previous
        # config keeps its live state coherent. The failed sync already
        # revokes a card containing superseded credentials; regenerate the
        # previous card only after the old config is durable again.
        (
            rollback_configured,
            rollback_driver,
        ) = await _rollback_qwenpawmail_update(
            agentId,
            previous_config,
            workspace_dir,
        )

        rollback_detail = (
            "The previous mail configuration was restored."
            if rollback_configured and rollback_driver
            else "Rollback was incomplete; the driver was left disabled."
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "The qwenpawmail driver card could not be synchronized. "
                f"{rollback_detail} Check workspace permissions and retry."
            ),
        )

    if updated_config.mail is not None and updated_config.backend == "qwenpaw":
        await run_sync_io(
            _ensure_contacts_file,
            workspace_dir,
            updated_config.language or config.agents.language or "en",
        )
        await run_sync_io(
            _ensure_mail_triage_file,
            workspace_dir,
            updated_config.language or config.agents.language or "en",
        )

    schedule_agent_reload(request, agentId)

    return updated_config


@router.patch(
    "/{agentId}/model-settings",
    response_model=AgentProfileConfig,
    summary="Update agent model settings",
    description="Update only model-routing settings and trigger reload",
)
async def update_agent_model_settings(
    agentId: str = PathParam(...),
    body: AgentModelSettingsPatch = Body(...),
    request: Request = None,
) -> AgentProfileConfig:
    """Patch model-routing fields without overwriting other settings."""
    values = {field: getattr(body, field) for field in body.model_fields_set}

    def apply_settings(existing_config: AgentProfileConfig) -> None:
        for key, value in values.items():
            setattr(existing_config, key, value)

    try:
        updated = await run_sync_io(
            mutate_agent_config,
            agentId,
            apply_settings,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    schedule_agent_reload(request, agentId)
    return updated


@router.post(
    "/{agentId}/memory/reindex",
    summary="Rebuild agent memory index",
    description="Clear and rebuild the ReMe search index for an agent",
)
async def rebuild_agent_memory_index(
    agentId: str = PathParam(...),
    request: Request = None,
) -> dict[str, str]:
    """Run the expensive ReMe reindex job as an explicit maintenance task."""
    config = await run_sync_io(load_config)
    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    agent_config = await run_sync_io(load_agent_config, agentId)
    if agent_config.running.memory_manager_backend != "remelight":
        raise HTTPException(
            status_code=400,
            detail="Memory index rebuild is only supported by ReMe Light",
        )

    manager = _get_multi_agent_manager(request)
    workspace = await manager.get_agent(agentId)
    memory_manager = workspace.memory_manager
    if memory_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Memory manager is not available",
        )

    try:
        response = await memory_manager.rebuild_index()
    except RuntimeError as exc:
        if str(exc) == "Memory index rebuild is already running":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise

    if response is None:
        raise HTTPException(
            status_code=503,
            detail="ReMe is not started or the reindex job failed",
        )
    if not response.success:
        raise HTTPException(status_code=500, detail=str(response.answer))

    return {"status": "completed"}


@router.get(
    "/{agentId}/memory/runtime-status",
    response_model=MemoryRuntimeStatus,
    summary="Get agent memory runtime state",
    description="Return in-memory ReMe lifecycle state without a ReMe lease",
)
async def get_agent_memory_runtime_status(
    agentId: str = PathParam(...),
    request: Request = None,
) -> MemoryRuntimeStatus:
    """Return immediately even while an exclusive lifecycle job is active."""
    config = await run_sync_io(load_config)
    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    agent_config = await run_sync_io(load_agent_config, agentId)
    if agent_config.running.memory_manager_backend != "remelight":
        raise HTTPException(
            status_code=400,
            detail="Memory status is only supported by ReMe Light",
        )

    manager = _get_multi_agent_manager(request)
    workspace = manager.get_loaded_agent(agentId)
    if workspace is None or workspace.memory_manager is None:
        raise HTTPException(status_code=503, detail="Agent is not running")
    memory_config = agent_config.running.reme_light_memory_config
    return MemoryRuntimeStatus.model_validate(
        workspace.memory_manager.get_runtime_status(
            auto_memory_interval=memory_config.auto_memory_interval,
        ),
    )


@router.get(
    "/{agentId}/memory/status",
    response_model=ReMeMemoryStatusResponse,
    summary="Get agent ReMe memory status",
    description="Return ReMe component memory estimates and process RSS",
)
async def get_agent_memory_status(
    agentId: str = PathParam(...),
    request: Request = None,
) -> ReMeMemoryStatusResponse:
    """Inspect the currently running ReMe instance without reloading it."""
    config = await run_sync_io(load_config)
    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    agent_config = await run_sync_io(load_agent_config, agentId)
    if agent_config.running.memory_manager_backend != "remelight":
        raise HTTPException(
            status_code=400,
            detail="Memory status is only supported by ReMe Light",
        )

    manager = _get_multi_agent_manager(request)
    workspace = manager.get_loaded_agent(agentId)
    if workspace is None:
        raise HTTPException(
            status_code=503,
            detail="Agent is not running",
        )
    memory_manager = workspace.memory_manager
    if memory_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Memory manager is not available",
        )

    response = await memory_manager.reme_status()
    if response is None:
        raise HTTPException(
            status_code=503,
            detail="ReMe is not started or status reporting is unavailable",
        )
    if not response.success:
        raise HTTPException(status_code=500, detail=str(response.answer))

    metadata = getattr(response, "metadata", None) or {}
    memory = metadata.get("status", {}).get("memory")
    if not isinstance(memory, dict):
        raise HTTPException(
            status_code=500,
            detail="ReMe returned an invalid memory status payload",
        )
    memory_config = agent_config.running.reme_light_memory_config
    try:
        return ReMeMemoryStatusResponse.model_validate(
            {
                **memory,
                "runtime": memory_manager.get_runtime_status(
                    auto_memory_interval=memory_config.auto_memory_interval,
                ),
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="ReMe returned an invalid memory status payload",
        ) from exc


@router.get(
    "/{agentId}/memory/graph",
    response_model=MemoryGraphSnapshot,
    summary="Get agent memory graph",
    description="Return the category-rooted ReMe wikilink graph",
)
async def get_agent_memory_graph(
    agentId: str = PathParam(...),
    request: Request = None,
) -> MemoryGraphSnapshot:
    """Return a frontend-ready graph snapshot from embedded ReMe."""

    def load_memory_configs() -> AgentProfileConfig:
        config = load_config()
        if agentId not in config.agents.profiles:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{agentId}' not found",
            )
        return load_agent_config(agentId)

    agent_config = await run_sync_io(load_memory_configs)
    if agent_config.running.memory_manager_backend != "remelight":
        raise HTTPException(
            status_code=400,
            detail="Memory graph is only supported by ReMe Light",
        )

    manager = _get_multi_agent_manager(request)
    workspace = await manager.get_agent(agentId)
    memory_manager = workspace.memory_manager
    if memory_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Memory manager is not available",
        )

    response = await memory_manager.graph_snapshot()
    if response is None:
        raise HTTPException(
            status_code=503,
            detail="ReMe is not started or the graph snapshot job failed",
        )
    if not response.success:
        raise HTTPException(status_code=500, detail=str(response.answer))

    snapshot = MemoryGraphSnapshot.model_validate(response.answer)
    reme_config = agent_config.running.reme_light_memory_config
    roots = sorted(
        (
            ("daily", reme_config.daily_dir),
            ("digest", reme_config.digest_dir),
        ),
        key=lambda item: len(item[1].replace("\\", "/").strip("/").split("/")),
        reverse=True,
    )
    for node in snapshot.nodes:
        if not node.indexed or node.virtual:
            continue
        node_path = node.path.replace("\\", "/").strip("/")
        for section, configured_root in roots:
            root = configured_root.replace("\\", "/").strip("/")
            prefix = f"{root}/"
            if root and node_path.startswith(prefix):
                node.section = section
                prefix_length = len(prefix)
                node.relative_path = node_path[prefix_length:]
                break

    return snapshot


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
    config = await run_sync_io(load_config)

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
    if manager.is_agent_startup_in_progress(agentId):
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{agentId}' cannot be deleted while starting",
        )
    await manager.stop_agent(agentId)

    def remove_agent(latest_config: Any) -> None:
        if agentId not in latest_config.agents.profiles:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{agentId}' not found",
            )
        del latest_config.agents.profiles[agentId]
        latest_config.agents.agent_order = _normalized_agent_order(
            latest_config,
        )

    await run_sync_io(mutate_config, remove_agent)

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
    config = await run_sync_io(load_config)

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

    if not enabled and manager.is_agent_startup_in_progress(agentId):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Agent '{agentId}' is still starting and cannot be "
                "disabled yet"
            ),
        )

    if not enabled and getattr(agent_ref, "enabled", True):
        await manager.stop_agent(agentId)

    def apply_enabled(latest_config: Any) -> None:
        if agentId not in latest_config.agents.profiles:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{agentId}' not found",
            )
        latest_config.agents.profiles[agentId].enabled = enabled

    await run_sync_io(mutate_config, apply_enabled)

    if enabled:
        manager.schedule_agent_startup(agentId)

    return {
        "success": True,
        "agent_id": agentId,
        "enabled": enabled,
    }


def _apply_workspace_md_templates(
    workspace_dir: Path,
    language: str,
    *,
    md_template_id: str | None,
) -> None:
    """Copy common and template-specific markdown files for a workspace."""
    copy_workspace_md_files(
        language,
        workspace_dir,
        md_template_id=md_template_id,
    )


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
                sanitize_log_value(skill_name),
                sanitize_log_value(workspace_dir),
                sanitize_log_value(result.get("reason", "unknown")),
            )
        except Exception as e:
            logger.warning(
                "Failed to install initial skill %s for %s: %s",
                sanitize_log_value(skill_name),
                sanitize_log_value(workspace_dir),
                sanitize_log_value(e),
            )


_ALLOWED_MAIL_DOMAINS = {
    "163.com",
    "126.com",
    "yeah.net",
    "qq.com",
    "foxmail.com",
    "sina.com",
    "sina.cn",
    "aliyun.com",
    "gmail.com",
    "exmail.qq.com",
    "qiye.aliyun.com",
    "qiye.163.com",
}

# Domains whose authorization codes (or app-specific passwords) are
# exactly 16 characters.  Other allowed domains use login passwords
# (or client-specific passwords) of variable length.
_AUTH_CODE_16_CHAR_DOMAINS = frozenset(
    {
        "163.com",
        "126.com",
        "yeah.net",
        "qq.com",
        "foxmail.com",
        "sina.com",
        "sina.cn",
        "gmail.com",
    },
)

# Microsoft disabled basic auth (and app passwords) for personal
# IMAP/SMTP in September 2024; only OAuth2 works now, which this
# version does not support.
_MICROSOFT_MAIL_DOMAINS = {
    "outlook.com",
    "hotmail.com",
    "live.com",
    "msn.com",
    "office365.com",
}

# Basic sanity check for custom enterprise-mail domains coming from
# free-form frontend input: labels of alnum/hyphen joined by dots.
_MAIL_DOMAIN_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$",
)


def _validate_mail_backend_compatibility(
    backend: str | None,
    mail: AgentMailConfig | None,
) -> None:
    """Reject mailbox configuration on unsupported agent backends."""
    if mail is not None and (backend or "qwenpaw") != "qwenpaw":
        raise HTTPException(
            status_code=400,
            detail="Mail configuration is only supported for qwenpaw backend",
        )


def _merge_unchanged_mail_secrets(
    incoming: AgentMailConfig,
    existing: AgentMailConfig | None,
) -> AgentMailConfig:
    """Treat blank edit-form secrets as "keep existing" for one mailbox.

    GET responses omit secret fields, so the Console submits blanks when a
    user edits unrelated agent settings.  Secrets are inherited only when the
    mailbox mode and public identity are unchanged; changing the account still
    requires fresh credentials and is validated normally.
    """
    merged = incoming.model_copy(deep=True)
    if existing is None:
        return merged

    def identity(mail: AgentMailConfig) -> tuple[bool, str, str, str]:
        credential = mail.credential
        return (
            mail.is_new_account,
            (credential.name or "").strip().lower(),
            (credential.domain or "").strip().lower(),
            (credential.provider or "").strip().lower(),
        )

    if identity(merged) != identity(existing):
        return merged
    for field_name in ("auth_code", "password", "phone_number"):
        if not getattr(merged.credential, field_name):
            setattr(
                merged.credential,
                field_name,
                getattr(existing.credential, field_name),
            )
    return merged


def _validate_mail_config(mail: AgentMailConfig) -> None:
    # pylint: disable=too-many-branches
    """Validate the mailbox management configuration.

    Raises HTTPException(400) when validation fails.
    """
    credential = mail.credential
    provider = (credential.provider or "").strip()
    if provider and provider not in _ENTERPRISE_MAIL_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported mail provider '{provider}', allowed: "
                f"'' (auto-detect) or "
                f"{sorted(_ENTERPRISE_MAIL_PROVIDERS)}"
            ),
        )
    domain = (credential.domain or "").strip().lower()
    if domain in _MICROSOFT_MAIL_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Mail domain '{domain}' is not supported: since "
                "September 2024 Microsoft only allows OAuth2 for "
                "IMAP/SMTP access (basic auth and app passwords are "
                "both disabled). This version does not support "
                "OAuth2 — please use another mailbox."
            ),
        )
    if provider:
        # Well-known domains resolve their IMAP/SMTP hosts automatically;
        # combining them with an explicit enterprise provider would inject
        # mismatched host overrides.
        if domain in _ALLOWED_MAIL_DOMAINS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Mail domain '{domain}' is a well-known domain and "
                    "must not be combined with an enterprise mail "
                    "provider; leave provider empty (auto-detect)"
                ),
            )
        # Enterprise mail with a custom domain: accept any
        # syntactically valid domain instead of the whitelist.
        if not domain or not _MAIL_DOMAIN_RE.match(domain):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid mail domain '{credential.domain}' for "
                    f"enterprise mail provider '{provider}'"
                ),
            )
    elif domain not in _ALLOWED_MAIL_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported mail domain '{credential.domain}', "
                f"allowed: {sorted(_ALLOWED_MAIL_DOMAINS)}"
            ),
        )

    if mail.push is not None:
        if len(mail.push.rules) > 50:
            raise HTTPException(
                status_code=400,
                detail="push.rules supports at most 50 rules",
            )
        for index, rule in enumerate(mail.push.rules):
            if rule.action == "move" and not rule.param.strip():
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"push.rules[{index}]: param (target folder) "
                        "is required when action is 'move'"
                    ),
                )

    if mail.is_new_account:
        # Registration secrets are entered directly on the provider page and
        # are no longer part of QwenPaw's dedicated-mailbox form.  A blank
        # auth_code means registration is still pending; supplying the final
        # provider credential completes provisioning in the same UI.
        credential.password = ""
        credential.phone_number = ""
        if not credential.auth_code:
            return
        mail.is_new_account = False

    if domain in _AUTH_CODE_16_CHAR_DOMAINS:
        if len(credential.auth_code) != 16:
            raise HTTPException(
                status_code=400,
                detail=(
                    "auth_code must be exactly 16 characters "
                    "(authorization code or app-specific password)"
                ),
            )
    elif not credential.auth_code:
        raise HTTPException(
            status_code=400,
            detail=(
                "auth_code (login password or client-specific "
                "password) is required"
            ),
        )
    if not credential.name:
        raise HTTPException(
            status_code=400,
            detail="credential name (mailbox username) is required",
        )


def _ensure_workspace_md_file(
    workspace_dir: Path,
    language: str,
    filename: str,
) -> None:
    """Copy a md_files template into the workspace if missing.

    Thin wrapper over :func:`ensure_workspace_md_file`, kept for the
    router-local call sites.  Idempotent and never raises.
    """
    ensure_workspace_md_file(workspace_dir, language, filename)


def _ensure_contacts_file(workspace_dir: Path, language: str) -> None:
    """Copy the CONTACTS.md template into the workspace if missing."""
    _ensure_workspace_md_file(workspace_dir, language, "CONTACTS.md")


def _ensure_mail_triage_file(workspace_dir: Path, language: str) -> None:
    """Copy the MAIL_TRIAGE.md seed tree into the workspace if missing."""
    _ensure_workspace_md_file(workspace_dir, language, "MAIL_TRIAGE.md")


def _initialize_agent_workspace(
    workspace_dir: Path,
    skill_names: list[str] | None = None,
    md_template_id: str | None = None,
    language: str | None = None,
    *,
    apply_md_templates: bool = True,
    create_skills_dir: bool = True,
    create_jobs_file: bool = True,
) -> None:
    """Initialize agent workspace with only explicitly requested skills."""
    from ...config import load_config as load_global_config

    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    if create_skills_dir:
        get_workspace_skills_dir(workspace_dir).mkdir(exist_ok=True)

    config = load_global_config()
    if not language:
        language = config.agents.language or "zh"

    if apply_md_templates:
        _apply_workspace_md_templates(
            workspace_dir,
            language,
            md_template_id=md_template_id,
        )
        _ensure_heartbeat_file(workspace_dir, language)
    _install_initial_skills(workspace_dir, skill_names)

    if create_jobs_file:
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
