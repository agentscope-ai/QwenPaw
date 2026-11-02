# -*- coding: utf-8 -*-
"""Host task API. Scope comes from authentication, path and owned ChatSpec."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import Field, model_validator

from ..deps import get_scoped_ctx
from .contracts import (
    ApprovalDecision,
    Contract,
    Engagement,
    Identity,
    TaskOrigin,
    TaskAnswer,
    TaskScope,
    TaskStoreError,
)

router = APIRouter(
    prefix="/pawapps/{app_id}/workspaces/{workspace_id}",
    tags=["pawapp-tasks"],
)


class DispatchRequest(Contract):
    request_id: Identity
    chat_id: Identity
    engagement: Engagement
    inputs: dict


class AnswerTaskRequest(Contract):
    command_id: Identity
    request_id: Identity
    answers: tuple[TaskAnswer, ...]


class DecideTaskRequest(Contract):
    command_id: Identity
    decision: ApprovalDecision


class InspectApprovalRequest(Contract):
    request_id: Identity | None = None
    subject_digest: (
        Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")] | None
    ) = None

    @model_validator(mode="after")
    def validate_reference(self):
        if (self.request_id is None) != (self.subject_digest is None):
            raise ValueError(
                "approval identity and digest are required together",
            )
        return self


class DirectDispatchRequest(Contract):
    request_id: Identity
    app_session_id: Identity = "default"
    inputs: dict


class CancelTaskRequest(Contract):
    reason: Annotated[str, Field(max_length=2000)] | None = None


class HostOrigins:
    def __init__(self, manager, enabled):
        self.manager = manager
        self.enabled = enabled
        self._direct_lock = asyncio.Lock()

    async def direct(self, scope, app_session_id):
        from .contracts import content_digest

        identity = content_digest(
            {
                "scope": scope.model_dump(mode="json"),
                "session": app_session_id,
            },
        )
        return await self.ensure_direct(
            scope,
            session_ref=f"pawapp:{scope.app_id}:session:{identity}",
            chat_id="pawapp_" + identity,
            name=scope.app_id,
        )

    async def ensure_direct(self, scope, *, session_ref, chat_id, name):
        """Register a native origin with its existing identity."""
        from ...app.chats.models import ChatSpec

        if not await self.enabled(scope.workspace_id):
            raise TaskStoreError("workspace_unavailable")
        async with self._direct_lock:
            workspace = await self.manager.get_agent(scope.workspace_id)
            if await workspace.chat_manager.get_chat(chat_id) is None:
                await workspace.chat_manager.create_chat(
                    ChatSpec(
                        id=chat_id,
                        session_id=session_ref,
                        user_id=scope.principal_id,
                        channel="console",
                        name=name[:60],
                        meta={
                            "pawapp": {
                                "app_id": scope.app_id,
                                "agent_id": scope.workspace_id,
                            },
                        },
                    ),
                )
        return await self.resolve(scope, "direct", chat_id)

    async def resolve(self, scope, engagement, chat_id):
        if not await self.enabled(scope.workspace_id):
            raise TaskStoreError("workspace_unavailable")
        workspace = await self.manager.get_agent(scope.workspace_id)
        chat = await workspace.chat_manager.get_chat(chat_id)
        if (
            chat is None
            or chat.user_id != scope.principal_id
            or chat.channel != "console"
            or chat.archived
            or chat.source != "chat"
        ):
            raise TaskStoreError("origin_not_found")
        owner = chat.meta.get("pawapp")
        if engagement == "direct":
            namespace = f"pawapp:{scope.app_id}"
            if (
                not isinstance(owner, dict)
                or owner.get("app_id") != scope.app_id
                or owner.get("agent_id") != scope.workspace_id
                or not (
                    chat.session_id == namespace
                    or chat.session_id.startswith(namespace + ":")
                )
            ):
                raise TaskStoreError("origin_not_found")
            return TaskOrigin(
                engagement="direct",
                origin_ref=chat.id,
                app_session_ref=chat.session_id,
            )
        if owner is not None or chat.session_id.startswith("pawapp:"):
            raise TaskStoreError("origin_not_found")
        return TaskOrigin(
            engagement="delegated",
            origin_ref=chat.id,
            return_session_ref=chat.session_id,
        )

    async def __call__(self, scope, origin):
        expected = await self.resolve(
            scope,
            origin.engagement,
            origin.origin_ref,
        )
        if origin != expected:
            raise TaskStoreError("origin_not_found")


async def workspace_enabled(workspace_id):
    from ...config.utils import load_config

    config = await asyncio.to_thread(load_config)
    profile = config.agents.profiles.get(workspace_id)
    return profile is not None and getattr(profile, "enabled", True)


def _error(exc):
    code = (
        exc.code if isinstance(exc, TaskStoreError) else "invalid_task_request"
    )
    status = 409
    if code in {
        "task_not_found",
        "action_not_found",
        "origin_not_found",
        "handoff_not_found",
        "setup_request_not_found",
    }:
        status = 404
    elif code in {"action_forbidden", "workspace_unavailable"}:
        status = 403
    elif code in {
        "task_policy_unavailable",
        "task_runtime_closed",
        "handoff_store_unavailable",
        "setup_runtime_unavailable",
    }:
        status = 503
    elif code == "invalid_grant_constraints":
        status = 422
    elif isinstance(exc, ValueError):
        status = 422
    return HTTPException(status_code=status, detail=code)


async def task_scope(request: Request, app_id: str, workspace_id: str):
    request.state.app_id = app_id
    ctx = await get_scoped_ctx(request)
    # Reject *each* contradictory claim, including a header hidden by a query.
    claims = (
        ("X-User-Id", "user_id", ctx.user_id),
        ("X-Channel", "channel", "console"),
        ("X-Agent-Id", "agent_id", workspace_id),
        ("X-PawApp-Id", "app_id", app_id),
    )
    for header, query, expected in claims:
        values = request.headers.getlist(
            header,
        ) + request.query_params.getlist(query)
        if any(value != expected for value in values):
            raise HTTPException(status_code=403, detail="task_scope_mismatch")
    if getattr(request.app.state, "pawapp_tasks", None) is None:
        raise HTTPException(status_code=503, detail="task_runtime_unavailable")
    try:
        return TaskScope(
            principal_id=ctx.user_id,
            workspace_id=workspace_id,
            app_id=app_id,
        )
    except ValueError as exc:
        raise _error(exc) from None


Scope = Annotated[TaskScope, Depends(task_scope)]


@router.post("/actions/{action_id}/direct-tasks")
async def dispatch_direct(
    request: Request,
    action_id: str,
    scope: Scope,
    body: DirectDispatchRequest,
):
    from .client import ScopedTasks

    try:
        client = ScopedTasks(
            request.app.state.pawapp_tasks,
            request.app.state.pawapp_task_origins,
            scope,
        )
        result = await client.dispatch(
            action_id,
            body.inputs,
            request_id=body.request_id,
            app_session_id=body.app_session_id,
        )
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=202 if result["state"] == "accepted" else 200,
        )
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.get("/actions/{action_id}")
async def describe_action(request: Request, action_id: str, scope: Scope):
    try:
        action = await request.app.state.pawapp_tasks.describe(
            scope,
            action_id,
        )
        return {
            "action": action,
            "descriptor_digest": action.descriptor_digest,
        }
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


async def _dispatch(request, action_id, scope, body, *, prepare):
    runtime = request.app.state.pawapp_tasks
    try:
        # Check the grant before looking up caller-supplied chat IDs.
        await runtime.describe(scope, action_id)
        origin = await request.app.state.pawapp_task_origins.resolve(
            scope,
            body.engagement,
            body.chat_id,
        )
        result = await runtime.dispatch(
            scope,
            action_id,
            request_id=body.request_id,
            inputs=body.inputs,
            origin=origin,
            prepare=prepare,
        )
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=202 if result["state"] == "accepted" else 200,
        )
    except (TaskStoreError, ValueError) as exc:
        await runtime.store.audit(
            scope,
            action_id,
            "prepare" if prepare else "dispatch",
            exc.code if isinstance(exc, TaskStoreError) else "invalid_request",
            request_id=body.request_id,
        )
        raise _error(exc) from None


@router.post("/actions/{action_id}/prepare")
async def prepare_action(
    request: Request,
    action_id: str,
    scope: Scope,
    body: DispatchRequest,
):
    return await _dispatch(request, action_id, scope, body, prepare=True)


@router.post("/actions/{action_id}/tasks")
async def dispatch_action(
    request: Request,
    action_id: str,
    scope: Scope,
    body: DispatchRequest,
):
    return await _dispatch(request, action_id, scope, body, prepare=False)


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str, scope: Scope):
    try:
        submission = await request.app.state.pawapp_tasks.get(scope, task_id)
        return {"task": submission.handle}
    except TaskStoreError as exc:
        raise _error(exc) from None


@router.post("/tasks/{task_id}/open")
async def open_task_app(
    request: Request,
    task_id: str,
    scope: Scope,
    body: InspectApprovalRequest | None = None,
):
    try:
        action = await request.app.state.pawapp_tasks.open_app(
            scope,
            task_id,
            **(
                {"approval": body}
                if body is not None and body.request_id is not None
                else {}
            ),
        )
        return {"action": action}
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.get("/handoffs/{handoff_id}")
async def resolve_handoff(request: Request, handoff_id: str, scope: Scope):
    try:
        handoff = await request.app.state.pawapp_tasks.resolve_handoff(
            scope,
            handoff_id,
        )
        return {"handoff": handoff}
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.post("/tasks/{task_id}/answer")
async def answer_task(
    request: Request,
    task_id: str,
    scope: Scope,
    body: AnswerTaskRequest,
):
    try:
        command = await request.app.state.pawapp_tasks.answer(
            scope,
            task_id,
            command_id=body.command_id,
            request_id=body.request_id,
            user_interface=True,
            answers=[
                answer.model_dump(mode="json") for answer in body.answers
            ],
        )
        return {"command": command}
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.post("/tasks/{task_id}/decide")
async def decide_task(
    request: Request,
    task_id: str,
    scope: Scope,
    body: DecideTaskRequest,
):
    try:
        command = await request.app.state.pawapp_tasks.decide(
            scope,
            task_id,
            command_id=body.command_id,
            decision=body.decision,
        )
        return {"command": command}
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    request: Request,
    task_id: str,
    scope: Scope,
    body: CancelTaskRequest,
):
    try:
        command = await request.app.state.pawapp_tasks.cancel(
            scope,
            task_id,
            reason=body.reason,
        )
        return {"command": command}
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


@router.get("/tasks/{task_id}/events")
async def get_task_events(
    request: Request,
    task_id: str,
    scope: Scope,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    runtime = request.app.state.pawapp_tasks
    try:
        await runtime.get_authorized(scope, task_id)
        return {
            "events": await runtime.store.events(
                scope,
                task_id,
                after=after,
                limit=limit,
            ),
        }
    except TaskStoreError as exc:
        raise _error(exc) from None
