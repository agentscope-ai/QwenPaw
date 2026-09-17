"""Safe skill catalog and explicit administrator publication governance."""

from pathlib import Path
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from ...access.dependencies import get_actor
from ...access.service import AuthorizationDeniedError
from ...exceptions import SkillScanError
from ...persistence.database import DatabaseUnavailableError
from ...persistence.settings import DatabaseConfigurationError
from ...skills.runtime import get_skill_service, get_skill_lifecycle_service
from ...skills.service import SkillGovernanceService
from ...skills.snapshots import validate_name
from ..utils import schedule_agent_reload


class SkillAuthorityRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except AuthorizationDeniedError as exc:
                raise HTTPException(403, "forbidden") from exc
            except (
                SQLAlchemyError,
                OSError,
                DatabaseUnavailableError,
                DatabaseConfigurationError,
            ) as exc:
                raise HTTPException(503, "skill_authority_unavailable") from exc
            except SkillScanError as exc:
                raise HTTPException(422, "skill_security_scan_failed") from exc
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

        return guarded


router = APIRouter(tags=["skill-governance"], route_class=SkillAuthorityRoute)


def require_manage(actor=Depends(get_actor)):
    SkillGovernanceService.require_manage(actor)
    return actor


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InitializationItem(StrictBody):
    name: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Initialization(StrictBody):
    items: list[InitializationItem]


class Enabled(StrictBody):
    enabled: bool


class Submission(StrictBody):
    agent_id: str
    skill_name: str


class Review(StrictBody):
    decision: Literal["approve", "reject"]
    expected_version: int = Field(ge=0)
    note: str = Field(default="", max_length=4000)


class SkillLoad(StrictBody):
    agent_id: str
    skill_id: UUID
    overwrite: bool = False
    expected_content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class SkillConfirmation(StrictBody):
    agent_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class SkillBroadcast(StrictBody):
    agent_ids: list[str] = Field(min_length=1)
    overwrite: bool = False
    preview_only: bool = False
    confirmations: dict[str, "BroadcastConfirmation"] = Field(default_factory=dict)


class BroadcastConfirmation(StrictBody):
    expected_content_hash: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    expected_version_id: str


@router.post("/skill-governance/items/{skill_id}/broadcast")
async def broadcast_skill(
    request: Request,
    skill_id: UUID,
    body: SkillBroadcast,
    actor=Depends(require_manage),
):
    result = await get_skill_lifecycle_service().broadcast(
        actor,
        skill_id,
        body.agent_ids,
        overwrite=body.overwrite,
        preview_only=body.preview_only,
        confirmations={key: value.model_dump() for key, value in body.confirmations.items()},
    )
    for row in result["results"]:
        if row["status"] == "updated":
            schedule_agent_reload(request, row["agent_id"])
    return result


@router.get("/agent-skills")
async def installed_skills(agent_id: str, actor=Depends(get_actor)):
    return await get_skill_lifecycle_service().list_installed(actor, agent_id)


@router.post("/agent-skills/load")
async def load_skill(request: Request, body: SkillLoad, actor=Depends(get_actor)):
    result = await get_skill_lifecycle_service().install(
        actor,
        body.agent_id,
        body.skill_id,
        overwrite=body.overwrite,
        expected_content_hash=body.expected_content_hash,
    )
    schedule_agent_reload(request, body.agent_id)
    return result


@router.post("/agent-skills/{skill_name}/update")
async def update_skill(
    request: Request, skill_name: str, body: SkillConfirmation, actor=Depends(get_actor)
):
    result = await get_skill_lifecycle_service().update(
        actor, body.agent_id, skill_name, body.expected_content_hash
    )
    schedule_agent_reload(request, body.agent_id)
    return result


@router.post("/agent-skills/{skill_name}/restore")
async def restore_skill(
    request: Request, skill_name: str, body: SkillConfirmation, actor=Depends(get_actor)
):
    result = await get_skill_lifecycle_service().restore(
        actor, body.agent_id, skill_name, body.expected_content_hash
    )
    schedule_agent_reload(request, body.agent_id)
    return result


@router.get("/skill-catalog")
async def catalog(agent_id: str, actor=Depends(get_actor)):
    return await get_skill_service().list_catalog(actor, agent_id)


@router.post("/skill-governance/initialization/preview")
async def preview(actor=Depends(require_manage)):
    return {"items": await get_skill_service().preview_existing(actor)}


@router.post("/skill-governance/initialization/import")
async def initialize(body: Initialization, actor=Depends(require_manage)):
    return await get_skill_service().import_existing(
        actor, [item.model_dump() for item in body.items]
    )


@router.get("/skill-governance/items")
async def items(actor=Depends(require_manage)):
    return {"items": await get_skill_service().repository.list_items()}


@router.patch("/skill-governance/items/{skill_id}/status")
async def status(skill_id: UUID, body: Enabled, actor=Depends(require_manage)):
    return await get_skill_service().set_item_status(actor, skill_id, body.enabled)


@router.get("/skill-governance/items/{skill_id}/agent-grants")
async def grants(skill_id: UUID, actor=Depends(require_manage)):
    from ...config.utils import load_config
    from ...access.agent_repository import agent_database_id

    names = {str(agent_database_id(key)): key for key in load_config().agents.profiles}
    rows = await get_skill_service().repository.list_grants(skill_id)
    return {
        "grants": [
            {
                **row,
                "agent_database_id": str(row["agent_id"]),
                "agent_id": names.get(str(row["agent_id"])),
            }
            for row in rows
        ]
    }


@router.put("/skill-governance/items/{skill_id}/agent-grants/{agent_id}")
async def grant(
    skill_id: UUID, agent_id: str, body: Enabled, actor=Depends(require_manage)
):
    return await get_skill_service().set_agent_grant(
        actor, skill_id, agent_id, body.enabled
    )


@router.get("/skill-governance/requests")
async def requests(actor=Depends(require_manage)):
    return {"requests": await get_skill_service().repository.list_requests()}


@router.post("/skill-governance/requests")
async def submit(body: Submission, actor=Depends(get_actor)):
    from ...config.utils import load_config
    from ...agents.skill_system.store import get_workspace_skills_dir

    service = get_skill_service()
    # Resolve fresh DB authority for the exact body Agent, never a cached header Agent.
    await service.require_agent_editor(actor, body.agent_id, owner_only=True)
    name = validate_name(body.skill_name)
    profile = load_config().agents.profiles.get(body.agent_id)
    if profile is None or not getattr(profile, "enabled", True):
        raise AuthorizationDeniedError()
    return await service.submit_request(
        actor,
        body.agent_id,
        name,
        get_workspace_skills_dir(Path(profile.workspace_dir)) / name,
    )


@router.post("/skill-governance/requests/{request_id}/review")
async def review(
    request: Request, request_id: UUID, body: Review, actor=Depends(require_manage)
):
    result = await get_skill_service().review_request(
        actor, request_id, body.decision, body.expected_version, body.note
    )
    if result["status"] == "approved":
        from .skills import _follow_auto_update

        await _follow_auto_update(request=request)
    return result


@router.get("/skill-governance/requests/{request_id}")
async def request_detail(request_id: UUID, actor=Depends(require_manage)):
    return await get_skill_service().request_detail(actor, request_id)


@router.get("/skill-governance/requests/{request_id}/files/{file_path:path}")
async def request_file(request_id: UUID, file_path: str, actor=Depends(require_manage)):
    return await get_skill_service().request_file(actor, request_id, file_path)
