# -*- coding: utf-8 -*-
"""Authenticated Host routes for durable PawApp setup requests."""

from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field

from ..tasks.contracts import (
    Contract,
    Engagement,
    Identity,
    ProjectRef,
    TaskStoreError,
)
from ..tasks.routes import Scope, _error
from .contracts import SetupPresentation, SuggestedValue

router = APIRouter(
    prefix="/pawapps/{app_id}/workspaces/{workspace_id}",
    tags=["pawapp-setup"],
)


class StartSetupRequest(Contract):
    chat_id: Identity
    engagement: Engagement
    inputs: dict
    entry_id: Identity | None = None
    requirement_ids: tuple[Identity, ...] = ()
    presentation: SetupPresentation
    project_ref: ProjectRef | None = None
    plan_digest: Identity | None = None
    expected_revisions: dict[Identity, int] = Field(default_factory=dict)
    scopes: tuple[Identity, ...] = ()
    suggested_values: tuple[SuggestedValue, ...] = ()
    expires_in_seconds: int = Field(default=900, ge=60, le=3600)


def _payload(record) -> dict:
    return {
        "request": record.request,
        "open_action": record.open_action,
        "result": record.result,
    }


@router.post("/actions/{action_id}/setup-requests")
async def start_setup(
    request: Request,
    action_id: str,
    scope: Scope,
    body: StartSetupRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ],
):
    runtime = request.app.state.pawapp_tasks
    try:
        await runtime.describe(scope, action_id)
        origin = await request.app.state.pawapp_task_origins.resolve(
            scope,
            body.engagement,
            body.chat_id,
        )
        record, replayed = await runtime.create_setup_request(
            scope,
            action_id,
            idempotency_key=idempotency_key,
            inputs=body.inputs,
            origin=origin,
            presentation=body.presentation,
            entry_id=body.entry_id,
            requirement_ids=body.requirement_ids,
            project_ref=body.project_ref,
            plan_digest=body.plan_digest,
            expected_revisions=body.expected_revisions,
            scopes=body.scopes,
            suggested_values=body.suggested_values,
            expires_in_seconds=body.expires_in_seconds,
        )
        return JSONResponse(
            content=jsonable_encoder(_payload(record)),
            status_code=200 if replayed else 201,
            headers={"X-Idempotent-Replay": str(replayed).lower()},
        )
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.get("/setup-requests/{request_id}")
async def get_setup(request: Request, request_id: str, scope: Scope):
    try:
        record = await request.app.state.pawapp_setup.get(scope, request_id)
        return _payload(record)
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.post("/setup-requests/{request_id}/open")
async def open_setup(request: Request, request_id: str, scope: Scope):
    try:
        record = await request.app.state.pawapp_setup.open(scope, request_id)
        return _payload(record)
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.post("/setup-requests/{request_id}/cancel")
async def cancel_setup(request: Request, request_id: str, scope: Scope):
    try:
        record = await request.app.state.pawapp_setup.cancel(
            scope,
            request_id,
        )
        return _payload(record)
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None
