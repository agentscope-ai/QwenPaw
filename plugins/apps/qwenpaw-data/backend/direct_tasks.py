"""Native Data Console admission through the same durable Host boundary."""

from __future__ import annotations

import asyncio
import re

from fastapi import HTTPException, Request

from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.pawapp.tasks import TaskStoreError, ExecutorRunRef, TaskAnswer
from qwenpaw.pawapp.tasks.contracts import content_digest
from qwenpaw.pawapp.tasks.routes import task_scope, _error

from .task_bridge import DataTaskAdapter


async def console_scope(request: Request):
    workspace = request.headers.get("X-Agent-Id", "default")
    return await task_scope(request, "qwenpaw-data", workspace)


async def dispatch_console_chat(request: Request, gateway):
    """Persist first; never fall back to a raw Engine chat after uncertainty."""
    scope = await console_scope(request)
    runtime = request.app.state.pawapp_tasks
    request_id = request.headers.get("X-Request-Id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
        raise HTTPException(422, "A stable X-Request-Id is required")
    try:
        inputs = await request.json()
    except ValueError:
        raise HTTPException(422, "Invalid JSON analysis inputs") from None
    if not isinstance(inputs, dict):
        raise HTTPException(422, "Invalid analysis inputs")
    # Console-only hints are not silently accepted as analysis constraints.
    if (
        inputs.get("dataset_names")
        or inputs.get("enable_clarification") is False
    ):
        raise HTTPException(
            422,
            "Dataset filtering and disabled clarification are not supported by this Engine",
        )
    inputs.pop("dataset_names", None)
    inputs.pop("enable_clarification", None)
    try:
        action = await runtime.describe(scope, "analyze-session")
        action.validate_inputs(inputs)
        namespace = "pawapp:qwenpaw-data:engine:" + content_digest(
            {
                "scope": scope.model_dump(mode="json"),
                "session_id": inputs["session_id"],
            }
        )
        origins = request.app.state.pawapp_task_origins
        if not await origins.enabled(scope.workspace_id):
            raise TaskStoreError("workspace_unavailable")
        workspace = await origins.manager.get_agent(scope.workspace_id)
        chat_id = "pawdata_" + content_digest({"session": namespace})
        chat = await workspace.chat_manager.get_chat(chat_id)
        if chat is None:
            await workspace.chat_manager.create_chat(
                ChatSpec(
                    id=chat_id,
                    session_id=namespace,
                    user_id=scope.principal_id,
                    channel="console",
                    name=inputs["text"][:60],
                    meta={
                        "pawapp": {
                            "app_id": scope.app_id,
                            "agent_id": scope.workspace_id,
                        }
                    },
                )
            )
        origin = await origins.resolve(scope, "direct", chat_id)
        result = await runtime.dispatch(
            scope,
            "analyze-session",
            request_id="console_" + request_id,
            inputs=inputs,
            origin=origin,
        )
        if result["state"] != "accepted":
            if result.get("reason") == "session_unavailable":
                raise HTTPException(
                    409,
                    "This Data session is not available in the current workspace; start a new session",
                )
            if result.get("reason") == "session_busy":
                raise HTTPException(
                    409, "This Data session already has a running turn"
                )
            raise HTTPException(
                409, "Analysis setup is required in Data settings"
            )
        handle = result["task"]
        # Only wait for admission, not model completion. Retrying the same
        # request returns this task even when its first HTTP response was lost.
        for _ in range(100):
            if handle.executor_run_ref is not None:
                run = handle.executor_run_ref
                payload = await gateway.json(
                    "GET",
                    f"/api/v1/sessions/{run.session_id}/chats/{run.run_id}",
                    user_id=DataTaskAdapter.identity_namespace(scope),
                )
                payload["task_id"] = handle.task_id
                return payload
            if handle.status in {"failed", "cancelled", "interrupted"}:
                raise HTTPException(
                    409,
                    "Analysis could not start; inspect the task or start a new Data session",
                )
            await asyncio.sleep(0.1)
            handle = (await runtime.get(scope, handle.task_id)).handle
        raise HTTPException(
            503,
            "Analysis admission is pending; retry with the same request ID",
        )
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None


async def command_console_chat(
    request: Request, gateway, session_id: str, run_id: str, kind: str
):
    scope = await console_scope(request)
    runtime = request.app.state.pawapp_tasks
    try:
        submission = await runtime.store.find_run(
            scope,
            ExecutorRunRef(
                executor_id="qwenpaw-data.engine",
                session_id=session_id,
                run_id=run_id,
            ),
        )
        task_id = submission.handle.task_id
        if submission.handle.origin.engagement != "direct":
            raise HTTPException(
                409,
                "This delegated task is controlled from its originating Main Chat",
            )
        if kind == "cancel":
            command = await runtime.cancel(scope, task_id)
        else:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(
                body.get("clarification_id"), str
            ):
                raise HTTPException(422, "A clarification ID is required")
            result = body.get("result", {})
            if (
                not isinstance(result, dict)
                or result.get("status") != "answered"
            ):
                raise HTTPException(
                    422, "An explicit clarification answer is required"
                )
            if not isinstance(result.get("answers"), list):
                raise HTTPException(
                    422, "Explicit clarification answers are required"
                )
            answers = tuple(
                TaskAnswer.model_validate(item)
                for item in result.get("answers", [])
            )
            command = await runtime.answer(
                scope,
                task_id,
                command_id="console_" + content_digest(body),
                request_id=body["clarification_id"],
                answers=answers,
            )
        if command.state != "accepted":
            raise HTTPException(
                409,
                f"Task command is {command.state}; refresh before retrying",
            )
        return await gateway.json(
            "GET",
            f"/api/v1/sessions/{session_id}/chats/{run_id}",
            user_id=DataTaskAdapter.identity_namespace(scope),
        )
    except (TaskStoreError, ValueError) as exc:
        raise _error(exc) from None
