# -*- coding: utf-8 -*-
"""Non-blocking event fan-out with SDK-owned, bounded consumer workers."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

import asyncio
import functools
import itertools
import logging
import time
from collections import deque
from collections.abc import Mapping
from contextvars import ContextVar
from types import MappingProxyType

from .errors import SDKError
from .events import (
    ApprovalDisplay,
    ApprovalEvent,
    ApprovalSnapshot,
    ChatEvent,
    RunEvent,
    StreamContent,
    StreamMessage,
    SubscriptionGap,
    JSONValue,
)

_log = logging.getLogger(__name__)
_listeners = []
_sequence = itertools.count(1)
_observing = ContextVar("sdk_observing", default=False)


def observing():
    return _observing.get()


def freeze(value: object) -> JSONValue:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): freeze(item) for key, item in value.items()},
        )
    if isinstance(value, (tuple, list)):
        return tuple(freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SDKError(
        f"Event payload must contain JSON values, got {type(value).__name__}",
    )


def _content(value):
    data = dict(value)
    fields = {
        key: data.pop(key)
        for key in tuple(data)
        if key
        in {
            "type",
            "text",
            "delta",
            "index",
            "status",
            "object",
            "msg_id",
            "data",
        }
    }
    return StreamContent(**fields, attributes=freeze(data))


def _message(value):
    data = dict(value)
    fields = {
        key: data.pop(key, None) for key in ("id", "type", "role", "status")
    }
    return StreamMessage(
        **fields,
        content=tuple(_content(block) for block in data.pop("content", ())),
        metadata=freeze(data.pop("metadata", None) or {}),
        attributes=freeze(data),
    )


def chat_event(value):
    data = dict(freeze(value))
    object_type = data.pop("object", None)
    if object_type is None:
        object_type = (
            "response"
            if "output" in data
            else "message"
            if "content" in data
            else "event"
        )
    if object_type == "content":
        return ChatEvent(
            object_type,
            type=str(data.get("type", "")),
            status=data.get("status"),
            content=(_content({**data, "object": "content"}),),
        )
    fields = {
        key: data.pop(key, "" if key in {"id", "type"} else None)
        for key in ("id", "type", "status")
    }
    return ChatEvent(
        object_type,
        **fields,
        output=tuple(_message(item) for item in data.pop("output", ())),
        content=tuple(_content(item) for item in data.pop("content", ())),
        data=data.pop("data", None),
        attributes=freeze(data),
    )


def approval_snapshot(pending):
    from ..app.approvals.display import approval_display_fields

    return ApprovalSnapshot(
        pending.request_id,
        pending.session_id,
        pending.root_session_id,
        pending.owner_agent_id,
        pending.agent_id,
        pending.user_id,
        pending.channel,
        pending.tool_name,
        pending.status,
        pending.created_at,
        pending.resolved_at,
        pending.timeout_seconds,
        pending.severity,
        pending.findings_count,
        pending.result_summary,
        str(pending.extra.get("source_type", "tool_guard")),
        pending.scope.value if pending.scope else None,
        ApprovalDisplay(**approval_display_fields(pending)),
        getattr(pending, "_sdk_run_id", None),
    )


def emit(event):
    # Never call plugin code, wait, or propagate serialization failures here.
    for listener in tuple(_listeners):
        try:
            listener.offer(event)
        except Exception:
            _log.exception("SDK event enqueue failed")


def approval_changed(pending):
    try:
        from ._runs import bind_approval

        bind_approval(pending)
        if not _listeners:
            return
        emit(
            ApprovalEvent(
                f"approval.{pending.status}",
                approval_snapshot(pending),
                next(_sequence),
                time.time(),
            ),
        )
    except Exception:
        _log.exception("SDK approval snapshot failed")


def observe_stream(function):
    @functools.wraps(function)
    def wrapped(workspace, request):
        async def observed():
            from ._runs import current_run, index
            from ..runtime.runtime import Runtime

            # Index the same identity that execution and approvals will use.
            normalized = Runtime._normalize(request)
            runs = index()
            record = runs.start(workspace, normalized)
            run_id = record.run_id
            identity = {
                # SDK 1.0 observers correlate with the request ID. Preserve
                # that alias; snapshot.run_id is the new unique run identity.
                "run_id": runs.aliases[run_id],
                "workspace_id": workspace.agent_id,
                "session_id": record.session_id,
                "user_id": record.user_id,
                "channel": record.channel,
            }

            def publish(kind, event=None, reason=""):
                emit(
                    RunEvent(
                        kind,
                        **identity,
                        sequence=next(_sequence),
                        timestamp=time.time(),
                        event=event,
                        reason=reason,
                        snapshot=runs.snapshots[run_id],
                    ),
                )

            publish("run.started")
            stream = function(workspace, normalized)
            outcome, reason = "completed", ""
            try:
                while True:
                    token = _observing.set(True)
                    owner = current_run.set(run_id)
                    try:
                        item = await anext(stream)
                    except StopAsyncIteration:
                        break
                    finally:
                        current_run.reset(owner)
                        _observing.reset(token)
                    try:
                        snapshot = chat_event(item)
                        if snapshot.status in {"failed", "cancelled"}:
                            outcome = snapshot.status
                        publish("run.updated", snapshot)
                    except Exception:
                        _log.exception("SDK runtime snapshot failed")
                    yield item
            except (asyncio.CancelledError, GeneratorExit):
                outcome, reason = "cancelled", "consumer cancelled or closed"
                raise
            except BaseException as exc:
                outcome, reason = "failed", str(exc)
                raise
            finally:
                token = _observing.set(True)
                owner = current_run.set(run_id)
                try:
                    await stream.aclose()
                except BaseException as exc:
                    outcome = (
                        "cancelled"
                        if isinstance(exc, asyncio.CancelledError)
                        else "failed"
                    )
                    reason = str(exc) or "stream cleanup interrupted"
                    raise
                finally:
                    current_run.reset(owner)
                    _observing.reset(token)
                    runs.finish(run_id, outcome, reason)
                    publish(f"run.{outcome}", reason=reason)

        return observed()

    return wrapped


def subscribe(plugin, spec):
    plugin._resource_guard()
    if spec.capacity < 2:
        raise SDKError("Event capacity must be at least 2")

    class Listener:
        def __init__(self):
            self.queue = deque()
            self.wake = asyncio.Event()
            self.lost = 0
            self.disconnected = False

        def offer(self, event):
            if spec.kinds and event.kind not in spec.kinds:
                return
            if (
                spec.workspace_id is not None
                and event.workspace_id != spec.workspace_id
            ):
                return
            if (
                spec.session_id is not None
                and event.session_id != spec.session_id
            ):
                return
            if len(self.queue) >= spec.capacity:
                disposable = next(
                    (
                        item
                        for item in self.queue
                        if item.kind
                        in {"run.updated", "run.started", "approval.pending"}
                    ),
                    None,
                )
                if disposable is None:
                    self.disconnected = True
                    self.lost += len(self.queue) + 1
                    self.queue.clear()
                    _listeners.remove(self)
                    self.wake.set()
                    return
                self.queue.remove(disposable)
                self.lost += 1
            self.queue.append(event)
            self.wake.set()

        async def run(self):
            while True:
                await self.wake.wait()
                self.wake.clear()
                while self.queue or self.lost:
                    if self.lost:
                        event = SubscriptionGap(
                            lost=self.lost,
                            disconnected=self.disconnected,
                        )
                        self.lost = 0
                    else:
                        event = self.queue.popleft()
                    try:
                        from .context import RequestContext

                        owner = (
                            event.approval
                            if isinstance(event, ApprovalEvent)
                            else event
                        )
                        async with plugin._invocation(
                            workspace_id=getattr(event, "workspace_id", ""),
                            session_id=getattr(event, "session_id", ""),
                            identity=RequestContext(
                                getattr(event, "workspace_id", ""),
                                getattr(event, "session_id", ""),
                                getattr(owner, "channel", ""),
                                getattr(owner, "user_id", ""),
                            ),
                        ) as context:
                            await plugin._call(spec.handler, context, event)
                    except Exception as exc:
                        plugin._instance.add_diagnostic(
                            f"Event subscriber failed: {exc}",
                        )
                if self.disconnected:
                    return

    listener = Listener()
    task = plugin.resources.task(listener.run(), "event subscriber")
    _listeners.append(listener)

    async def release():
        from .custody import stop_task

        if listener in _listeners:
            _listeners.remove(listener)
        await stop_task(task, "event subscriber")

    return plugin.resources._defer(release, "event subscription")
