# -*- coding: utf-8 -*-
"""PawApp adapter using authenticated identity and existing host services."""

import asyncio
import hashlib
import json
import re
import weakref
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import fields, is_dataclass, replace
from collections.abc import Mapping

from .apps import (
    AppContext,
    CancelResult,
    ChatRequest,
    ChatReply,
    HttpRequest,
    HttpResponse,
    SessionSummary,
    WorkspaceSummary,
    StreamingResponse,
    TaskSnapshot,
    WebSocket,
)
from .errors import SDKError, SDKAccessError, StaleContextError
from .storage import PluginStorage, MediaStore
from ._events import _message, approval_snapshot, chat_event, _observing


def plain(value):
    if is_dataclass(value):
        return {
            field.name: plain(getattr(value, field.name))
            for field in fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def wire_event(value):
    """Restore the existing frontend wire envelope from finite public DTOs."""
    from .events import ChatEvent

    if isinstance(value, ChatEvent) and value.object == "content":
        return wire_event(value.content[0])
    if is_dataclass(value):
        data = {
            field.name: wire_event(getattr(value, field.name))
            for field in fields(value)
            if field.name != "attributes"
        }
        return {**plain(getattr(value, "attributes", {})), **data}
    if isinstance(value, (tuple, list)):
        return [wire_event(item) for item in value]
    return plain(value)


class CapabilityContext:  # pylint: disable=protected-access
    """Internal bridge to PawApp's single standard route implementation."""

    def __init__(self, context):
        self.public = context
        self.app_id = context.app_id
        self.storage = CapabilityStorage(context.storage)

    async def chat(
        self,
        message,
        *,
        session_id=None,
        skill=None,
        request_id=None,
    ):
        return await self.public.chat(
            ChatRequest(message, session_id, skill, request_id),
        )

    def chat_stream(
        self,
        message,
        *,
        session_id=None,
        skill=None,
        request_id=None,
    ):
        return self.public.chat_stream(
            ChatRequest(message, session_id, skill, request_id),
        )

    async def get_session_history(self, session_id):
        return [
            wire_event(item) for item in await self.public.history(session_id)
        ]

    async def list_chat_sessions(self):
        return [plain(item) for item in await self.public.sessions()]

    async def create_chat_session(self, *, name):
        return plain(await self.public.create_session(name=name))

    async def rename_chat_session(self, chat_id, *, name):
        return plain(await self.public.rename_session(chat_id, name))

    async def archive_chat_session(self, chat_id):
        services = self.public._services
        services.guard()
        return await services.legacy.archive_chat_session(chat_id)

    async def pin_chat_session(self, chat_id, *, pinned):
        return plain(await self.public.pin_session(chat_id, pinned))

    async def delete_chat_session(self, chat_id):
        return await self.public.delete_session(chat_id)

    async def toast(self, message, *, kind):
        self.public._services.guard()
        await self.public._services.legacy.toast(message, kind=kind)

    async def notify(self, *, title, body):
        await self.public.notify(body, title=title)


class CapabilityStorage:  # pylint: disable=protected-access
    def __init__(self, storage):
        self.storage = storage

    async def get(self, key):
        return await self.storage.aread_json(key)

    async def set(self, key, value):
        await self.storage.awrite_json(key, value)

    async def delete(self, key):
        await self.storage.adelete(key)

    async def keys(self):
        return await self.storage._io(
            lambda: [
                str(path.relative_to(self.storage._root))
                for path in self.storage._root.rglob("*")
                if path.is_file() and not path.is_symlink()
            ],
        )


def _summary(value):
    if value is None:
        raise SDKError(
            "Session not found in this app, user, channel and workspace",
        )
    return SessionSummary(
        **{
            key: str(item) if key in {"created_at", "updated_at"} else item
            for key, item in value.items()
        },
    )


# Keep related adapter declarations and lifecycle ordering together.
# pylint: disable-next=too-many-public-methods
class Services:  # pylint: disable=protected-access
    def __init__(self, plugin, legacy, admitted):
        self.plugin, self.legacy, self.admitted = plugin, legacy, admitted
        self._scope = None
        self._cancelled = lambda: False

    def guard(self, *, delegation=False):
        self.plugin._guard()
        if not self.admitted():
            raise StaleContextError("App has been released")
        if (
            not delegation
            and self._scope is not None
            and (
                self._scope.closed or self._scope._closing or self._cancelled()
            )
        ):
            raise StaleContextError(
                "App call has ended; enter for_workspace() for a new call",
            )

    async def workspaces(self):
        self.guard()
        return await self._configured_workspaces()

    async def _configured_workspaces(self):
        from ..config.utils import load_config, load_agent_config
        from ..utils.io_utils import run_sync_io

        self.guard(delegation=True)

        def configured():
            result = []
            for name, profile in load_config().agents.profiles.items():
                config = load_agent_config(name)
                result.append(
                    WorkspaceSummary(
                        name,
                        config.name or name,
                        profile.enabled,
                    ),
                )
            return tuple(result)

        return await run_sync_io(configured)

    @asynccontextmanager
    async def for_workspace(self, workspace_id):
        self.guard(delegation=True)
        available = await self._configured_workspaces()
        if not any(
            item.id == workspace_id and item.enabled for item in available
        ):
            raise SDKAccessError("Workspace is not configured and enabled")
        services = Services(
            self.plugin,
            replace(self.legacy, agent_id=workspace_id),
            self.admitted,
        )
        await services.workspace()
        async with self.plugin._invocation(
            workspace_id=workspace_id,
            session_id="",
        ) as base:
            yield services.context(base)

    def context(self, base):
        self._scope = base.resources
        self._cancelled = lambda: base.cancelled
        key = hashlib.sha256(
            (
                f"{self.legacy.app_id}:{self.legacy.user_id}:"
                f"{self.legacy.channel}"
            ).encode(),
        ).hexdigest()
        storage = PluginStorage(
            base.storage._root / "apps" / key,
            self.guard,
            _admission=self.plugin._storage_admission,
        )
        media_root = base.media._storage._root / "apps" / key
        return AppContext(
            **{
                field.name: getattr(base, field.name)
                for field in fields(base)
                if field.name not in {"storage", "media"}
            },
            storage=storage,
            media=MediaStore(
                PluginStorage(
                    media_root,
                    self.guard,
                    _admission=self.plugin._storage_admission,
                ),
                "/api/files/preview/" + str(media_root),
            ),
            app_id=self.legacy.app_id,
            user_id=self.legacy.user_id,
            channel=self.legacy.channel,
            _services=self,
        )

    def session_id(self, value):
        namespace = f"pawapp:{self.legacy.app_id}"
        identity = hashlib.sha256(
            f"{self.legacy.user_id}:{self.legacy.channel}".encode(),
        ).hexdigest()
        owned = f"{namespace}:scope:{identity}"
        if value is None or value == namespace:
            return owned
        if value == owned or value.startswith(owned + ":"):
            return value
        if value.startswith("pawapp:"):
            if not value.startswith(namespace + ":"):
                raise SDKError("Session belongs to another app")
            value = value[len(namespace) + 1 :]
            if value.startswith("scope:"):
                raise SDKError("Session belongs to another user or channel")
        return f"{owned}:{value}"

    async def workspace(self):
        self.guard()
        workspace = await self.legacy._get_workspace()
        if workspace is None:
            raise SDKError("Workspace is unavailable")
        return workspace

    async def sessions(self):
        self.guard()
        await self.legacy.ensure_chat_session(self.session_id(None))
        workspace = await self.workspace()
        chats = await workspace.chat_manager.list_chats(
            user_id=self.legacy.user_id,
            channel=self.legacy.channel,
            archived=False,
        )
        namespace = self.session_id(None)
        return tuple(
            _summary(self.legacy._chat_session_payload(chat))
            for chat in sorted(
                chats,
                key=lambda item: (item.pinned, item.updated_at),
                reverse=True,
            )
            if self.legacy._owns_chat_spec(chat)
            and (
                chat.session_id == namespace
                or chat.session_id.startswith(namespace + ":")
            )
        )

    async def create_session(self, name):
        from uuid import uuid4

        self.guard()
        return _summary(
            await self.legacy.ensure_chat_session(
                self.session_id(f"dialogue:{uuid4()}"),
                name=name,
            ),
        )

    async def rename_session(self, chat_id, name):
        self.guard()
        return _summary(
            await self.legacy.rename_chat_session(chat_id, name=name),
        )

    async def archive_session(self, chat_id):
        self.guard()
        return await self.legacy.archive_chat_session(chat_id) is not None

    async def pin_session(self, chat_id, pinned):
        self.guard()
        return _summary(
            await self.legacy.pin_chat_session(chat_id, pinned=pinned),
        )

    async def delete_session(self, chat_id):
        self.guard()
        return bool(await self.legacy.delete_chat_session(chat_id))

    async def history(self, session_id):
        self.guard()
        sid = self.session_id(session_id)
        return tuple(
            _message(item)
            for item in await self.legacy.get_session_history(sid)
        )

    async def _owned_chat(self, run_id):
        workspace = await self.workspace()
        chat = await workspace.chat_manager.get_chat(run_id)
        if chat is None or not self.legacy._owns_chat_spec(chat):
            raise SDKAccessError(
                "Task/session does not belong to this app scope",
            )
        return workspace, chat

    async def _produce_chat(self, request):
        from ..schemas import AgentRequest
        from ..config.context import current_workspace_dir, current_session_id

        workspace = await self.workspace()
        sid = self.session_id(request.session_id)
        if await self.legacy.ensure_chat_session(sid) is None:
            raise SDKError("Chat session service is unavailable")
        text = request.text
        if request.skill:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", request.skill):
                raise SDKError("Skill must be a registered skill name")
            text = f"/{request.skill} {text}"
        envelope = AgentRequest(
            input=[
                {"role": "user", "content": [{"type": "text", "text": text}]},
            ],
            session_id=sid,
            user_id=self.legacy.user_id,
            channel=self.legacy.channel,
            agent_id=self.legacy.agent_id,
            request_id=request.request_id,
            request_context={"app_id": self.legacy.app_id},
        )
        async with self.plugin._invocation(
            workspace_id=self.legacy.agent_id,
            session_id=sid,
        ):
            workspace_token = current_workspace_dir.set(
                workspace.workspace_dir,
            )
            session_token = current_session_id.set(sid)
            observation_token = _observing.set(True)
            stream = workspace.stream_query(envelope)
            try:
                async for event in stream:
                    yield chat_event(event)
            finally:
                try:
                    await stream.aclose()
                finally:
                    _observing.reset(observation_token)
                    current_session_id.reset(session_token)
                    current_workspace_dir.reset(workspace_token)

    def chat_stream(self, request):
        self.guard()
        if isinstance(request, str):
            request = ChatRequest(request)
        if not isinstance(request, ChatRequest):
            raise SDKError("chat_stream requires ChatRequest or text")
        return self.plugin._managed_stream(
            lambda: self._produce_chat(request),
            f"app:{self.legacy.app_id}:chat",
        )

    # Keep related adapter declarations and lifecycle ordering together.
    # pylint: disable-next=too-many-statements
    async def start_task(self, request):
        if isinstance(request, str):
            request = ChatRequest(request)
        workspace = await self.workspace()
        sid = self.session_id(request.session_id)
        session = _summary(await self.legacy.ensure_chat_session(sid))
        run_id = session.id
        records = self.plugin._app_tasks
        key = self._task_key(run_id)
        status = TaskSnapshot(
            run_id,
            sid,
            self.legacy.agent_id,
            self.legacy.app_id,
            "running",
        )
        # The accepted run is owned by TaskTracker and the plugin generation,
        # independently of the HTTP call that requested it.
        worker = Services(self.plugin, self.legacy, self.admitted)
        ready = asyncio.Event()
        from ..agents.context.overflow_recovery import _stream_observer
        from .sdk import _RunStreams, _stream_tasks

        owned = _RunStreams()

        # Keep related adapter declarations and lifecycle ordering together.
        # pylint: disable-next=too-many-branches,too-many-statements
        async def run(_payload):
            # Do not execute author/model code until status persistence and
            # custody registration have both completed.
            await ready.wait()
            stream = worker.chat_stream(replace(request, session_id=sid))
            outcome, error = "completed", ""
            summary, truncated = "", False
            try:
                async for event in stream:
                    if event.status in {"failed", "cancelled"}:
                        outcome = event.status
                    if event.output or (
                        event.object == "message"
                        and event.status == "completed"
                    ):
                        text = ChatReply((event,)).text
                        value = text if event.output else summary + text
                        truncated = truncated or len(value) > 65536
                        summary = value[:65536]
            except (asyncio.CancelledError, GeneratorExit):
                outcome = "cancelled"
                raise
            except BaseException as exc:
                outcome, error = "failed", str(exc)
                raise
            finally:
                from ..utils.io_utils import run_async_to_completion

                owned.closing = True
                try:
                    await stream.aclose()
                except asyncio.CancelledError:
                    outcome = "cancelled"
                except Exception as exc:
                    outcome, error = "failed", str(exc)
                # Runtime wrappers may finish before an uncooperative provider
                # acknowledges cancellation. Keep the native run and its owner
                # alive until every descendant producer has actually finished.
                while pending := {
                    task for task in owned.tasks if not task.done()
                }:
                    for task in pending:
                        task.cancel()
                    try:
                        await asyncio.wait(pending)
                    except asyncio.CancelledError:
                        outcome = "cancelled"
                # A finished producer may have left a failed thread/connection
                # close behind. Reuse those exact scopes, never other runs'
                # work.
                while owned.streams or owned.scopes:
                    for close_scope in owned.closers():
                        # Repeated stops must not interrupt resource release.
                        closing = asyncio.create_task(close_scope())
                        self.plugin._instance.activity.retain_cleanup(closing)
                        try:
                            await run_async_to_completion(closing)
                        except asyncio.CancelledError:
                            outcome = "cancelled"
                        except Exception as exc:
                            error = f"Run cleanup has not finished: {exc}"
                            records[key] = replace(status, error=error)
                    if owned.streams or owned.scopes:
                        # Retain this run until an explicit stop retries
                        # cleanup; do not spin on a permanently bad close.
                        retry = self.plugin._instance.activity.retry_cleanup
                        if await retry():
                            outcome = "cancelled"
                terminal = replace(
                    status,
                    status=outcome,
                    error=error,
                    result=summary,
                    result_truncated=truncated,
                )
                # Finish persistence and memory bookkeeping even if stop or
                # reload cancels this producer again while its disk I/O waits.
                saving = asyncio.create_task(
                    self._finish_task(run_id, terminal),
                )
                self.plugin._instance.activity.retain_cleanup(saving)
                terminal = await run_async_to_completion(saving)
            # This SDK API subscribes to snapshots; history owns complete chat
            # output. Do not fill the native tracker's replay buffer with
            # tokens.
            return (
                "data: "
                + json.dumps(plain(terminal), ensure_ascii=False)
                + "\n\n"
            )

        async def produce(payload):
            with self.plugin._admission():
                token = _stream_tasks.set(owned)
                observer_token = _stream_observer.set(owned.retain)
                try:
                    event = await run(payload)
                finally:
                    owned.closing = True
                    _stream_observer.reset(observer_token)
                    _stream_tasks.reset(token)
            yield event

        from .custody import stop_task

        created, task = False, None

        async def cleanup():
            nonlocal task
            if created:
                if task is None:
                    tasks = await workspace.task_tracker.snapshot_active_tasks(
                        owner=self.plugin._instance,
                    )
                    task = tasks.get(run_id)
                if task is not None:
                    await stop_task(task, f"app task:{run_id}")

        handle = self.plugin.resources._defer(cleanup, f"app task:{run_id}")

        def finished(_task=None):
            handle.closed = True
            if handle in self.plugin.resources._handles:
                self.plugin.resources._handles.remove(handle)

        try:
            async with self._task_lock(run_id):
                if (
                    await workspace.task_tracker.get_status(run_id)
                    != "running"
                ):
                    await self.plugin.storage.awrite_json(
                        self._task_file(run_id),
                        plain(status),
                    )
                queue, created = await workspace.task_tracker.attach_or_start(
                    run_id,
                    None,
                    produce,
                    owner=self.plugin._instance,
                )
                if created:
                    records[key] = status
                    tasks = await workspace.task_tracker.snapshot_active_tasks(
                        owner=self.plugin._instance,
                    )
                    task = tasks.get(run_id)
                    if task is not None:
                        task.add_done_callback(finished)
                    else:
                        finished()
                else:
                    finished()
                await workspace.task_tracker.detach_subscriber(run_id, queue)
                ready.set()
        except BaseException:
            # Failed stops retain the registered handle and block replacement.
            await handle.close()
            finished()
            if created:
                records.pop(key, None)
            raise
        return records.get(key, status)

    def _task_lock(self, run_id):
        # Each HTTP request has its own Services; locks belong to the plugin
        # generation and survive while any start/read/finalizer uses the run.
        name = self._task_file(run_id)
        return self.plugin._app_task_locks.setdefault(name, asyncio.Lock())

    async def _finish_task(self, run_id, terminal):
        key = self._task_key(run_id)
        records = self.plugin._app_tasks
        async with self._task_lock(run_id):
            try:
                await self.plugin.storage.awrite_json(
                    self._task_file(run_id),
                    plain(terminal),
                )
            except Exception as exc:
                terminal = replace(
                    terminal,
                    status="failed",
                    error=f"Task status could not be saved: {exc}",
                )
                records[key] = terminal
                # Preserve the failure in memory if the diagnostic also
                # cannot be persisted, so callers can still inspect it.
                try:
                    await self.plugin.storage.awrite_json(
                        self._task_file(run_id),
                        plain(terminal),
                    )
                except Exception as retry_error:
                    self.plugin._instance.add_diagnostic(str(retry_error))
                else:
                    records.pop(key, None)
            else:
                records.pop(key, None)
        return terminal

    def _task_key(self, run_id):
        return (
            self.legacy.app_id,
            self.legacy.agent_id,
            self.legacy.user_id,
            self.legacy.channel,
            run_id,
        )

    def _task_file(self, run_id):
        owner = json.dumps(self._task_key(run_id)).encode()
        return "sdk-task-status/" + hashlib.sha256(owner).hexdigest() + ".json"

    async def task(self, run_id):
        workspace, chat = await self._owned_chat(run_id)
        async with self._task_lock(run_id):
            key = self._task_key(run_id)
            running = (
                await workspace.task_tracker.get_status(run_id) == "running"
            )
            saved = self.plugin._app_tasks.get(key)
            if saved is None:
                value = await self.plugin.storage.aread_json(
                    self._task_file(run_id),
                )
                saved = TaskSnapshot(**value) if value else None
            if saved is not None:
                if saved.status == "running" and not running:
                    saved = replace(
                        saved,
                        status="interrupted",
                        error="Run ended without a recorded terminal state",
                    )
                    await self.plugin.storage.awrite_json(
                        self._task_file(run_id),
                        plain(saved),
                    )
                    self.plugin._app_tasks.pop(key, None)
                return saved
            return TaskSnapshot(
                run_id,
                chat.session_id,
                self.legacy.agent_id,
                self.legacy.app_id,
                ("running" if running else "idle"),
            )

    def task_stream(self, run_id):
        async def snapshots():
            async with self.plugin._invocation(
                workspace_id=self.legacy.agent_id,
                session_id=self.session_id(None),
            ):
                previous = None
                while True:
                    current = await self.task(run_id)
                    if current != previous:
                        yield current
                        previous = current
                    if current.status != "running":
                        return
                    await asyncio.sleep(0.1)

        return self.plugin._managed_stream(snapshots, "app task subscription")

    async def cancel_task(self, run_id, timeout):
        workspace, chat = await self._owned_chat(run_id)

        async def stop():
            from ..tool_calls import CancelReason

            coordinator = getattr(
                self.legacy._app_services,
                "tool_coordinator",
                None,
            )
            if coordinator is not None:
                await coordinator.cancel_running_for_session(
                    chat.session_id,
                    agent_id=self.legacy.agent_id,
                    reason=CancelReason.USER,
                )
            return await workspace.task_tracker.request_stop(
                run_id,
                reason="user",
            )

        task = self.plugin.resources.task(stop(), f"cancel app task:{run_id}")
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            return CancelResult(True, False, True)
        return CancelResult(
            bool(task.result()),
            await workspace.task_tracker.get_status(run_id) != "running",
        )

    def _owns_approval(self, pending):
        return (
            pending.agent_id == self.legacy.agent_id
            and pending.owner_agent_id == self.legacy.agent_id
            and pending.user_id == self.legacy.user_id
            and pending.channel == self.legacy.channel
            and self.legacy.is_app_session_id(pending.session_id)
            and self.legacy.is_app_session_id(pending.root_session_id)
        )

    async def approvals(self, session_id):
        from ..app.approvals import get_approval_service

        self.guard()
        sid = self.session_id(session_id)
        pending = await get_approval_service().list_pending_by_session(sid)
        return tuple(
            approval_snapshot(item)
            for item in pending
            if self._owns_approval(item)
        )

    async def resolve_approval(self, request_id, approved, scope):
        from ..app.approvals import get_approval_service
        from ..app.approvals.service import ApprovalActor
        from ..security.tool_guard.approval import (
            ApprovalDecision,
            ApprovalScope,
        )

        self.guard()
        if not isinstance(approved, bool):
            raise SDKError("Approval decision must be a boolean")
        service = get_approval_service()
        pending = await service.get_request(request_id)
        if pending is None or not self._owns_approval(pending):
            raise SDKAccessError("Approval does not belong to this app scope")
        if scope not in {"exact", "similar"}:
            raise SDKError("Approval scope must be exact or similar")
        actor = ApprovalActor(
            pending.session_id,
            pending.root_session_id,
            self.legacy.user_id,
            self.legacy.channel,
            self.legacy.agent_id,
        )
        result = await service.resolve_request(
            request_id,
            ApprovalDecision.APPROVED if approved else ApprovalDecision.DENIED,
            scope=ApprovalScope(scope),
            actor=actor,
        )
        return result is not None

    async def request_approval(self, name, session_id, summary, timeout):
        from ..app.approvals import get_approval_service
        from ..app.approvals.service import (
            ApprovalIdentityPolicy,
            ApprovalActor,
        )
        from ..app.approvals.models import ApprovalRequestSummary
        from ..security.tool_guard.approval import ApprovalDecision

        self.guard()
        sid = self.session_id(session_id)
        service = get_approval_service()
        pending = await service.create_pending_summary(
            session_id=sid,
            root_session_id=sid,
            owner_agent_id=self.legacy.agent_id,
            agent_id=self.legacy.agent_id,
            user_id=self.legacy.user_id,
            channel=self.legacy.channel,
            summary=ApprovalRequestSummary(
                "sdk_app",
                name,
                result_summary=summary,
            ),
            extra={"app_id": self.legacy.app_id},
            timeout_seconds=timeout,
            identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
        )
        try:
            return (
                await service.wait_for_approval(pending, timeout)
                == ApprovalDecision.APPROVED
            )
        except asyncio.CancelledError:
            await service.cancel_request(
                pending.request_id,
                actor=ApprovalActor(
                    sid,
                    sid,
                    self.legacy.user_id,
                    self.legacy.channel,
                    self.legacy.agent_id,
                ),
            )
            raise

    async def notify(self, message, title, level):
        self.guard()
        await self.legacy.toast(message, kind=level)
        await self.legacy.notify(
            channels=[self.legacy.channel],
            title=title,
            body=message,
        )


# Keep related adapter declarations and lifecycle ordering together.
# pylint: disable-next=too-many-statements
def register(plugin, app):
    # This host adapter bridges SDK contracts to private runtime services.
    # pylint: disable=protected-access
    from fastapi import APIRouter, Request, WebSocket as NativeWebSocket
    from fastapi.routing import APIRoute
    from starlette.responses import (
        JSONResponse,
        Response,
        StreamingResponse as NativeStream,
    )
    from ..pawapp.deps import get_scoped_ctx

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", app.app_id):
        raise SDKError(
            "App ID must contain only letters, digits, "
            "underscores and hyphens",
        )
    plugin._guard()
    if getattr(plugin, "_app_registered", False):
        raise SDKError("One PawApp may be registered per plugin")
    plugin._app_registered = True
    plugin._app_tasks = {}
    plugin._app_task_locks = weakref.WeakValueDictionary()
    admitted = True
    current = ContextVar(f"sdk_app:{plugin.plugin_id}:{app.app_id}")

    @asynccontextmanager
    async def scope(connection):
        if not admitted:
            raise StaleContextError("App has been released")
        connection.state.app_id = app.app_id
        identity_request = (
            connection
            if isinstance(connection, Request)
            else Request({**connection.scope, "type": "http"})
        )
        legacy = await get_scoped_ctx(identity_request)
        async with plugin._invocation(
            workspace_id=legacy.agent_id,
            session_id="",
        ) as base:
            services = Services(plugin, legacy, lambda: admitted)
            public = services.context(base)
            token = current.set(public)
            try:
                yield public
            finally:
                current.reset(token)

    class Route(APIRoute):
        async def handle(self, asgi_scope, receive, send):
            # FastAPI can rebuild request handlers for included routers. Own
            # the dispatch boundary, including the response body's lifetime.
            async with scope(Request(asgi_scope, receive=receive)):
                await super().handle(asgi_scope, receive, send)

    router = APIRouter(route_class=Route)

    def add_route(path, methods, handler):
        async def endpoint(request: Request):
            public = HttpRequest(
                request.method,
                request.url.path,
                dict(request.path_params),
                dict(request.query_params),
                dict(request.headers),
                await request.body(),
            )
            try:
                result = await plugin._call(handler, current.get(), public)
            except SDKAccessError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=403)
            if isinstance(result, StreamingResponse):

                async def body():
                    try:
                        async for chunk in result.stream:
                            yield chunk
                    finally:
                        close = getattr(result.stream, "aclose", None)
                        if close:
                            await close()

                return NativeStream(
                    body(),
                    status_code=result.status,
                    headers=dict(result.headers),
                    media_type=result.media_type,
                )
            if not isinstance(result, HttpResponse):
                result = HttpResponse(result)
            if isinstance(result.body, (bytes, str)):
                return Response(
                    result.body,
                    status_code=result.status,
                    headers=dict(result.headers),
                    media_type=result.media_type or "text/plain",
                )
            return JSONResponse(
                plain(result.body),
                status_code=result.status,
                headers=dict(result.headers),
            )

        endpoint.__name__ = f"{app.app_id}_{len(router.routes)}"
        router.add_api_route(path, endpoint, methods=list(methods))

    for path, methods, handler in app._routes:
        add_route(path, methods, handler)

    async def capabilities(_context, _request):
        from .sdk_version import SDK_VERSION

        return {
            "sdk_version": SDK_VERSION,
            "app_id": app.app_id,
            "capabilities": [
                "http",
                "websocket",
                *(
                    ["chat", "sessions", "storage", "tasks", "approvals"]
                    if app._standard
                    else []
                ),
            ],
        }

    add_route("/.sdk", ("GET",), capabilities)
    for path, handler in app._websockets:

        def websocket_endpoint(callback):
            async def endpoint(connection: NativeWebSocket):
                from ..app.auth import AuthMiddleware, verify_token
                from starlette.websockets import WebSocketState

                identity = Request(
                    {**connection.scope, "type": "http", "method": "GET"},
                )
                if not AuthMiddleware._should_skip_auth(identity):
                    token = AuthMiddleware._extract_token(identity)
                    user = verify_token(token) if token else None
                    if user is None:
                        await connection.close(code=4401)
                        return
                    connection.state.user = user
                async with scope(connection) as public:
                    await connection.accept()
                    try:
                        await plugin._call(
                            callback,
                            public,
                            WebSocket(connection),
                        )
                    finally:
                        if (
                            connection.application_state
                            is not WebSocketState.DISCONNECTED
                        ):
                            await connection.close()

            return endpoint

        router.add_api_websocket_route(path, websocket_endpoint(handler))

    if app._standard:
        from ..pawapp.app import _build_capability_router

        async def capability_context():
            return CapabilityContext(current.get())

        router.include_router(
            _build_capability_router(
                capability_context,
                route_class=Route,
                encode=wire_event,
                managed_stream=True,
            ),
        )

        async def start_task(ctx, request):
            payload = request.json()
            return await ctx.start_task(
                ChatRequest(
                    payload["message"],
                    payload.get("session_id"),
                    payload.get("skill"),
                    payload.get("request_id"),
                ),
            )

        async def task(ctx, request):
            return await ctx.task(request.path_params["run_id"])

        async def task_stream(ctx, request):
            # Authorize before sending successful SSE headers.
            await ctx.task(request.path_params["run_id"])

            async def events():
                stream = ctx.task_stream(request.path_params["run_id"])
                try:
                    async for item in stream:
                        yield "data: " + json.dumps(
                            plain(item),
                            ensure_ascii=False,
                        ) + "\n\n"
                finally:
                    await stream.aclose()

            return StreamingResponse(events())

        async def cancel(ctx, request):
            return await ctx.cancel_task(request.path_params["run_id"])

        async def approvals(ctx, request):
            return {
                "approvals": await ctx.approvals(
                    request.query.get("session_id", ""),
                ),
            }

        async def resolve(ctx, request):
            from fastapi import HTTPException

            payload = request.json()
            if not isinstance(payload.get("approved"), bool):
                raise HTTPException(422, "approved must be a boolean")
            return {
                "resolved": await ctx.resolve_approval(
                    request.path_params["request_id"],
                    approved=payload["approved"],
                    scope=payload.get("scope", "exact"),
                ),
            }

        for path, methods, handler in (
            ("/tasks", ("POST",), start_task),
            ("/tasks/{run_id}", ("GET",), task),
            ("/tasks/{run_id}/stream", ("GET",), task_stream),
            ("/tasks/{run_id}/cancel", ("POST",), cancel),
            ("/approvals", ("GET",), approvals),
            ("/approvals/{request_id}", ("POST",), resolve),
        ):
            add_route(path, methods, handler)

    from ..pawapp import PawApp as HostPawApp

    native_app = HostPawApp(name=app.name, app_id=app.app_id)
    from starlette.requests import HTTPConnection

    async def inject_app_id(connection: HTTPConnection):
        connection.state.app_id = app.app_id

    native_app._sdk_app_id_injector = inject_app_id
    native_app.include_router(router)
    handle = plugin._register_contribution(native_app.register, plugin._api)
    from .resources import Registration

    async def release():
        nonlocal admitted
        admitted = False
        await handle.close()

    return Registration(
        release,
        owner=plugin.resources.owner,
        description=f"app:{app.app_id}",
        _bounded=False,
    )
