# -*- coding: utf-8 -*-
"""Main Chat tools bound to a server-created, non-serialized invocation."""

from dataclasses import dataclass
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from .contracts import (
    TaskScope,
    TaskStoreError,
    canonical_json,
    content_digest,
)
from .routes import HostOrigins
from .runtime import HostTaskRuntime


@dataclass(frozen=True)
class TaskToolContext:
    runtime: HostTaskRuntime
    origins: HostOrigins
    principal_id: str
    workspace_id: str
    chat_id: str
    session_id: str
    continuation_id: str | None = None

    def scope(self, app_id: str) -> TaskScope:
        return TaskScope(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            app_id=app_id,
        )


async def bind_task_tools(request, workspace, chat, payload):
    """Only Console ingress may create this authority; JSON cannot carry it.

    Legacy Console identities remain usable for chat, but they do not acquire
    task authority when they differ from the authenticated principal.
    """
    payload.pop("_pawapp_task_context", None)
    runtime = getattr(request.app.state, "pawapp_tasks", None)
    origins = getattr(request.app.state, "pawapp_task_origins", None)
    if not isinstance(runtime, HostTaskRuntime) or not isinstance(
        origins,
        HostOrigins,
    ):
        return
    principal = str(getattr(request.state, "user", None) or "default")
    workspace_id = workspace.agent_id
    if (
        payload.get("sender_id") != principal
        or payload.get("channel_id") != "console"
    ):
        return
    if (
        chat.user_id != principal
        or chat.channel != "console"
        or chat.source != "chat"
        or chat.archived
    ):
        return
    if (
        chat.session_id.startswith("pawapp:")
        or chat.meta.get("pawapp") is not None
    ):
        return
    for header, query, expected in (
        ("X-User-Id", "user_id", principal),
        ("X-Channel", "channel", "console"),
        ("X-Agent-Id", "agent_id", workspace_id),
    ):
        if any(
            value != expected
            for value in (
                request.headers.getlist(header)
                + request.query_params.getlist(query)
            )
        ):
            return
    payload["_pawapp_task_context"] = TaskToolContext(
        runtime,
        origins,
        principal,
        workspace_id,
        chat.id,
        chat.session_id,
    )


def _result(payload, *, error=False):
    return ToolChunk(
        is_last=True,
        state=ToolResultState.ERROR if error else ToolResultState.SUCCESS,
        content=[TextBlock(text=canonical_json(payload))],
    )


def make_task_tools(context: TaskToolContext):
    """Fixed tool set; action schemas are returned on demand, never injected
    as one top-level tool per App action. Scope and return chat are closures.
    """

    async def list_apps(intent: str = "") -> ToolChunk:
        """List granted PawApp actions, optionally ranked by an intent hint.

        Returns short summaries. Call describe_action before delegate. An
        App task executes independently; submission does not mean completion.
        """
        try:
            actions = await context.runtime.catalog(
                context.principal_id,
                context.workspace_id,
                intent=intent,
            )
            return _result({"actions": actions})
        except TaskStoreError as exc:
            return _result({"state": "error", "reason": exc.code}, error=True)

    async def describe_action(app_id: str, action_id: str) -> ToolChunk:
        """Get a granted App action's full input schema and effects.

        Use the returned schema to construct delegate.inputs. Description
        does not execute an action or grant permission to execute it.
        """
        try:
            action = await context.runtime.describe(
                context.scope(app_id),
                action_id,
            )
            return _result(
                {
                    "action": action.model_dump(mode="json"),
                    "descriptor_digest": action.descriptor_digest,
                },
            )
        except (TaskStoreError, ValueError) as exc:
            return _result(
                {"state": "error", "reason": _reason(exc)},
                error=True,
            )

    async def delegate(
        app_id: str,
        action_id: str,
        inputs: dict[str, Any],
        request_id: str,
    ) -> ToolChunk:
        """Start an independent App task and return its durable handle.

        Args:
            app_id: App ID from list_apps.
            action_id: Action ID from describe_action.
            inputs: JSON object matching the described input schema.
            request_id: Unique key for this user intent (for example a UUID).
                Reuse exactly the same key and inputs on an uncertain retry.
                Use a new key for a new intentional task.

        A blocked response starts no work: guide the user to App settings and
        retry only after setup. Accepted means queued, not successful. The
        chat card follows progress. Use get_app_task for a later status/result
        request; do not poll repeatedly. Completion queues an automatic,
        tool-free summary in this Main Chat when it becomes idle.
        """
        try:
            scope = context.scope(app_id)
        except ValueError as exc:
            return _result(
                {"state": "error", "reason": _reason(exc)},
                error=True,
            )
        try:
            if not request_id or len(request_id) > 256:
                raise ValueError("invalid request identity")
            origin = await context.origins.resolve(
                scope,
                "delegated",
                context.chat_id,
            )
            result = await context.runtime.dispatch(
                scope,
                action_id,
                request_id="agent_"
                + content_digest(
                    (
                        [
                            context.chat_id,
                            context.continuation_id,
                            app_id,
                            action_id,
                            inputs,
                        ]
                        if context.continuation_id
                        else [context.chat_id, request_id]
                    ),
                ),
                inputs=inputs,
                origin=origin,
            )
            if result["state"] == "accepted":
                result["task"] = result["task"].model_dump(mode="json")
            return _result(
                {
                    "kind": "pawapp_task",
                    "app_id": app_id,
                    "workspace_id": context.workspace_id,
                    **result,
                },
            )
        except (TaskStoreError, ValueError) as exc:
            await context.runtime.store.audit(
                scope,
                action_id,
                "agent_dispatch",
                _reason(exc),
            )
            return _result(
                {"state": "error", "reason": _reason(exc)},
                error=True,
            )

    async def get_app_task(app_id: str, task_id: str) -> ToolChunk:
        """Read a task delegated from this chat; acceptance is not success.

        Returns current status and the latest text snapshot. Recovery states
        are uncertainty, not successful completion. Do not busy-poll.
        """
        try:
            submission = await context.runtime.get(
                context.scope(app_id),
                task_id,
            )
            if submission.handle.origin.origin_ref != context.chat_id:
                raise TaskStoreError("task_not_found")
            return _result(
                {
                    "kind": "pawapp_task",
                    "state": "accepted",
                    "app_id": app_id,
                    "workspace_id": context.workspace_id,
                    "task": submission.handle.model_dump(mode="json"),
                },
            )
        except (TaskStoreError, ValueError) as exc:
            return _result(
                {"state": "error", "reason": _reason(exc)},
                error=True,
            )

    async def open_app(app_id: str, task_id: str) -> ToolChunk:
        """Open the App project created by a task delegated from this chat.

        The Host returns a local, authenticated handoff. Use this after the
        task has published a project_ref; do not construct an App URL.
        """
        try:
            scope = context.scope(app_id)
            submission = await context.runtime.get(scope, task_id)
            if (
                submission.handle.origin.engagement != "delegated"
                or submission.handle.origin.origin_ref != context.chat_id
            ):
                raise TaskStoreError("task_not_found")
            action = await context.runtime.open_app(scope, task_id)
            return _result(
                {
                    "kind": "pawapp_open_app",
                    "app_id": app_id,
                    "workspace_id": context.workspace_id,
                    "action": action.model_dump(mode="json"),
                },
            )
        except (TaskStoreError, ValueError) as exc:
            return _result(
                {"state": "error", "reason": _reason(exc)},
                error=True,
            )

    async def answer_task(
        app_id: str,
        task_id: str,
        request_id: str,
        command_id: str,
        answers: list[dict[str, Any]],
    ) -> ToolChunk:
        """Answer the current input request for a delegated App task.

        Read request_id, exact question text and option labels from the task's
        input_request. Reuse command_id and identical answers on an uncertain
        retry. A stale request or changed retry is rejected without affecting
        another task.
        """
        try:
            scope = context.scope(app_id)
            submission = await context.runtime.get(scope, task_id)
            if (
                submission.handle.origin.engagement != "delegated"
                or submission.handle.origin.origin_ref != context.chat_id
            ):
                raise TaskStoreError("task_not_found")
            command = await context.runtime.answer(
                scope,
                task_id,
                command_id=command_id,
                request_id=request_id,
                answers=answers,
            )
            return _result(
                {
                    "kind": "pawapp_task_command",
                    "app_id": app_id,
                    "task_id": task_id,
                    "command": command.model_dump(mode="json"),
                },
                error=command.state in {"rejected", "unknown"},
            )
        except (TaskStoreError, ValueError) as exc:
            return _result(
                {"state": "error", "reason": _reason(exc)},
                error=True,
            )

    async def cancel_task(
        app_id: str,
        task_id: str,
        reason: str = "",
    ) -> ToolChunk:
        """Request cancellation of a delegated App task.

        Cancellation keeps existing output and follows the task's authoritative
        executor result. Repeated calls return the same durable receipt.
        """
        try:
            scope = context.scope(app_id)
            submission = await context.runtime.get(scope, task_id)
            if (
                submission.handle.origin.engagement != "delegated"
                or submission.handle.origin.origin_ref != context.chat_id
            ):
                raise TaskStoreError("task_not_found")
            command = await context.runtime.cancel(
                scope,
                task_id,
                reason=reason or None,
            )
            return _result(
                {
                    "kind": "pawapp_task_command",
                    "app_id": app_id,
                    "task_id": task_id,
                    "command": command.model_dump(mode="json"),
                },
                error=command.state in {"rejected", "unknown"},
            )
        except (TaskStoreError, ValueError) as exc:
            return _result(
                {"state": "error", "reason": _reason(exc)},
                error=True,
            )

    return [
        list_apps,
        describe_action,
        delegate,
        get_app_task,
        open_app,
        answer_task,
        cancel_task,
    ]


def _reason(exc):
    return (
        exc.code if isinstance(exc, TaskStoreError) else "invalid_task_request"
    )
