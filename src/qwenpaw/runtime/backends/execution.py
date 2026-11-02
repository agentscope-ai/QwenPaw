# -*- coding: utf-8 -*-
"""Workspace-owned execution of lazily registered harness backends."""

# Execution bridges the registry's private owner and SDK admission state.
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...plugins.errors import SDKError, StaleContextError
from ...plugins.activity import PluginBusyError
from ...plugins.harnesses import (
    HarnessApprovalSummary,
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessCallContext,
    HarnessContext,
    HarnessEvent,
    HarnessEventKind,
    HarnessHistoryItem,
    HarnessOperationNotSupportedError,
    HarnessRunRequest,
)
from ...plugins.storage import PluginStorage
from ...schemas import AgentResponse, ContentType, MessageType, RunStatus
from ...utils.io_utils import run_async_to_completion, run_sync_io
from .session import HarnessSessionBridge
from .streaming import TextStream, ToolStream


logger = logging.getLogger(__name__)


@dataclass
class _Instance:
    entry: Any
    settings: dict
    backend: Any
    context: HarnessContext
    closed: bool = False
    failed: bool = False
    tasks: dict = field(default_factory=dict)


class BackendExecution:
    """Keep instance lifetime separate from the identity of each invocation."""

    def __init__(
        self,
        workspace_dir: Path,
        session=None,
        agent_id="default",
        workspace=None,
        registry=None,
    ):
        if registry is None:
            from ...plugins.registry import PluginRegistry

            registry = PluginRegistry().backend_registry
        self._registry = registry
        self._workspace_dir = Path(workspace_dir)
        self._workspace = workspace
        self._agent_id = agent_id
        self._instances = {}
        self._lock = asyncio.Lock()
        self._session_bridge = (
            HarnessSessionBridge(session) if session is not None else None
        )
        self._resolver = None
        self._closed = False

    def _entry(self, backend_id):
        if self._closed:
            raise StaleContextError("Workspace backend runtime is closed")
        try:
            entry = self._registry.get(backend_id)
        except StaleContextError as exc:
            raise StaleContextError(
                f"backend_unavailable: Backend {backend_id!r}: {exc}",
            ) from exc
        if entry is None or entry._context is None:
            raise SDKError(
                f"backend_unavailable: Backend {backend_id!r} is unavailable",
            )
        return entry

    async def _instance(self, entry, settings):
        async with self._lock:
            entry.assert_active()
            instance_settings = deepcopy(
                {
                    key: settings[key]
                    for key in entry.spec.instance_settings_keys
                    if key in settings
                },
            )
            existing = self._instances.get(entry.spec.id)
            if existing is not None:
                if existing.failed:
                    raise StaleContextError(
                        "Backend cleanup must complete before reuse",
                    )
                if (
                    existing.entry is entry
                    and existing.settings == instance_settings
                ):
                    return existing
                await self._close_instance(existing)
            plugin = entry._context
            scope = plugin.resources.child(
                workspace_id=self._agent_id,
                instance_id=uuid.uuid4().hex,
            )
            state_dir = (
                self._workspace_dir / "plugin-data" / entry.owner.plugin_id
            )
            instance = None

            def storage_guard():
                plugin._storage_guard()
                if instance is not None and instance.closed:
                    raise StaleContextError("Backend instance has been closed")

            try:
                await run_sync_io(state_dir.mkdir, parents=True, exist_ok=True)
                storage = await run_sync_io(
                    PluginStorage,
                    state_dir,
                    storage_guard,
                    _admission=plugin._storage_admission,
                )
                context = HarnessContext(
                    entry.owner.plugin_id,
                    entry.owner.generation,
                    self._agent_id,
                    self._workspace_dir,
                    state_dir,
                    storage,
                    scope,
                    plugin.logger,
                )
                instance = _Instance(entry, instance_settings, None, context)
                self._instances[entry.spec.id] = instance
                entry._runtimes.add(self)
                # Constructors and returned awaitables belong to this loop.
                backend = entry.spec.create(
                    context,
                    deepcopy(instance_settings),
                )
                if inspect.isawaitable(backend):
                    backend = await backend
                if not callable(getattr(backend, "close", None)):
                    raise SDKError("Harness backend requires close()")
                # Direct release preserves the SDK cleanup task's storage
                # ownership while retaining bounded, retryable close custody.
                scope.defer(backend.close, f"harness:{entry.spec.id}")
                instance.backend = backend
                return instance
            except BaseException:
                if instance is not None:
                    instance.failed = True
                    await run_async_to_completion(
                        self._close_instance(instance),
                    )
                else:
                    await run_async_to_completion(scope.close())
                raise

    async def _close_instance(self, instance):
        if instance.tasks:
            raise PluginBusyError(
                instance.entry.owner.plugin_id,
                len(instance.tasks),
            )
        try:
            await instance.context.resources.close()
        except BaseException:
            instance.failed = True
            raise
        instance.closed = True
        if self._instances.get(instance.entry.spec.id) is instance:
            del self._instances[instance.entry.spec.id]
        instance.entry._runtimes.discard(self)

    async def _close_entry(self, entry):
        async with self._lock:
            instance = self._instances.get(entry.spec.id)
            if instance is not None and instance.entry is entry:
                await self._close_instance(instance)

    async def close(self):
        self._closed = True
        async with self._lock:
            for instance in tuple(self._instances.values()):
                await self._close_instance(instance)

    @asynccontextmanager
    async def _invocation(
        self,
        entry,
        settings,
        *,
        request_id="",
        session_id="",
        user_id="",
        channel="",
        cwd=None,
        running=False,
    ):
        entry.assert_active()
        plugin = entry._context
        async with plugin._invocation(
            workspace_id=self._agent_id,
            session_id=session_id,
        ) as base:
            instance = await self._instance(entry, settings)
            task = asyncio.current_task()
            instance.tasks[task] = instance.tasks.get(task, 0) + 1
            try:
                capabilities = None
                if running:
                    if self._resolver is None:
                        from ...plugins._harness_capabilities import (
                            HarnessCapabilityResolver,
                        )

                        self._resolver = HarnessCapabilityResolver(
                            self._workspace_dir,
                            self._workspace,
                        )
                    capabilities = await self._resolver.resolve(
                        {
                            "agent_id": self._agent_id,
                            "session_id": session_id,
                            "user_id": user_id,
                            "channel": channel,
                        },
                    )

                async def approval(summary, *, timeout):
                    entry.assert_active()
                    base.resources._check()
                    if not isinstance(summary, HarnessApprovalSummary):
                        raise SDKError(
                            "Approval requires HarnessApprovalSummary",
                        )
                    return await self._request_approval(
                        summary,
                        timeout=timeout,
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                    )

                public = HarnessCallContext(
                    request_id,
                    session_id,
                    user_id,
                    channel,
                    Path(cwd) if cwd else self._workspace_dir,
                    deepcopy(settings),
                    capabilities,
                    base.resources,
                    base.deadline,
                    base.cancelled,
                    approval,
                )
                yield instance.backend, public
            finally:
                instance.tasks[task] -= 1
                if not instance.tasks[task]:
                    del instance.tasks[task]

    async def _request_approval(
        self,
        summary,
        *,
        timeout,
        session_id,
        user_id,
        channel,
    ):
        from ...app.approvals import get_approval_service
        from ...app.approvals.models import ApprovalRequestSummary
        from ...app.approvals.service import (
            ApprovalActor,
            ApprovalIdentityPolicy,
        )
        from ...security.tool_guard.approval import ApprovalDecision

        service = get_approval_service()
        pending = await service.create_pending_summary(
            session_id=session_id,
            root_session_id=session_id,
            owner_agent_id=self._agent_id,
            agent_id=self._agent_id,
            user_id=user_id,
            channel=channel,
            summary=ApprovalRequestSummary(
                "harness",
                summary.tool_name,
                severity=summary.severity or "medium",
                result_summary=summary.description or summary.title,
                payload=deepcopy(summary.parameters),
            ),
            timeout_seconds=timeout,
            identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
        )
        try:
            decision = await service.wait_for_approval(pending, timeout)
        except asyncio.CancelledError:
            await run_async_to_completion(
                service.cancel_request(
                    pending.request_id,
                    actor=ApprovalActor(
                        session_id,
                        session_id,
                        user_id,
                        channel,
                        self._agent_id,
                    ),
                ),
            )
            raise
        if pending.status == "cancelled":
            return "cancelled"
        return {
            ApprovalDecision.APPROVED: "approved",
            ApprovalDecision.DENIED: "rejected",
            ApprovalDecision.TIMEOUT: "timeout",
        }[decision]

    async def call(
        self,
        backend_id,
        operation,
        settings=None,
        *,
        session_id="",
        user_id="",
        channel="",
        **arguments,
    ):
        if operation not in {
            "status",
            "start_login",
            "logout",
            "models",
            "discover_skills",
            "discover_mcp",
            "history",
            "reset_session",
            "run_command",
        }:
            raise HarnessOperationNotSupportedError(
                f"Unsupported harness operation {operation!r}",
            )
        if (
            operation in {"history", "reset_session", "run_command"}
            and not session_id
        ):
            raise SDKError(f"{operation} requires a session ID")
        entry = self._entry(backend_id)
        async with self._invocation(
            entry,
            dict(settings or {}),
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        ) as (backend, context):
            callback = getattr(backend, operation, None)
            if not callable(callback):
                raise HarnessOperationNotSupportedError(
                    f"Harness does not support {operation}",
                )
            return await callback(context, **arguments)

    async def hydrate_session(
        self,
        backend_id,
        *,
        session_id,
        user_id,
        channel,
        settings=None,
    ):
        if not session_id:
            raise SDKError("History requires a session ID")
        if (
            self._session_bridge is None
            or await self._session_bridge.has_history(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
        ):
            return
        history = await self.call(
            backend_id,
            "history",
            settings,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        await self._session_bridge.hydrate(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            backend=backend_id,
            history=history,
        )

    @asynccontextmanager
    async def archive(self, backend_id, settings=None):
        entry = self._entry(backend_id)
        if not entry.spec.capabilities.external_history:
            raise HarnessOperationNotSupportedError(
                "Harness does not support external history",
            )
        async with self._invocation(entry, dict(settings or {})) as (
            backend,
            context,
        ):
            names = (
                "list_external_threads",
                "read_external_thread",
                "external_skill_records",
                "external_mcp_records",
            )
            if not all(
                callable(getattr(backend, name, None)) for name in names
            ):
                raise HarnessOperationNotSupportedError(
                    "Harness archive protocol is incomplete",
                )
            facade = _Archive(entry, backend, context)
            try:
                yield facade
            finally:
                facade.closed = True

    async def stream(self, backend_id, request, settings=None, *, cwd=None):
        session_id = str(getattr(request, "session_id", "") or "")
        if not session_id:
            raise SDKError("Harness execution requires a session ID")
        entry = self._entry(backend_id)
        stream = entry._context._managed_stream(
            lambda: self._produce(entry, request, dict(settings or {}), cwd),
            f"harness:{backend_id}",
        )
        try:
            async for item in stream:
                yield item
        finally:
            await stream.aclose()

    # Keep wire translation and terminal persistence in the producer's lease.
    # pylint: disable-next=too-many-branches,too-many-statements
    async def _produce(self, entry, request, settings, cwd):
        session_id = str(request.session_id)
        user_id = str(getattr(request, "user_id", "") or session_id)
        channel = str(getattr(request, "channel", "") or "")
        async with self._invocation(
            entry,
            settings,
            request_id=str(getattr(request, "request_id", "") or ""),
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            cwd=cwd,
            running=True,
        ) as (backend, context):
            prompt, attachments = self._content_from_request(request)
            command, arguments = (
                self._parse_command(prompt) if not attachments else ("", "")
            )
            response = AgentResponse(
                id=f"response_{uuid.uuid4().hex}",
                output=[],
                status=RunStatus.Created,
                created_at=datetime.now(timezone.utc).isoformat(
                    timespec="seconds",
                ),
            )
            response.object, response.session_id = "response", session_id
            sequence = 0

            def tagged(value):
                nonlocal sequence
                sequence += 1
                value.sequence_number = sequence
                return value

            text_stream, tool_stream = TextStream(response), ToolStream(
                response,
            )
            event_stream = None
            interrupted = None
            error_text, cancelled = "", False
            final_items = []
            try:
                yield tagged(response.model_copy(deep=True))
                response.status = RunStatus.InProgress
                yield tagged(response.model_copy(deep=True))
                if command in {"new", "clear"}:
                    await backend.reset_session(context)
                    event_stream = self._iter_events(
                        (
                            HarnessEvent(
                                HarnessEventKind.TEXT_DELTA,
                                text="Started a fresh conversation.",
                            ),
                            HarnessEvent(HarnessEventKind.COMPLETED),
                        ),
                    )
                elif command:
                    if command not in {
                        item.name for item in entry.spec.capabilities.commands
                    }:
                        raise ValueError(
                            f"Unsupported {entry.spec.label} command: "
                            f"/{command}",
                        )
                    event_stream = self._iter_events(
                        await backend.run_command(context, command, arguments),
                    )
                else:
                    from ...utils.daily_telemetry import record_agent_activity

                    await record_agent_activity()
                    event_stream = backend.run_turn(
                        context,
                        HarnessRunRequest(prompt, tuple(attachments)),
                    )
                async for event in event_stream:
                    if event.kind in {
                        HarnessEventKind.TEXT_DELTA,
                        HarnessEventKind.REASONING_DELTA,
                    }:
                        items = text_stream.push(
                            (
                                MessageType.MESSAGE
                                if event.kind == HarnessEventKind.TEXT_DELTA
                                else MessageType.REASONING
                            ),
                            event.text,
                        )
                    elif event.kind == HarnessEventKind.TOOL_STARTED:
                        items = text_stream.finish() + tool_stream.start(event)
                    elif event.kind == HarnessEventKind.TOOL_PROGRESS:
                        items = tool_stream.progress(event)
                    elif event.kind == HarnessEventKind.TOOL_COMPLETED:
                        items = tool_stream.complete(event)
                    else:
                        items = []
                        if event.kind == HarnessEventKind.ERROR:
                            error_text = event.text
                        elif event.kind == HarnessEventKind.CANCELLED:
                            cancelled = True
                    for item in items:
                        yield tagged(item)
            except (asyncio.CancelledError, GeneratorExit) as exc:
                interrupted, cancelled = exc, True
            except Exception as exc:
                error_text = str(exc)
            finally:
                if event_stream is not None:
                    try:
                        close = getattr(event_stream, "aclose", None)
                        if callable(close):
                            await close()
                    except (asyncio.CancelledError, GeneratorExit) as exc:
                        if interrupted is None:
                            interrupted = exc
                        cancelled = True
                    except Exception as exc:
                        logger.exception("Harness event stream close failed")
                        if not error_text and not cancelled:
                            error_text = (
                                f"Harness event stream close failed: {exc}"
                            )
                final_items = text_stream.finish()
                response.status = (
                    RunStatus.Failed
                    if error_text
                    else (
                        RunStatus.Cancelled
                        if cancelled
                        else RunStatus.Completed
                    )
                )
                if error_text:
                    response.error = {
                        "code": "harness_error",
                        "message": error_text,
                    }
                response.completed_at = datetime.now(timezone.utc).isoformat(
                    timespec="seconds",
                )
                if command in {"new", "clear"} and response.output:
                    response.output[-1].metadata = {
                        **dict(response.output[-1].metadata or {}),
                        "clear_history": True,
                    }
                if self._session_bridge is not None:
                    operation = (
                        self._session_bridge.clear(
                            session_id=session_id,
                            user_id=user_id,
                            channel=channel,
                        )
                        if command in {"new", "clear"}
                        else self._session_bridge.append_turn(
                            request=request,
                            response=response,
                            backend=entry.spec.id,
                        )
                    )
                    await run_async_to_completion(operation)
            if interrupted is not None:
                raise interrupted
            for item in final_items:
                yield tagged(item)
            yield tagged(response)

    @staticmethod
    async def _iter_events(events):
        for event in events:
            yield event

    @staticmethod
    def _content_from_request(
        request: Any,
    ) -> tuple[str, list[HarnessAttachment]]:
        parts: list[str] = []
        attachments: list[HarnessAttachment] = []
        for message in getattr(request, "input", None) or []:
            for content in getattr(message, "content", None) or []:
                if isinstance(content, str):
                    parts.append(content)
                    continue
                text = getattr(content, "text", None)
                if text:
                    parts.append(str(text))
                    continue
                content_type = getattr(content, "type", None)
                if content_type == ContentType.IMAGE:
                    raw_path = getattr(content, "image_url", None)
                    if raw_path:
                        attachments.append(
                            HarnessAttachment(
                                kind=HarnessAttachmentKind.IMAGE,
                                path=Path(str(raw_path)).expanduser(),
                                name=Path(str(raw_path)).name,
                            ),
                        )
                    continue
                path_field = None
                if content_type == ContentType.FILE:
                    path_field = "file_url"
                elif content_type == ContentType.AUDIO:
                    path_field = "data"
                elif content_type == ContentType.VIDEO:
                    path_field = "video_url"
                raw_path = (
                    getattr(content, path_field, None) if path_field else None
                )
                if raw_path:
                    attachments.append(
                        HarnessAttachment(
                            kind=HarnessAttachmentKind.FILE,
                            path=Path(str(raw_path)).expanduser(),
                            name=str(
                                getattr(content, "filename", None)
                                or Path(str(raw_path)).name,
                            ),
                        ),
                    )
        prompt = "\n".join(parts).strip()
        if not prompt and not attachments:
            raise ValueError(
                "Third-party agent requests require text or attachments",
            )
        return prompt, attachments

    @staticmethod
    def _parse_command(prompt: str) -> tuple[str, str]:
        if not prompt.startswith("/"):
            return "", ""
        first_line = prompt.splitlines()[0].strip()
        command, _, arguments = first_line[1:].partition(" ")
        return command.lower(), arguments.strip()


class _Archive:
    def __init__(self, entry, backend, context):
        self.entry, self.backend, self.context = entry, backend, context
        self.closed = False

    async def _call(self, operation, *args, **kwargs):
        if self.closed:
            raise StaleContextError("Harness archive call has ended")
        self.entry.assert_active()
        result = await getattr(self.backend, operation)(
            self.context,
            *args,
            **kwargs,
        )
        if operation == "read_external_thread":
            if not isinstance(result, tuple) or not all(
                isinstance(item, HarnessHistoryItem) for item in result
            ):
                raise SDKError(
                    "Archive history must contain public "
                    "HarnessHistoryItem values",
                )
            return result
        try:
            snapshot = json.loads(json.dumps(result, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise SDKError(
                "Archive records must contain only JSON values",
            ) from exc
        if not isinstance(snapshot, list) or not all(
            isinstance(item, dict) for item in snapshot
        ):
            raise SDKError("Archive records must be JSON objects")
        return tuple(snapshot)

    async def list_external_threads(self, *, limit, archived):
        return await self._call(
            "list_external_threads",
            limit=limit,
            archived=archived,
        )

    async def read_external_thread(self, thread_id):
        return await self._call("read_external_thread", thread_id)

    async def external_skill_records(self):
        return await self._call("external_skill_records")

    async def external_mcp_records(self):
        return await self._call("external_mcp_records")
