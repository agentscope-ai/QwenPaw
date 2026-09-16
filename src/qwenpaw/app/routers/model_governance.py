"""Credential-free model catalog and explicit administrator governance."""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel

from ...access.dependencies import get_actor
from ...access.service import AuthorizationDeniedError
from ...identity.runtime import is_multi_user_enabled
from ...models.runtime import (
    get_model_service,
    conversation_override,
    persist_selection,
    resolve_selection,
)
from ...config.config import ModelSlotConfig, load_agent_config
from ..agent_context import get_agent_for_request


class ModelAuthorityRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except (SQLAlchemyError, OSError) as exc:
                raise HTTPException(
                    status_code=503, detail="model_authority_unavailable"
                ) from exc

        return guarded


router = APIRouter(tags=["model-governance"], route_class=ModelAuthorityRoute)


def require_manage(actor=Depends(get_actor)):
    from ...models.governance import ModelGovernanceService

    try:
        ModelGovernanceService.require_manage(actor)
    except AuthorizationDeniedError as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    return actor


def service(request):
    return get_model_service(request.app.state.provider_manager)


def require_database():
    if not is_multi_user_enabled():
        raise HTTPException(status_code=409, detail="postgres_governance_required")


@router.get("/model-governance/status")
async def status(request: Request, actor=Depends(require_manage)):
    return await service(request).repository.get_status()


@router.post("/model-governance/import/preview")
async def preview(request: Request, actor=Depends(require_manage)):
    return await service(request).preview_import(
        actor, request.app.state.provider_manager
    )


@router.post("/model-governance/import")
async def import_metadata(request: Request, actor=Depends(require_manage)):
    require_database()
    return await service(request).import_metadata(
        actor, request.app.state.provider_manager
    )


@router.get("/model-governance/models")
async def models(request: Request, actor=Depends(require_manage)):
    require_database()
    return await service(request).repository.list_models()


class Enabled(BaseModel):
    enabled: bool


@router.put("/model-governance/models/{model_id}/users/{user_id}")
async def grant(
    request: Request,
    model_id: UUID,
    user_id: UUID,
    body: Enabled,
    actor=Depends(require_manage),
):
    require_database()
    try:
        return await service(request).set_user_grant(
            actor, model_id, user_id, body.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/model-governance/models/{model_id}/status")
async def model_status(
    request: Request, model_id: UUID, body: Enabled, actor=Depends(require_manage)
):
    require_database()
    try:
        return await service(request).set_model_status(actor, model_id, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class Enforcement(Enabled):
    expected_version: int
    reason: str


@router.put("/model-governance/enforcement")
async def enforcement(
    request: Request, body: Enforcement, actor=Depends(require_manage)
):
    require_database()
    try:
        return await service(request).set_enforced(
            actor, body.enabled, body.expected_version, body.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/model-governance/enforcement/preview")
async def enforcement_preview(request: Request, actor=Depends(require_manage)):
    require_database()
    from ...config.utils import load_config

    manager = request.app.state.provider_manager
    defaults = []
    global_slot = manager.get_active_model()
    if global_slot:
        defaults.append({"agent_id": None, **global_slot.model_dump()})
    for agent_id in load_config().agents.profiles:
        slot = load_agent_config(agent_id).active_model
        if slot:
            defaults.append({"agent_id": agent_id, **slot.model_dump()})
    return await service(request).preview_enforcement(actor, defaults)


@router.get("/model-catalog")
async def catalog(
    request: Request, agent_id: str | None = None, actor=Depends(get_actor)
):
    if agent_id:
        await get_agent_for_request(request, agent_id)
    return await service(request).list_catalog(actor, agent_id)


@router.get("/model-catalog/default")
async def default_model(
    request: Request, agent_id: str | None = None, actor=Depends(get_actor)
):
    svc = service(request)
    if agent_id:
        await get_agent_for_request(request, agent_id)
    config = (
        load_agent_config(agent_id)
        if agent_id
        else type("Inherited", (), {"active_model": None})()
    )
    try:
        return await resolve_selection(svc, actor, agent_id, config, svc.manager, None)
    except Exception as exc:
        from ...exceptions import ProviderError

        if not isinstance(exc, (ValueError, ProviderError)):
            raise
        if getattr(config, "active_model", None) or svc.manager.get_active_model():
            raise HTTPException(
                status_code=403, detail="explicit_model_unavailable"
            ) from exc
        return {
            "active_llm": None,
            "source": "agent" if agent_id else "platform",
            "model_override": None,
            "effective_max_input_length": None,
            "locked": False,
        }


async def owned_context(request, chat_id):
    from ..chats.api import _require_writable_chat

    workspace = await get_agent_for_request(request)
    chat = await _require_writable_chat(
        request, workspace.chat_manager, workspace, chat_id
    )
    return workspace, chat


@router.get("/chats/{chat_id}/model")
async def chat_model(request: Request, chat_id: str, actor=Depends(get_actor)):
    workspace, chat = await owned_context(request, chat_id)
    svc = service(request)
    try:
        override = await conversation_override(svc, actor, workspace, chat)
        return await resolve_selection(
            svc,
            actor,
            workspace.agent_id,
            load_agent_config(workspace.agent_id),
            svc.manager,
            override,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put("/chats/{chat_id}/model")
async def select_model(request: Request, chat_id: str, actor=Depends(get_actor)):
    try:
        raw = await request.json()
        body = ModelSlotConfig.model_validate(raw) if raw is not None else None
        if body is not None and (not body.provider_id or not body.model):
            raise ValueError("invalid_model_override")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_model_override") from exc
    workspace, chat = await owned_context(request, chat_id)
    svc = service(request)
    # A running turn retains its validated slot; changes take effect on the next turn.
    selection = body.model_dump() if body else None
    try:
        resolved = await resolve_selection(
            svc,
            actor,
            workspace.agent_id,
            load_agent_config(workspace.agent_id),
            svc.manager,
            selection,
        )
        await persist_selection(svc, actor, workspace, chat, selection)
        return resolved
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
