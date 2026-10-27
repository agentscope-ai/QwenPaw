# -*- coding: utf-8 -*-
"""SDK transport adapter that keeps host objects private."""

import asyncio
import inspect
import logging
import re
import uuid
from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from contextlib import asynccontextmanager

from .channels import (
    ChannelContext,
    ChannelMessage,
    ChannelStreamEvent,
    ChannelRunEvent,
    ChannelHealth,
    OutgoingMessage,
)
from .errors import SDKError, StaleContextError
from .storage import PluginConfig, PluginStorage, MediaStore
from ._events import _content, chat_event

logger = logging.getLogger(__name__)


@dataclass
class _Incoming:
    requests: tuple


def _metadata(values):
    # The host adds scheduler tasks/flush bookkeeping under private keys.
    # Only JSON platform metadata belongs in the public transport contract.
    from ._events import freeze

    return freeze(
        {
            key: value
            for key, value in (values or {}).items()
            if not key.startswith("_")
        },
    )


# Keep related adapter declarations and lifecycle ordering together.
# pylint: disable-next=too-many-statements
def register(plugin, spec):
    # This host adapter bridges SDK contracts to private runtime services.
    # pylint: disable=protected-access
    from ..app.channels.base import BaseChannel
    from ..app.channels.registry import _BUILTIN_SPECS
    from ..schemas import (
        TextContent,
        ImageContent,
        AudioContent,
        VideoContent,
        FileContent,
    )

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", spec.name):
        raise SDKError("Channel name must be a safe identifier")
    if spec.name in _BUILTIN_SPECS:
        raise SDKError("An SDK channel cannot replace a built-in channel")

    class Adapter(BaseChannel):
        channel = spec.name

        # Keep related adapter declarations and lifecycle ordering together.
        # pylint: disable-next=too-many-statements
        def __init__(
            self,
            process,
            config,
            on_reply_sent,
            display_config,
            no_text_debounce,
        ):
            values = (
                config.model_dump()
                if hasattr(config, "model_dump")
                else dict(config)
                if isinstance(config, Mapping)
                else dict(vars(config))
            )
            super().__init__(
                process,
                on_reply_sent,
                display_config,
                dm_policy=values.get("dm_policy", "open"),
                group_policy=values.get("group_policy", "open"),
                allow_from=values.get("allow_from", []),
                deny_message=values.get("deny_message", ""),
                require_mention=values.get("require_mention", False),
                no_text_debounce=no_text_debounce,
                streaming_enabled=spec.streaming,
                access_control_dm=values.get("access_control_dm", False),
                access_control_group=values.get("access_control_group", False),
            )
            self._sdk_values = values
            self._sdk_scope = self._sdk_context = self._backend = None
            self._closed = False
            self._receiving = False
            self._stopping = False
            self._calls = {}
            self._call_done = {}
            self._call_cancels = {}
            self._tracker_calls = set()
            self._terminal_notifications = set()
            self._sdk_id = uuid.uuid4().hex
            self._stream_contexts = {}
            self._stream_ends = {}
            self._run_states = {}
            self._pending_message_ids = {}
            original_process = getattr(
                self._process,
                "_sdk_original_process",
                self._process,
            )

            # Keep related adapter declarations and lifecycle ordering
            # together.
            # pylint: disable-next=too-many-branches,too-many-statements
            async def produce(request):
                from ._events import _observing
                from ..agents.context.overflow_recovery import _stream_observer
                from .sdk import _RunStreams, _stream_tasks

                async with (
                    self._owned_call(),
                    plugin._invocation(
                        workspace_id=self._workspace.agent_id,
                        session_id=request.session_id,
                    ),
                ):
                    token = _observing.set(True)
                    owned = _RunStreams()
                    owner_token = _stream_tasks.set(owned)
                    observer_token = _stream_observer.set(owned.retain)
                    source = None
                    status = "completed"
                    try:
                        source = original_process(request)
                        async for event in source:
                            event_status = getattr(event, "status", None)
                            if event_status in {"failed", "cancelled"}:
                                status = event_status
                                self._set_run_status(request, status)
                            yield event
                    except (asyncio.CancelledError, GeneratorExit):
                        status = "cancelled"
                        self._set_run_status(request, status)
                        raise
                    except BaseException:
                        status = "failed"
                        self._set_run_status(request, status)
                        raise
                    finally:
                        try:
                            if source is not None:
                                await source.aclose()
                        except (asyncio.CancelledError, GeneratorExit):
                            status = "cancelled"
                            raise
                        except BaseException:
                            status = "failed"
                            raise
                        finally:
                            owned.closing = True
                            _stream_observer.reset(observer_token)
                            _stream_tasks.reset(owner_token)
                            _observing.reset(token)
                            # Host model wrappers can finish before their SDK
                            # producer does. This channel run retains custody
                            # of
                            # only its descendants, including failed scope
                            # close.
                            while pending := {
                                task for task in owned.tasks if not task.done()
                            }:
                                for task in pending:
                                    task.cancel()
                                try:
                                    await asyncio.wait(pending)
                                except asyncio.CancelledError:
                                    status = "cancelled"
                            while owned.streams or owned.scopes:
                                for close_scope in owned.closers():
                                    try:
                                        await close_scope()
                                    except asyncio.CancelledError:
                                        status = "cancelled"
                                    except Exception as exc:
                                        logger.warning(
                                            "Channel %s run cleanup "
                                            "requires retry: %s",
                                            spec.name,
                                            exc,
                                        )
                                if owned.streams or owned.scopes:
                                    retry = (
                                        plugin._instance.activity.retry_cleanup
                                    )
                                    if await retry():
                                        status = "cancelled"
                            self._set_run_status(request, status)
                            await self._finish_streams(request, status)

            def owned_process(request):
                return plugin._managed_stream(
                    lambda: produce(request),
                    f"channel:{spec.name}:run",
                )

            owned_process._sdk_original_process = original_process
            self._process = owned_process

        @classmethod
        def from_config(
            cls,
            process,
            config,
            on_reply_sent=None,
            display_config=None,
            no_text_debounce=True,
        ):
            return cls(
                process,
                config,
                on_reply_sent,
                display_config,
                no_text_debounce,
            )

        @classmethod
        def from_env(cls, process, on_reply_sent=None):
            from types import SimpleNamespace

            return cls.from_config(process, SimpleNamespace(), on_reply_sent)

        def _guard(self):
            plugin._guard()
            if self._closed or getattr(Adapter, "_sdk_closed", False):
                raise StaleContextError("Channel instance has stopped")

        @asynccontextmanager
        async def _owned_call(
            self,
            *,
            allow_stopping=False,
            propagate_cancel=False,
        ):
            task = asyncio.current_task()
            if (
                self._stopping
                and task not in self._calls
                and not allow_stopping
            ):
                raise StaleContextError("Channel instance is stopping")
            if task not in self._calls:
                self._call_done[
                    task
                ] = asyncio.get_running_loop().create_future()
            self._calls[task] = self._calls.get(task, 0) + 1
            try:
                yield
            finally:
                self._calls[task] -= 1
                if not self._calls[task]:
                    del self._calls[task]
                    # Only retract cancellation requests issued by our scoped
                    # stop. A shared queue worker may continue after this call.
                    for _ in range(self._call_cancels.pop(task, 0)):
                        task.uncancel()
                    self._call_done.pop(task).set_result(None)
                    if propagate_cancel and task.cancelling():
                        # The manager owns the queue worker's lifetime. A host
                        # stream may consume its cancellation while producing
                        # a terminal event; do not then return to queue.get().
                        raise asyncio.CancelledError

        def _receive(self, message):
            self._guard()
            if not self._receiving or self._enqueue is None:
                raise StaleContextError("Channel is not accepting messages")
            if (
                not isinstance(message, ChannelMessage)
                or not message.sender_id
            ):
                raise SDKError(
                    "Channel receive requires a sender and ChannelMessage",
                )
            # Convert/validate before enqueue; malformed input cannot affect
            # queue state.
            request = self.build_agent_request_from_native(message)
            if self._sdk_values.get(
                "group_disabled" if message.is_group else "dm_disabled",
                False,
            ):
                return
            if not self._check_group_mention(
                message.is_group,
                request.channel_meta,
            ):
                return
            self._enqueue(
                _Incoming((request,))
                if message.session_scope != "default"
                else request,
            )

        # Keep the existing adapter callback signature.
        # pylint: disable-next=arguments-renamed
        def build_agent_request_from_native(self, message):
            if not isinstance(message, ChannelMessage):
                raise SDKError("Channel input must be ChannelMessage")
            if message.session_scope not in {"default", "sender", "group"}:
                raise SDKError("Unknown channel session scope")
            if message.session_scope == "group" and not message.is_group:
                raise SDKError("Shared group sessions require a group message")
            parts = []
            for block in message.content:
                if block.type == "text":
                    parts.append(TextContent(text=block.text))
                elif block.attachment is not None:
                    attachment = block.attachment
                    if block.type == "image":
                        parts.append(ImageContent(image_url=attachment.url))
                    elif block.type == "video":
                        parts.append(VideoContent(video_url=attachment.url))
                    elif block.type == "audio":
                        parts.append(
                            AudioContent(
                                data=attachment.url,
                                format=attachment.mime_type,
                            ),
                        )
                    elif block.type == "file":
                        parts.append(
                            FileContent(
                                file_url=attachment.url,
                                filename=attachment.name,
                            ),
                        )
                    else:
                        raise SDKError(
                            "Unsupported incoming channel attachment",
                        )
                else:
                    raise SDKError(
                        "Incoming channel content requires text or attachment",
                    )
            sid = message.session_id or self.resolve_session_id(
                message.sender_id,
            )
            request = self.build_agent_request_from_user_content(
                self.channel,
                "group"
                if message.session_scope == "group"
                else message.sender_id,
                sid,
                parts,
            )
            request.acl_sender_id = message.acl_sender_id or message.sender_id
            request.channel_meta = {
                **deepcopy(message.metadata),
                "is_group": message.is_group,
                "bot_mentioned": message.mentioned,
                "sdk_reply_to": message.reply_to,
                "_sdk_channel_instance": self._sdk_id,
                "_sdk_message_ids": (message.message_id,)
                if message.message_id
                else (),
                "_sdk_session_scope": message.session_scope,
                "_sdk_sender_id": message.sender_id,
            }
            return request

        def get_debounce_key(self, payload):
            if isinstance(payload, _Incoming):
                request = payload.requests[0]
                return str((request.session_id, request.user_id))
            if (getattr(payload, "channel_meta", {}) or {}).get(
                "_sdk_session_scope",
            ) in {"sender", "group"}:
                return str((payload.session_id, payload.user_id))
            return super().get_debounce_key(payload)

        def _debounce_payload(self, payload):
            key = self.get_debounce_key(payload)
            meta = getattr(payload, "channel_meta", {}) or {}
            ids = tuple(meta.get("_sdk_message_ids", ()))
            previous = self._pending_message_ids.pop(key, ())
            ready = super()._debounce_payload(payload)
            if ready:
                meta["_sdk_message_ids"] = previous + ids
            else:
                self._pending_message_ids[key] = previous + ids
            return ready

        async def _access_control_gate(self, payload):
            blocked = await super()._access_control_gate(payload)
            if blocked:
                await self._notify_run(payload, "end", "rejected")
            return blocked

        def _extract_query_from_payload(self, payload):
            if isinstance(payload, _Incoming):
                payload = payload.requests[0]
            return super()._extract_query_from_payload(payload)

        def get_to_handle_from_request(self, request):
            return (getattr(request, "channel_meta", {}) or {}).get(
                "sdk_reply_to",
            ) or request.user_id

        async def start(self):
            with plugin._activation():
                await self._start()

        async def _start(self):
            self._guard()
            if self._backend is not None:
                return
            workspace_id = self._workspace.agent_id
            self._sdk_loop = asyncio.get_running_loop()
            async with plugin._invocation(
                workspace_id=workspace_id,
                session_id="",
            ) as base:
                self._sdk_scope = plugin.resources.child(
                    workspace_id=workspace_id,
                    instance_id=self._sdk_id,
                )
                declared = {item["name"]: item for item in spec.config_fields}
                values = {
                    key: self._sdk_values.get(key, field.get("default"))
                    for key, field in declared.items()
                }
                secrets = [
                    key
                    for key, field in declared.items()
                    if field.get("type") == "password"
                ]
                storage = PluginStorage(
                    base.storage._root / "channels" / spec.name,
                    plugin._storage_guard,
                    _admission=plugin._storage_admission,
                )
                media_root = base.media._storage._root / "channels" / spec.name
                self._sdk_context = replace(
                    ChannelContext(
                        **{
                            field.name: getattr(base, field.name)
                            for field in fields(base)
                        },
                        channel_name=spec.name,
                        _receive=self._receive,
                    ),
                    resources=self._sdk_scope,
                    config=PluginConfig(values, {"secrets": secrets}),
                    storage=storage,
                    media=MediaStore(
                        PluginStorage(
                            media_root,
                            plugin._storage_guard,
                            _admission=plugin._storage_admission,
                        ),
                        "/api/files/preview/" + str(media_root),
                    ),
                )
                from ..utils.io_utils import run_sync_io

                self._backend = await run_sync_io(spec.create)
                if inspect.isawaitable(self._backend):
                    self._backend = await self._backend
                for method in ("start", "stop", "send"):
                    if not callable(getattr(self._backend, method, None)):
                        raise SDKError(f"Channel backend requires {method}()")
                if spec.streaming and not callable(
                    getattr(self._backend, "on_stream", None),
                ):
                    raise SDKError("A streaming channel requires on_stream()")
                self._receiving = True
                await plugin._call(self._backend.start, self._sdk_context)

        # Keep related adapter declarations and lifecycle ordering together.
        # pylint: disable-next=too-many-branches
        async def stop(self):
            if self._closed:
                return
            self._receiving = False
            self._stopping = True
            from .custody import stop_task, TASK_STOP_SECONDS

            if asyncio.current_task() in self._calls:
                raise SDKError(
                    "A channel callback cannot stop its own active call",
                )
            # A transport must stay usable for cancellation/final stream events
            # until its actual consumers and TaskTracker producers have
            # stopped.
            while self._calls or self._terminal_notifications:
                for task in sorted(
                    self._calls.keys() | self._terminal_notifications,
                    key=lambda item: item not in self._tracker_calls,
                ):
                    if task in self._terminal_notifications:
                        # A submitted terminal may already have changed remote
                        # state. Drain it without cancelling and triggering a
                        # second terminal from the backend's recovery path.
                        _, pending = await asyncio.wait(
                            {task},
                            timeout=TASK_STOP_SECONDS,
                        )
                        if pending:
                            raise SDKError(
                                f"Channel {spec.name!r} terminal "
                                "notification has not stopped; "
                                "retry is required",
                            )
                        continue
                    completion = self._call_done.get(task)
                    if completion is None:
                        continue
                    if task in self._tracker_calls:
                        await stop_task(task, f"channel:{spec.name}:run")
                    else:
                        # A queue worker can swallow cancellation and return to
                        # queue.get(); only this channel's invocation must end.
                        if task.cancel():
                            self._call_cancels[task] = (
                                self._call_cancels.get(task, 0) + 1
                            )
                        _, pending = await asyncio.wait(
                            {completion},
                            timeout=TASK_STOP_SECONDS,
                        )
                        if pending:
                            raise SDKError(
                                f"Channel {spec.name!r} call has not "
                                "stopped; retry is required",
                            )
            if self._backend is not None:
                result = await plugin._call(
                    self._backend.stop,
                    self._sdk_context,
                )
                if result is not True:
                    raise SDKError(
                        "Channel backend has not stopped; retry is required",
                    )
            if self._sdk_scope is not None:
                await self._sdk_scope.close()
                plugin.resources._handles[:] = [
                    handle
                    for handle in plugin.resources._handles
                    if getattr(handle._release, "__self__", None)
                    is not self._sdk_scope
                ]
            self._closed = True

        def _owns_request(self, payload):
            if isinstance(payload, _Incoming):
                return all(
                    self._owns_request(item) for item in payload.requests
                )
            return (getattr(payload, "channel_meta", {}) or {}).get(
                "_sdk_channel_instance",
            ) == self._sdk_id

        def merge_requests(self, requests):
            if requests and isinstance(requests[0], _Incoming):
                return _Incoming(
                    tuple(
                        item
                        for incoming in requests
                        for item in incoming.requests
                        if self._owns_request(item)
                    ),
                )
            return super().merge_requests(
                [item for item in requests if self._owns_request(item)],
            )

        async def consume_one(self, payload):
            if self._receiving and self._owns_request(payload):
                await super().consume_one(payload)

        async def _consume_one_request(self, payload):
            if not self._receiving or not self._owns_request(payload):
                return
            if isinstance(payload, _Incoming) and not payload.requests:
                return
            self._guard()
            session_id = (
                payload.requests[0].session_id
                if isinstance(payload, _Incoming)
                else payload.session_id
            )
            async with (
                self._owned_call(propagate_cancel=True),
                plugin._invocation(
                    workspace_id=self._workspace.agent_id,
                    session_id=session_id,
                ),
            ):
                if isinstance(payload, _Incoming):
                    allowed = []
                    for request in payload.requests:
                        if await self._access_control_gate(request):
                            continue
                        allowed.append(request)
                    if not allowed:
                        return
                    payload = super().merge_requests(allowed)
                    # Identity comes from the first accepted sender. Delivery
                    # addresses may expire, so use the newest accepted
                    # metadata.
                    payload.channel_meta = {
                        **allowed[0].channel_meta,
                        **{
                            key: allowed[-1].channel_meta[key]
                            for key in (
                                "conversation_id",
                                "session_webhook",
                                "session_webhook_expired_time",
                                "conversation_type",
                            )
                            if key in allowed[-1].channel_meta
                        },
                        "_sdk_message_ids": tuple(
                            mid
                            for item in allowed
                            for mid in item.channel_meta.get(
                                "_sdk_message_ids",
                                (),
                            )
                        ),
                    }
                await super()._consume_one_request(payload)

        async def _stream_with_tracker(self, payload):
            if not self._receiving:
                return
            async with self._owned_call():
                task = asyncio.current_task()
                self._tracker_calls.add(task)
                stream = super()._stream_with_tracker(payload)
                try:
                    async for event in stream:
                        yield event
                except asyncio.CancelledError:
                    self._set_run_status(payload, "cancelled")
                    raise
                finally:
                    try:
                        await stream.aclose()
                    finally:
                        try:
                            await self._end_run(payload)
                        finally:
                            self._tracker_calls.discard(task)

        def _set_run_status(self, request, status):
            state = self._run_states.get(id(request))
            if state is not None:
                state["status"] = status

        def _retain_terminal(self, task):
            self._terminal_notifications.add(task)
            task.add_done_callback(self._terminal_notifications.discard)
            plugin._instance.activity.retain_cleanup(task)

        async def _notify_run(self, request, phase, status, state=None):
            callback = getattr(self._backend, "on_run", None)
            if callback is None:
                return
            cleanup = phase == "end" and state is not None
            state = state or {"id": uuid.uuid4().hex, "lock": asyncio.Lock()}
            meta = getattr(request, "channel_meta", {}) or {}
            event = ChannelRunEvent(
                phase,
                state["id"],
                self.get_to_handle_from_request(request),
                request.session_id,
                request.user_id,
                tuple(meta.get("_sdk_message_ids", ())),
                status,
                _metadata(meta),
                meta.get("_sdk_sender_id", request.user_id),
                getattr(request, "acl_sender_id", request.user_id),
            )
            admitted = asyncio.current_task() in self._calls

            async def invoke():
                async with (
                    self._owned_call(allow_stopping=admitted),
                    plugin._invocation(
                        workspace_id=self._workspace.agent_id,
                        session_id=request.session_id,
                        cleanup=cleanup,
                    ) as base,
                ):
                    async with state["lock"]:
                        if cleanup:
                            # Complete this run's stream final before a
                            # platform
                            # backend performs its run-level fallback final.
                            pending = [
                                asyncio.shield(task)
                                for (
                                    request_id,
                                    _,
                                ), task in self._stream_ends.items()
                                if request_id == id(request)
                            ]
                            if pending:
                                await asyncio.gather(
                                    *pending,
                                    return_exceptions=True,
                                )
                        await plugin._call(
                            callback,
                            replace(
                                self._sdk_context,
                                resources=base.resources,
                                session_id=base.session_id,
                                deadline=base.deadline,
                                _is_cancelled=base._is_cancelled,
                            ),
                            event,
                        )

            task = self._sdk_scope.task(invoke(), "channel run notification")
            if phase == "end":
                # Register before the task can run: even a terminal queued
                # behind its start callback must finish before transport close.
                if cleanup:
                    self._retain_terminal(task)
                else:
                    self._terminal_notifications.add(task)
                    task.add_done_callback(
                        self._terminal_notifications.discard,
                    )
                state["end_task"] = task

            def finished(completed):
                if phase == "end" and completed.cancelled():
                    logger.warning(
                        "Channel %s terminal notification cancelled",
                        spec.name,
                    )
                if (
                    not completed.cancelled()
                    and completed.exception() is not None
                ):
                    logger.warning(
                        "Channel %s run notification failed: %s",
                        spec.name,
                        completed.exception(),
                    )
                if (
                    phase == "end"
                    and self._run_states.get(id(request)) is state
                ):
                    # Keep the original run until delivery actually finishes or
                    # its failure is recorded. A second finally cannot resend
                    # it.
                    self._run_states.pop(id(request))

            task.add_done_callback(finished)
            try:
                done, _ = await asyncio.wait({task}, timeout=5)
                if not done:
                    # A terminal waiting behind a slow start remains owned and
                    # queued. Dropping it could leave a late-created platform
                    # card permanently running after the model has finished.
                    if phase == "start":
                        task.cancel()
                    logger.warning(
                        "Channel %s run notification timed out",
                        spec.name,
                    )
            except asyncio.CancelledError:
                if phase == "start":
                    task.cancel()
                raise

        async def _before_consume_process(self, request):
            if getattr(self._backend, "on_run", None) is None:
                return
            state = {
                "id": uuid.uuid4().hex,
                "lock": asyncio.Lock(),
                "status": "completed",
            }
            self._run_states[id(request)] = state
            request.channel_meta["_sdk_run_id"] = state["id"]
            try:
                await self._notify_run(request, "start", "running", state)
            except BaseException:
                self._set_run_status(request, "cancelled")
                await self._end_run(request)
                raise

        async def _end_run(self, request):
            state = self._run_states.get(id(request))
            if state is None or state.get("ending"):
                return
            state["ending"] = True
            try:
                await self._notify_run(request, "end", state["status"], state)
            finally:
                if "end_task" not in state:
                    # Scheduling failed before any delivery could start.
                    state.pop("ending", None)

        async def _on_consume_error(self, request, to_handle, err_text):
            self._set_run_status(request, "failed")
            await super()._on_consume_error(request, to_handle, err_text)

        async def _run_process_loop(self, request, to_handle, send_meta):
            try:
                await super()._run_process_loop(request, to_handle, send_meta)
            except asyncio.CancelledError:
                self._set_run_status(request, "cancelled")
                raise
            finally:
                await self._end_run(request)

        async def send_content_parts(self, to_handle, parts, meta=None):
            self._guard()
            async with (
                self._owned_call(),
                plugin._invocation(
                    workspace_id=self._workspace.agent_id,
                    session_id=(meta or {}).get("session_id", ""),
                ) as base,
            ):
                context = replace(
                    self._sdk_context,
                    resources=base.resources,
                    session_id=base.session_id,
                    deadline=base.deadline,
                    _is_cancelled=base._is_cancelled,
                )
                await plugin._call(
                    self._backend.send,
                    context,
                    OutgoingMessage(
                        to_handle,
                        tuple(_content(part) for part in parts),
                        _metadata(meta),
                        (meta or {}).get("_sdk_run_id", ""),
                        bool((meta or {}).get("_api_send", False)),
                    ),
                )

        async def send(self, to_handle, text, meta=None):
            await self.send_content_parts(
                to_handle,
                [TextContent(text=text)],
                meta,
            )

        async def health_check(self):
            self._guard()
            callback = getattr(self._backend, "health", None)
            result = ChannelHealth(
                "unsupported",
                "Backend has no health probe",
            )
            if callback is not None:
                async with (
                    self._owned_call(),
                    plugin._invocation(
                        workspace_id=self._workspace.agent_id,
                        session_id="",
                    ) as base,
                ):
                    result = await plugin._call(
                        callback,
                        replace(
                            self._sdk_context,
                            resources=base.resources,
                            _is_cancelled=base._is_cancelled,
                            deadline=base.deadline,
                        ),
                    )
                if not isinstance(result, ChannelHealth):
                    raise SDKError("Channel health must return ChannelHealth")
            return {
                "channel": self.channel,
                "status": result.status,
                "detail": result.detail,
            }

        async def _stream(
            self,
            phase,
            request,
            target,
            event,
            meta,
            stream_type,
            text,
        ):
            self._guard()
            key = (id(request), stream_type)
            if key in self._stream_ends:
                return
            if phase == "end":
                state = self._stream_contexts.get(key)
                if state is None:
                    return
            else:
                state = (request, target, meta, text)

            async def deliver():
                async with (
                    self._owned_call(allow_stopping=phase == "end"),
                    plugin._invocation(
                        workspace_id=self._workspace.agent_id,
                        session_id=request.session_id,
                        cleanup=phase == "end",
                    ) as base,
                ):
                    if phase != "end":
                        self._stream_contexts[key] = state
                    await plugin._call(
                        self._backend.on_stream,
                        replace(
                            self._sdk_context,
                            resources=base.resources,
                            session_id=base.session_id,
                            deadline=base.deadline,
                            _is_cancelled=base._is_cancelled,
                        ),
                        ChannelStreamEvent(
                            phase,
                            target,
                            chat_event(event),
                            stream_type,
                            text,
                            _metadata(meta),
                            meta.get("_sdk_run_id", ""),
                        ),
                    )

            if phase != "end":
                await deliver()
                return
            task = self._sdk_scope.task(deliver(), "channel stream terminal")
            self._stream_ends[key] = task
            self._retain_terminal(task)

            def finished(completed):
                if completed.cancelled():
                    logger.warning(
                        "Channel %s stream terminal cancelled",
                        spec.name,
                    )
                elif completed.exception() is not None:
                    logger.warning(
                        "Channel %s stream terminal failed: %s",
                        spec.name,
                        completed.exception(),
                    )
                if self._stream_contexts.get(key) is state:
                    self._stream_contexts.pop(key)
                self._stream_ends.pop(key, None)

            task.add_done_callback(finished)
            # Cancelling its producer must not cancel an already committed
            # platform final. Lifecycle/stop bound their own wait and retain
            # it.
            await asyncio.shield(task)

        async def _finish_streams(self, owner_request, status):
            from .custody import stop_task

            for (_, kind), (request, target, meta, text) in tuple(
                self._stream_contexts.items(),
            ):
                if request is not owner_request:
                    continue
                for flush in meta.get("_stream_flush", {}).values():
                    task = flush.get("task")
                    if task is not None and task is not asyncio.current_task():
                        await stop_task(task, f"channel:{spec.name}:flush")
                await self._stream(
                    "end",
                    request,
                    target,
                    {"object": "response", "status": status, "output": []},
                    meta,
                    kind,
                    text,
                )

        async def on_event_response(self, request, event):
            status = getattr(event, "status", None)
            if status in {"completed", "failed", "cancelled"}:
                await self._finish_streams(request, status)

        async def _on_stream_msg_end(
            self,
            request,
            to_handle,
            event,
            send_meta,
            msg_id_to_stream_type,
            streaming_buffers,
        ):
            # Commands can return only a completed message, including media.
            # With no preceding stream start, let the normal send path own it.
            if self._resolve_stream_type(event) not in streaming_buffers:
                return False
            return await super()._on_stream_msg_end(
                request,
                to_handle,
                event,
                send_meta,
                msg_id_to_stream_type,
                streaming_buffers,
            )

        async def on_streaming_start(
            self,
            request,
            to_handle,
            event,
            send_meta,
            stream_type,
            accumulated_text="",
        ):
            await self._stream(
                "start",
                request,
                to_handle,
                event,
                send_meta,
                stream_type,
                accumulated_text,
            )

        async def on_streaming_delta(
            self,
            request,
            to_handle,
            event,
            send_meta,
            stream_type,
            accumulated_text="",
        ):
            await self._stream(
                "delta",
                request,
                to_handle,
                event,
                send_meta,
                stream_type,
                accumulated_text,
            )

        async def on_streaming_end(
            self,
            request,
            to_handle,
            event,
            send_meta,
            stream_type,
            accumulated_text="",
        ):
            await self._stream(
                "end",
                request,
                to_handle,
                event,
                send_meta,
                stream_type,
                accumulated_text,
            )

    handle = plugin._register_contribution(
        plugin._api.register_channel,
        Adapter,
        label=spec.label,
        description=spec.description,
        config_fields=[
            {
                **field,
                "type": (
                    "switch"
                    if field.get("type") == "boolean"
                    else field.get("type", "text")
                ),
            }
            for field in spec.config_fields
        ],
        icon=spec.icon,
        doc_url=spec.doc_url,
    )
    return plugin._with_admission(handle, Adapter)
