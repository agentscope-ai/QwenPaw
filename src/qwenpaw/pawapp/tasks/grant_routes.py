# -*- coding: utf-8 -*-
"""Authenticated Host settings routes for scoped PawApp task grants."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from ..deps import get_scoped_ctx
from .contracts import Contract, Identity, TaskScope, TaskStoreError
from .routes import _error, workspace_enabled

router = APIRouter(
    prefix="/pawapps/workspaces/{workspace_id}/task-grants",
    tags=["pawapp-task-grants"],
)


class GrantUpdate(Contract):
    expected_revision: Annotated[int, Field(ge=0)]
    enabled: bool
    input_values: dict[str, list[str]] = Field(default_factory=dict)


class CapabilityGrantUpdate(Contract):
    expected_revision: Annotated[int, Field(ge=0)]
    enabled: bool


class GrantManagementScope(Contract):
    principal_id: Identity
    workspace_id: Identity


async def grant_scope(
    request: Request,
    workspace_id: str,
) -> GrantManagementScope:
    request.state.app_id = "qwenpaw-host"
    ctx = await get_scoped_ctx(request)
    claims = (
        ("X-User-Id", "user_id", ctx.user_id),
        ("X-Channel", "channel", "console"),
        ("X-Agent-Id", "agent_id", workspace_id),
    )
    for header, query, expected in claims:
        values = request.headers.getlist(
            header,
        ) + request.query_params.getlist(query)
        if any(value != expected for value in values):
            raise HTTPException(status_code=403, detail="task_scope_mismatch")
    if getattr(request.app.state, "pawapp_tasks", None) is None:
        raise HTTPException(status_code=503, detail="task_runtime_unavailable")
    if not await workspace_enabled(workspace_id):
        raise HTTPException(status_code=403, detail="workspace_unavailable")
    try:
        return GrantManagementScope(
            principal_id=ctx.user_id,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise _error(exc) from None


ManagementScope = Annotated[GrantManagementScope, Depends(grant_scope)]


@router.get("")
async def list_task_grants(request: Request, scope: ManagementScope):
    try:
        return await request.app.state.pawapp_tasks.grant_catalog(
            scope.principal_id,
            scope.workspace_id,
        )
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.put("/actions/{app_id}/{action_id}")
async def update_task_grant(
    request: Request,
    app_id: str,
    action_id: str,
    body: GrantUpdate,
    scope: ManagementScope,
):
    try:
        task_scope = TaskScope(
            principal_id=scope.principal_id,
            workspace_id=scope.workspace_id,
            app_id=app_id,
        )
        return await request.app.state.pawapp_tasks.set_action_grant(
            task_scope,
            action_id,
            enabled=body.enabled,
            input_values=body.input_values,
            expected_revision=body.expected_revision,
        )
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.put("/capabilities/{app_id}/{capability_id}")
async def update_task_capability_grant(
    request: Request,
    app_id: str,
    capability_id: str,
    body: CapabilityGrantUpdate,
    scope: ManagementScope,
):
    try:
        task_scope = TaskScope(
            principal_id=scope.principal_id,
            workspace_id=scope.workspace_id,
            app_id=app_id,
        )
        return await request.app.state.pawapp_tasks.set_capability_grant(
            task_scope,
            capability_id,
            enabled=body.enabled,
            expected_revision=body.expected_revision,
        )
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None
