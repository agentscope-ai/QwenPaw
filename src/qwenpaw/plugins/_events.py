# -*- coding: utf-8 -*-
"""Non-blocking event fan-out with SDK-owned, bounded consumer workers."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

import asyncio
import functools
import itertools
import logging
import time
import uuid
from collections import deque
from collections.abc import Mapping
from contextlib import aclosing
from types import MappingProxyType

from ..app.task_tracker import response_outcome
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
    )


def emit(event):
    # Never call plugin code, wait, or propagate serialization failures here.
    for listener in tuple(_listeners):
        try:
            listener.offer(event)
        except Exception:
            _log.exception("SDK event enqueue failed")


def approval_changed(pending):
    if not _listeners:
        return
    try:
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


def _stream_outcome(item):
    if isinstance(item, Mapping):
        return response_outcome(
            item.get("object"),
            item.get("status"),
            item.get("error"),
        )
    return response_outcome(
        getattr(item, "object", None),
        getattr(item, "status", None),
        getattr(item, "error", None),
    )


def observe_stream(function):
    @functools.wraps(function)
    async def observed(workspace, request):
        identity = None

        def publish(kind, event=None, reason=""):
            nonlocal identity
            if identity is None:
                identity = {
                    "run_id": str(
                        getattr(request, "request_id", None)
                        or uuid.uuid4().hex,
                    ),
                    "workspace_id": workspace.agent_id,
                    "session_id": str(
                        getattr(request, "session_id", "") or "",
                    ),
                    "user_id": str(getattr(request, "user_id", "") or ""),
                    "channel": str(getattr(request, "channel", "") or ""),
                }
            emit(
                RunEvent(
                    kind,
                    **identity,
                    sequence=next(_sequence),
                    timestamp=time.time(),
                    event=event,
                    reason=reason,
                ),
            )

        if _listeners:
            publish("run.started")
        item = None
        outcome, reason = None, ""
        try:
            async with aclosing(function(workspace, request)) as stream:
                async for item in stream:
                    # Keep the outcome once observed, even across a gap
                    # between subscribers.
                    if identity is not None or _listeners:
                        outcome = _stream_outcome(item) or outcome
                    if _listeners:
                        try:
                            publish("run.updated", chat_event(item))
                        except Exception:
                            _log.exception(
                                "SDK runtime event conversion failed",
                            )
                    yield item
            # A listener may have joined after the final response was yielded.
            if _listeners and outcome is None:
                outcome = _stream_outcome(item)
        except (asyncio.CancelledError, GeneratorExit):
            outcome, reason = "cancelled", "consumer cancelled or closed"
            raise
        except BaseException as exc:
            outcome, reason = "failed", str(exc)
            raise
        finally:
            if _listeners:
                if outcome is None:
                    outcome, reason = (
                        "failed",
                        "Stream ended without a response terminal",
                    )
                publish(f"run.{outcome}", reason=reason)

    return observed


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
