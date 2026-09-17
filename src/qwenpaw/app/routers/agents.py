# -*- coding: utf-8 -*-
"""Multi-agent management API.

Provides RESTful API for managing multiple agent instances.
"""

import json
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, Field, field_validator

from qwenpaw.exceptions import (
    AppBaseException,
    ProviderError,
)

from ...access.actor import ActorContext
from ...access.agent_membership import (
    AccessibleAgent,
    AgentAccessDeniedError,
    AgentMembershipService,
)
from ...access.agent_repository import (
    AgentResourceRole,
    AgentVisibility,
    LegacyAgentRecord,
    PostgresAgentRepository,
)
from ...identity.runtime import get_identity_schema, is_multi_user_enabled
from ...memory_scope.models import (
    MemoryIndexState,
    MemoryScope,
    MemoryWorkspaceStatus,
)
from ...memory_scope.resolver import MemoryScopeResolver
from ...persistence.agent_user_workspaces import AgentUserWorkspaceRepository

from ...agents.utils.file_handling import read_text_file_with_encoding_fallback
from ...agents.effective_model import resolve_effective_model
from ..utils import schedule_agent_reload
from ...config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    ModelSlotConfig,
    load_agent_config,
    save_agent_config,
    update_agent_config_async,
    generate_short_agent_id,
    sanitize_agent_id,
    validate_agent_id,
)
from ...config.utils import load_config, save_config
from ...agents.utils import copy_workspace_md_files, normalize_agent_language
from ...agents.skill_system import SkillPoolService, get_workspace_skills_dir
from ...harnesses.registry import ProviderCatalogItem, get_provider
from ..agent_startup import AgentStartupStatus
from ..multi_agent_manager import MultiAgentManager
from ...constant import WORKING_DIR
from ...utils.io_utils import run_sync_io
from ...workspaces.layout import ensure_artifacts_directory

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
    access_role: AgentResourceRole = AgentResourceRole.OWNER
    registration_state: Literal["registered", "legacy_preview"] = "registered"
    can_edit: bool = True
    can_delete: bool = True
    can_copy: bool = True
    can_export: bool = True
    can_toggle: bool = True
    can_reorder: bool = True
    visibility: AgentVisibility = AgentVisibility.PRIVATE
    can_manage_members: bool = True
    model_locked: bool = False
    historical_read_only: bool = False


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


class ReMeComponentMemoryUsage(BaseModel):
    """Estimated memory owned by one ReMe component."""

    bytes: int
    human: str


class MemoryWorkerRuntimeStatus(BaseModel):
    """Sanitized state of the background memory worker."""

    status: Literal["idle", "busy", "stopping", "error"]
    queue_pending: int
    tasks_running: int


class AutoMemoryRuntimeStatus(BaseModel):
    """Aggregate auto-memory progress without exposing session identity."""

    enabled: bool
    interval: int
    active_sessions: int
    sessions_with_pending: int
    pending_turns: int


class RecentMemoryRuntimeStatus(BaseModel):
    """Latest terminal task timestamps and a bounded error summary."""

    last_completed_at: str | None = None
    last_failed_at: str | None = None
    last_error: str | None = None


class MemoryRuntimeStatus(BaseModel):
    """Operational state surfaced to the Console."""

    worker: MemoryWorkerRuntimeStatus
    auto_memory: AutoMemoryRuntimeStatus
    recent: RecentMemoryRuntimeStatus
    reindexing: bool


class ReMeMemoryStatusResponse(BaseModel):
    """Structured memory information returned by ReMe's status job."""

    components: dict[str, dict[str, ReMeComponentMemoryUsage]]
    components_total: str
    process_rss: str
    runtime: MemoryRuntimeStatus


class MemoryScopeSummary(BaseModel):
    """不暴露物理路径和用户身份的记忆作用域摘要。"""

    scope: MemoryScope
    can_read: bool
    can_edit: bool
    status: MemoryWorkspaceStatus
    index_state: MemoryIndexState
    index_version: int = 0


class MemoryScopesResponse(BaseModel):
    """当前请求主体可访问的记忆作用域。"""

    agent_id: str
    scopes: list[MemoryScopeSummary]


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


def _get_agent_metadata_repository() -> PostgresAgentRepository:
    """按当前身份 Schema 装配唯一 Agent 元数据 Repository。"""
    return PostgresAgentRepository(schema=get_identity_schema())


def _get_agent_membership_service() -> AgentMembershipService:
    return AgentMembershipService(_get_agent_metadata_repository())


def _get_agent_user_workspace_repository() -> AgentUserWorkspaceRepository:
    return AgentUserWorkspaceRepository(schema=get_identity_schema())


def _get_memory_scope_resolver() -> MemoryScopeResolver:
    return MemoryScopeResolver()


def _model_mode(active_model: ModelSlotConfig | None) -> Literal[
    "inherited",
    "explicit",
]:
    if active_model and active_model.provider_id and active_model.model:
        return "explicit"
    return "inherited"


def _validate_agent_effective_model(agent_config: AgentProfileConfig) -> None:
    """拒绝无法解析到有效模型的 QwenPaw 智能体配置。"""
    if agent_config.backend != "qwenpaw":
        return
    try:
        resolve_effective_model(agent_config)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{agentId}/memory/scopes",
    response_model=MemoryScopesResponse,
    summary="Get safe memory scope summary",
)
async def get_memory_scopes(
    agentId: str = PathParam(..., min_length=1),
    request: Request = None,
) -> MemoryScopesResponse:
    """返回当前主体可用的公共/私有记忆作用域，不返回路径或其他用户 ID。"""
    governance = bool(
        request is not None
        and request.headers.get("X-Agent-Governance") == "runtime-config"
    )
    access = await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles={
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
            AgentResourceRole.USER,
        },
    )
    actor = _request_actor(request)
    resolver = _get_memory_scope_resolver()
    public_context = resolver.resolve_public(
        actor=actor,
        agent_id=agentId,
        governance=governance,
    )
    resolver.ensure_workspace(public_context)
    public_can_edit = governance or (
        access is not None
        and access.role
        in {AgentResourceRole.OWNER, AgentResourceRole.COLLABORATOR}
        and not access.historical_read_only
    )
    try:
        agent_config = await run_sync_io(load_agent_config, agentId)
        public_index_state = (
            MemoryIndexState.NEEDS_REINDEX
            if agent_config.running.reme_light_memory_config.needs_reindex
            else MemoryIndexState.READY
        )
    except Exception:
        public_index_state = MemoryIndexState.NEEDS_REINDEX
    loaded_manager = None
    if request is not None:
        manager = getattr(getattr(request, "app", None), "state", None)
        multi_agent_manager = getattr(manager, "multi_agent_manager", None)
        loaded_workspace = (
            multi_agent_manager.get_loaded_agent(agentId)
            if multi_agent_manager is not None
            else None
        )
        loaded_manager = getattr(loaded_workspace, "memory_manager", None)
    if getattr(loaded_manager, "is_reindexing", False):
        public_index_state = MemoryIndexState.REINDEXING
    summaries = [
        MemoryScopeSummary(
            scope=MemoryScope.PUBLIC,
            can_read=True,
            can_edit=public_can_edit,
            status=MemoryWorkspaceStatus.ACTIVE,
            index_state=public_index_state,
        )
    ]
    if not governance and actor.user_id is not None:
        private_context = resolver.resolve_private(
            actor=actor,
            agent_id=agentId,
        )
        resolver.ensure_workspace(private_context)
        repository = _get_agent_user_workspace_repository()
        record = await repository.ensure_private(
            user_id=actor.user_id,
            agent_key=agentId,
            workspace_key=resolver.workspace_key(private_context),
        )
        summaries.append(
            MemoryScopeSummary(
                scope=MemoryScope.PRIVATE,
                can_read=True,
                can_edit=True,
                status=record.status,
                index_state=record.index_state,
                index_version=record.index_version,
            )
        )
    return MemoryScopesResponse(agent_id=agentId, scopes=summaries)


def _request_actor(request: Request | None) -> ActorContext:
    actor = getattr(getattr(request, "state", None), "actor", None)
    if not isinstance(actor, ActorContext):
        raise HTTPException(status_code=401, detail="not_authenticated")
    return actor


def _legacy_agent_record(
    agent_id: str,
    agent_ref: AgentProfileRef,
    agent_config: AgentProfileConfig,
) -> LegacyAgentRecord:
    return LegacyAgentRecord(
        key=agent_id,
        name=agent_config.name,
        description=agent_config.description or "",
        workspace_key=agent_ref.workspace_dir,
        status=("active" if getattr(agent_ref, "enabled", True) else "disabled"),
    )


async def _require_agent_role(
    *,
    request: Request | None,
    agent_id: str,
    allowed_roles: set[AgentResourceRole],
) -> AccessibleAgent | None:
    """Legacy 不改变原行为；多用户模式统一执行资源角色校验。"""
    if not is_multi_user_enabled():
        return None
    if (
        request is not None
        and getattr(request, "headers", {}).get("X-Agent-Governance")
        == "runtime-config"
    ):
        from ..agent_context import get_running_config_workspace

        workspace = await get_running_config_workspace(
            request,
            action="agent.admin.runtime_config.memory",
        )
        if getattr(workspace, "agent_id", None) != agent_id:
            raise HTTPException(status_code=403, detail="forbidden")
        return None
    config = load_config()
    agent_ref = config.agents.profiles.get(agent_id)
    if agent_ref is None:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        agent_config = load_agent_config(agent_id)
        return await _get_agent_membership_service().require_role(
            actor=_request_actor(request),
            agent=_legacy_agent_record(agent_id, agent_ref, agent_config),
            allowed_roles=allowed_roles,
        )
    except AgentAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc


async def _register_legacy_preview(
    *,
    access: AccessibleAgent | None,
    request: Request | None,
    repository: PostgresAgentRepository,
) -> None:
    """用户首次修改旧 Agent 时登记 owner；只读列表仍保持预览。"""
    if access is None or access.registration_state != "legacy_preview":
        return
    actor = _request_actor(request)
    if actor.user_id is None:  # pragma: no cover - guarded by auth
        raise HTTPException(status_code=401, detail="not_authenticated")
    await repository.register_owner(
        agent=access.agent,
        owner_user_id=actor.user_id,
    )


async def _accessible_agents_for_config(
    *,
    config,
    request: Request | None,
) -> list[AccessibleAgent]:
    records: list[LegacyAgentRecord] = []
    for agent_id in _display_agent_order(config):
        agent_ref = config.agents.profiles[agent_id]
        try:
            agent_config = load_agent_config(agent_id)
        except Exception:  # noqa: BLE001 - preserve legacy catalog fallback
            agent_config = AgentProfileConfig(
                id=agent_id,
                name=agent_id.title(),
                description="",
                workspace_dir=agent_ref.workspace_dir,
            )
        records.append(_legacy_agent_record(agent_id, agent_ref, agent_config))
    return await _get_agent_membership_service().list_accessible(
        actor=_request_actor(request),
        legacy_agents=records,
    )


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
    config = load_config()
    manager = _get_multi_agent_manager(request) if request is not None else None
    ordered_agent_ids = _display_agent_order(config)
    access_by_id: dict[str, AccessibleAgent] = {}
    if is_multi_user_enabled():
        legacy_agents: list[LegacyAgentRecord] = []
        for agent_id in ordered_agent_ids:
            agent_ref = config.agents.profiles[agent_id]
            try:
                agent_config = load_agent_config(agent_id)
            except Exception:  # noqa: BLE001 - preserve legacy fallback
                agent_config = AgentProfileConfig(
                    id=agent_id,
                    name=agent_id.title(),
                    description="",
                    workspace_dir=agent_ref.workspace_dir,
                )
            legacy_agents.append(
                _legacy_agent_record(agent_id, agent_ref, agent_config)
            )
        accessible = await _get_agent_membership_service().list_accessible(
            actor=_request_actor(request),
            legacy_agents=legacy_agents,
        )
        access_by_id = {item.agent.key: item for item in accessible}
        ordered_agent_ids = [
            agent_id for agent_id in ordered_agent_ids if agent_id in access_by_id
        ]

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
                AgentStartupStatus.PENDING if enabled else AgentStartupStatus.DISABLED
            )
        )
        access = access_by_id.get(agent_id)
        role = access.role if access else AgentResourceRole.OWNER
        can_manage = role in {
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
        }
        historical_read_only = bool(
            access is not None and access.historical_read_only
        )
        access_fields = {
            "access_role": role,
            "registration_state": (
                access.registration_state if access else "registered"
            ),
            "can_edit": can_manage and not historical_read_only,
            "can_delete": (
                role is AgentResourceRole.OWNER and not historical_read_only
            ),
            "can_copy": can_manage and not historical_read_only,
            "can_export": (
                role is AgentResourceRole.OWNER and not historical_read_only
            ),
            "can_toggle": can_manage and not historical_read_only,
            # Order and pin state are shared profile metadata. Collaborators
            # may edit the Agent configuration, but only its owner controls
            # where that shared Agent appears and whether it is pinned.
            "can_reorder": (
                role is AgentResourceRole.OWNER and not historical_read_only
            ),
            "visibility": access.visibility if access else AgentVisibility.PRIVATE,
            "can_manage_members": (
                role is AgentResourceRole.OWNER and not historical_read_only
            ),
            "model_locked": False,
            "historical_read_only": historical_read_only,
        }
        try:
            agent_config = load_agent_config(agent_id)
            description = agent_config.description or ""

            profile_desc = _read_profile_description(agent_ref.workspace_dir)
            if profile_desc:
                if description.strip():
                    description = f"{description.strip()} | {profile_desc}"
                else:
                    description = profile_desc

            active_model = agent_config.active_model
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
                    **access_fields,
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
                    **access_fields,
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
    request: Request = None,
) -> dict:
    """Persist the full ordered list of agent IDs."""
    config = load_config()
    configured_ids = list(config.agents.profiles.keys())

    if len(reorder_request.agent_ids) != len(set(reorder_request.agent_ids)):
        raise HTTPException(
            status_code=400,
            detail="Each configured agent ID must appear exactly once.",
        )

    expected_ids = configured_ids
    if is_multi_user_enabled():
        accessible = await _accessible_agents_for_config(
            config=config,
            request=request,
        )
        expected_ids = [
            item.agent.key
            for item in accessible
            if item.role in {AgentResourceRole.OWNER, AgentResourceRole.COLLABORATOR}
        ]

    if set(reorder_request.agent_ids) != set(expected_ids):
        raise HTTPException(
            status_code=400,
            detail="Each configured agent ID must appear exactly once.",
        )

    persisted_order = list(reorder_request.agent_ids)
    if is_multi_user_enabled():
        persisted_order = _normalized_agent_order(config)
        visible = set(expected_ids)
        positions = [
            index
            for index, agent_id in enumerate(persisted_order)
            if agent_id in visible
        ]
        for index, agent_id in zip(
            positions,
            reorder_request.agent_ids,
            strict=True,
        ):
            persisted_order[index] = agent_id

    if not _is_valid_display_order(config, persisted_order):
        raise HTTPException(
            status_code=400,
            detail=(
                "Agent order must keep default first and pinned agents "
                "before unpinned agents."
            ),
        )

    config.agents.agent_order = persisted_order
    save_config(config)

    return {"success": True, "agent_ids": list(reorder_request.agent_ids)}


@router.patch(
    "/{agentId}/pin",
    summary="Pin or unpin an agent",
    description="Persist an agent's pinned state in agent selectors",
)
async def set_agent_pinned(
    agentId: str = PathParam(...),
    pinned: bool = Body(..., embed=True),
    request: Request = None,
) -> dict:
    """Persist an agent's pinned state without changing enabled state."""
    config = load_config()

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

    access = await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles={
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
        },
    )

    agent_ref = config.agents.profiles[agentId]
    if agentId != "default":
        agent_ref.pinned = pinned
        config.agents.agent_order = _display_agent_order(config)
        save_config(config)

    if is_multi_user_enabled():
        await _register_legacy_preview(
            access=access,
            request=request,
            repository=_get_agent_metadata_repository(),
        )

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
async def get_agent(
    agentId: str = PathParam(...),
    request: Request = None,
) -> AgentProfileConfig:
    """Get agent configuration."""
    await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles={
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
        },
    )
    try:
        agent_config = load_agent_config(agentId)
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
    request: Request = None,
) -> AgentProfileConfig:
    """Persist model controls owned by a third-party agent backend."""
    access = await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles={
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
        },
    )
    try:
        agent_config = load_agent_config(agentId)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if agent_config.backend == "qwenpaw":
        raise HTTPException(
            status_code=409,
            detail="QwenPaw models use the native model configuration",
        )
    provider = _get_available_third_party_provider(agent_config.backend)
    settings = dict(agent_config.backend_settings)
    values = body.model_dump()
    if provider.capabilities.model_selection:
        if values["model"]:
            settings["model"] = values["model"]
        else:
            settings.pop("model", None)
    if provider.capabilities.reasoning_effort:
        if values["reasoning_effort"]:
            settings["reasoning_effort"] = values["reasoning_effort"]
        else:
            settings.pop("reasoning_effort", None)
    agent_config.backend_settings = settings
    save_agent_config(agentId, agent_config)
    if is_multi_user_enabled():
        repository = _get_agent_metadata_repository()
        await _register_legacy_preview(
            access=access,
            request=request,
            repository=repository,
        )
        await repository.update_metadata(
            agent=_legacy_agent_record(
                agentId,
                load_config().agents.profiles[agentId],
                agent_config,
            )
        )
    return agent_config


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
    if request.backend != "qwenpaw":
        _get_available_third_party_provider(request.backend)

    config = load_config()
    existing_ids = set(config.agents.profiles.keys())

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

    workspace_dir = Path(
        request.workspace_dir or f"{WORKING_DIR}/workspaces/{new_id}",
    ).expanduser()

    active_model = request.active_model if request.backend == "qwenpaw" else None
    if request.backend == "qwenpaw":
        # Validate the effective model before creating database/file drafts,
        # while preserving ``None`` as the inheritance configuration fact.
        try:
            resolve_effective_model(
                SimpleNamespace(active_model=active_model),
            )
        except ProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    metadata_repository = None
    if is_multi_user_enabled():
        actor = _request_actor(http_request)
        if actor.user_id is None:  # pragma: no cover - guarded by auth
            raise HTTPException(status_code=401, detail="not_authenticated")
        metadata_repository = _get_agent_metadata_repository()
        await metadata_repository.register_owner(
            agent=LegacyAgentRecord(
                key=new_id,
                name=request.name,
                description=request.description,
                workspace_key=str(workspace_dir),
                status="draft",
            ),
            owner_user_id=actor.user_id,
            status="draft",
        )

    workspace_dir.mkdir(parents=True, exist_ok=True)

    from ...config.config import (
        ChannelConfig,
        MCPConfig,
        HeartbeatConfig,
        ToolsConfig,
    )

    language = normalize_agent_language(
        request.language or config.agents.language or "en",
    )

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
    )

    _initialize_agent_workspace(
        workspace_dir,
        skill_names=(request.skill_names if request.skill_names is not None else []),
        language=language,
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

    if metadata_repository is not None:
        await metadata_repository.update_metadata(
            agent=LegacyAgentRecord(
                key=new_id,
                name=agent_config.name,
                description=agent_config.description or "",
                workspace_key=str(workspace_dir),
                status="active",
            )
        )
        update_model_mode = getattr(metadata_repository, "update_model_mode", None)
        if callable(update_model_mode):
            await update_model_mode(
                new_id,
                _model_mode(agent_config.active_model),
            )

    logger.info(f"Created new agent: {new_id} (name={request.name})")

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
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    await _require_agent_role(
        request=http_request,
        agent_id=agentId,
        allowed_roles={
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
        },
    )

    try:
        source_config = load_agent_config(agentId)
    except (ValueError, AppBaseException) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    source_workspace = Path(
        config.agents.profiles[agentId].workspace_dir,
    ).expanduser()

    existing_ids = set(config.agents.profiles.keys())
    new_id = _generate_unique_id(existing_ids)
    new_name = (request.name or "").strip() or f"{source_config.name} Copy"
    workspace_dir = Path(f"{WORKING_DIR}/workspaces/{new_id}").expanduser()

    agent_config = _build_copied_agent_config(
        source_config=source_config,
        new_id=new_id,
        new_name=new_name,
        workspace_dir=workspace_dir,
    )
    if (
        agent_config.backend == "qwenpaw"
        and agent_config.active_model is not None
    ):
        # A copy retains the source model mode. Validate it before creating
        # database drafts or filesystem state so a stale explicit model cannot
        # leave a partially copied agent behind.
        try:
            resolve_effective_model(agent_config)
        except ProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    metadata_repository = None
    if is_multi_user_enabled():
        actor = _request_actor(http_request)
        if actor.user_id is None:  # pragma: no cover - guarded by auth
            raise HTTPException(status_code=401, detail="not_authenticated")
        metadata_repository = _get_agent_metadata_repository()
        await metadata_repository.register_owner(
            agent=LegacyAgentRecord(
                key=new_id,
                name=new_name,
                description=source_config.description or "",
                workspace_key=str(workspace_dir),
                status="draft",
            ),
            owner_user_id=actor.user_id,
            status="draft",
        )

    workspace_dir.mkdir(parents=True, exist_ok=True)

    language = normalize_agent_language(
        source_config.language or config.agents.language or "en",
    )

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

    agent_ref = AgentProfileRef(
        id=new_id,
        workspace_dir=str(workspace_dir),
        enabled=True,
    )

    config.agents.profiles[new_id] = agent_ref
    config.agents.agent_order = _normalized_agent_order(config)
    save_config(config)
    save_agent_config(new_id, agent_config)

    if metadata_repository is not None:
        await metadata_repository.update_metadata(
            agent=LegacyAgentRecord(
                key=new_id,
                name=agent_config.name,
                description=agent_config.description or "",
                workspace_key=str(workspace_dir),
                status="active",
            )
        )
        await metadata_repository.update_model_mode(
            new_id,
            _model_mode(agent_config.active_model),
        )

    logger.info(
        "Copied agent %s -> %s " "(name=%s, agent_json=%s, md=%s, skills=%s, jobs=%s)",
        agentId,
        new_id,
        new_name,
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

    access = await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles={
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
        },
    )

    _validate_agent_effective_model(agent_config)

    await _persist_agent_update(
        agentId=agentId,
        agent_config=agent_config,
        request=request,
        access=access,
    )

    return agent_config


async def _persist_agent_update(
    *,
    agentId: str,
    agent_config: AgentProfileConfig,
    request: Request | None,
    access: AccessibleAgent | None = None,
) -> None:
    """复用原更新语义，授权由调用入口在执行前完成。"""
    config = load_config()
    if agentId not in config.agents.profiles:
        raise HTTPException(status_code=404, detail=f"Agent '{agentId}' not found")

    update_data = agent_config.model_dump(exclude_unset=True)

    def apply_update(existing_config: AgentProfileConfig) -> None:
        requested = AgentProfileConfig.model_validate(
            {**existing_config.model_dump(), **update_data},
        )
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
            if key != "id":
                setattr(existing_config, key, getattr(requested, key))
        existing_config.id = agentId

    await update_agent_config_async(agentId, apply_update)
    schedule_agent_reload(request, agentId)

    if is_multi_user_enabled():
        repository = _get_agent_metadata_repository()
        await _register_legacy_preview(
            access=access,
            request=request,
            repository=repository,
        )
        persisted = load_agent_config(agentId)
        await repository.update_metadata(
            agent=_legacy_agent_record(
                agentId,
                config.agents.profiles[agentId],
                persisted,
            )
        )
        await repository.update_model_mode(
            agentId,
            _model_mode(persisted.active_model),
        )



@router.post(
    "/{agentId}/memory/reindex",
    summary="Rebuild agent memory index",
    description="Clear and rebuild the ReMe search index for an agent",
)
async def rebuild_agent_memory_index(
    agentId: str = PathParam(...),
    request: Request = None,
    scope: MemoryScope = MemoryScope.PUBLIC,
) -> dict[str, str]:
    """Run the expensive ReMe reindex job as an explicit maintenance task."""
    config = await run_sync_io(load_config)
    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )
    access = await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles=(
            {AgentResourceRole.OWNER, AgentResourceRole.COLLABORATOR}
            if scope is MemoryScope.PUBLIC
            else set(AgentResourceRole)
        ),
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

    target_manager = memory_manager
    private_record = None
    if scope is MemoryScope.PRIVATE:
        actor = _request_actor(request)
        repository = _get_agent_user_workspace_repository()
        if (
            request.headers.get("X-Agent-Governance") == "runtime-config"
            or access is None
            or access.historical_read_only
        ):
            raise HTTPException(status_code=403, detail="forbidden")
        private_record = await repository.ensure_private(
            user_id=actor.user_id,
            agent_key=agentId,
            workspace_key=f"user_workspaces/{actor.user_id}/{agentId}",
        )
        target_manager = await memory_manager.get_private_runtime(actor.user_id)
        await repository.update_index_state(
            user_id=actor.user_id,
            agent_key=agentId,
            index_state=MemoryIndexState.REINDEXING,
            index_version=private_record.index_version,
        )
    try:
        response = await target_manager.rebuild_index()
    except RuntimeError as exc:
        if str(exc) == "Memory index rebuild is already running":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise
    except Exception:
        if private_record is not None:
            await repository.update_index_state(
                user_id=actor.user_id,
                agent_key=agentId,
                index_state=MemoryIndexState.REINDEX_FAILED,
                index_version=private_record.index_version,
            )
        raise

    if response is None:
        if private_record is not None:
            await repository.update_index_state(
                user_id=actor.user_id,
                agent_key=agentId,
                index_state=MemoryIndexState.REINDEX_FAILED,
                index_version=private_record.index_version,
            )
        raise HTTPException(
            status_code=503,
            detail="ReMe is not started or the reindex job failed",
        )
    if not response.success:
        if private_record is not None:
            await repository.update_index_state(
                user_id=actor.user_id,
                agent_key=agentId,
                index_state=MemoryIndexState.REINDEX_FAILED,
                index_version=private_record.index_version,
            )
        raise HTTPException(status_code=500, detail=str(response.answer))

    if private_record is not None:
        await repository.update_index_state(
            user_id=actor.user_id,
            agent_key=agentId,
            index_state=MemoryIndexState.READY,
            index_version=private_record.index_version + 1,
        )

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
    await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles=set(AgentResourceRole),
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
    await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles=set(AgentResourceRole),
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
    scope: MemoryScope = MemoryScope.PUBLIC,
) -> MemoryGraphSnapshot:
    """Return a frontend-ready graph snapshot from embedded ReMe."""
    config = await run_sync_io(load_config)
    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )
    access = await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles=set(AgentResourceRole),
    )

    agent_config = await run_sync_io(load_agent_config, agentId)
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

    target_manager = memory_manager
    if scope is MemoryScope.PRIVATE:
        actor = _request_actor(request)
        if (
            request.headers.get("X-Agent-Governance") == "runtime-config"
            or access is None
            or access.historical_read_only
        ):
            raise HTTPException(status_code=403, detail="forbidden")
        target_manager = await memory_manager.get_private_runtime(actor.user_id)
    response = await target_manager.graph_snapshot()
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
                node.relative_path = node_path[len(prefix) :]
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

    access = await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles={AgentResourceRole.OWNER},
    )

    manager = _get_multi_agent_manager(request)
    if manager.is_agent_startup_in_progress(agentId):
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{agentId}' cannot be deleted while starting",
        )

    if is_multi_user_enabled():
        repository = _get_agent_metadata_repository()
        await _register_legacy_preview(
            access=access,
            request=request,
            repository=repository,
        )
        references = await repository.reference_counts(agentId)
        await _get_agent_user_workspace_repository().mark_agent_cleanup_pending(
            agent_key=agentId,
        )
        await repository.set_status(agentId, "deleted")
        await manager.stop_agent(agentId)
        return {
            "success": True,
            "agent_id": agentId,
            "soft_deleted": True,
            "references": {
                key: value for key, value in references.as_dict().items() if value > 0
            },
        }

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

    access = await _require_agent_role(
        request=request,
        agent_id=agentId,
        allowed_roles={
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
        },
    )

    agent_ref = config.agents.profiles[agentId]
    manager = _get_multi_agent_manager(request)

    if not enabled and manager.is_agent_startup_in_progress(agentId):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Agent '{agentId}' is still starting and cannot be " "disabled yet"
            ),
        )

    if not enabled and getattr(agent_ref, "enabled", True):
        await manager.stop_agent(agentId)

    agent_ref.enabled = enabled
    save_config(config)

    if is_multi_user_enabled():
        repository = _get_agent_metadata_repository()
        await _register_legacy_preview(
            access=access,
            request=request,
            repository=repository,
        )
        await repository.set_status(
            agentId,
            "active" if enabled else "disabled",
        )

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
    (workspace_dir / "media").mkdir(exist_ok=True)
    ensure_artifacts_directory(workspace_dir)
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


def ensure_agent_workspace_md_files(
    agent_id: str,
    workspace_dir: Path | str,
) -> list[str]:
    """补齐旧 Agent 缺失的标准档案文件，且绝不覆盖已有内容。"""
    target = Path(workspace_dir).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    ensure_artifacts_directory(target)
    language = normalize_agent_language(load_agent_config(agent_id).language)
    bootstrap_existed = (target / "BOOTSTRAP.md").exists()
    copied = copy_workspace_md_files(
        language,
        target,
        only_if_missing=True,
    )
    if not bootstrap_existed and "BOOTSTRAP.md" in copied:
        (target / "BOOTSTRAP.md").unlink(missing_ok=True)
        copied.remove("BOOTSTRAP.md")
    return copied


def ensure_all_agent_workspace_md_files() -> int:
    """补齐当前运行目录中全部已登记 Agent 的缺失档案文件。"""
    repaired = 0
    for agent_id, reference in load_config().agents.profiles.items():
        copied = ensure_agent_workspace_md_files(
            agent_id,
            reference.workspace_dir,
        )
        if copied:
            repaired += 1
            logger.info(
                "Backfilled Agent workspace files for %s: %s",
                agent_id,
                ", ".join(copied),
            )
    return repaired
