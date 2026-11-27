# -*- coding: utf-8 -*-
"""Host-owned process SDK adapter; reuse the native durable delivery engine."""

import asyncio
import hashlib
import inspect
import json
import re
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

from ..channel_protocol.models import InboundEvent
from ..channel_protocol.response_lifecycle import ResponseResourceRef
from ..channel_protocol.response_policy import (
    ResponsePolicy as NativePolicy,
    SendFormatPolicy,
)
from ..channel_protocol.shared_response_driver import SharedResponseDriver
from ..channel_protocol.shared_worker import PLATFORM_STATES
from ..channel_protocol.targets import decode_reply_target
from ._events import freeze
from ._models import json_mapping
from ._channel_delivery import DeliveryBridge
from ._channel_ingress import IngressBridge
from .channel_workers import (
    ChannelDriver,
    ChannelAuth,
    ChannelApproval,
    ChannelApprovalAction,
    ChannelApprovalResolution,
    ChannelApprovals,
    ChannelWorkerContext,
    ChannelReceiveResult,
    ChannelResponse,
    ChannelContent,
    ChannelSendResult,
    ChannelDeliveryError,
    ReplyTarget,
    ResponsePolicy,
)
from .errors import ResourceError, StaleContextError
from .messages import Attachment, ContentBlock
from .resources import ResourceOwner, ResourceScope
from .storage import PluginStorage, MediaStore
from .logging import PluginLogger


def _native_policy(policy, capabilities):
    if not isinstance(policy, ResponsePolicy):
        if inspect.iscoroutine(policy):
            policy.close()
        raise ValueError("Channel response policy must be ResponsePolicy")
    values = asdict(policy)
    if not values.pop("configured_prefix"):
        values["send_format"] = SendFormatPolicy(configured_prefix=False)
    result = NativePolicy(**values)
    _validate_policy(result, capabilities)
    return result


def _validate_policy(policy, capabilities):
    if capabilities is None:
        return
    for enabled, capability in (
        (policy.streaming, "streaming"),
        (policy.prepare, "response.prepare"),
        (policy.completion_reaction, "reaction"),
        (policy.text_merge_delay_ms is not None, "channel.text_merge.v1"),
        (policy.content_source == "semantic", "send.structured_parts.v1"),
    ):
        if enabled and capability not in capabilities:
            raise ValueError(
                f"Channel capability was not declared: {capability}",
            )


def prepare_driver(driver_class, packet, *, capabilities=None):
    """Legacy drivers are untouched; SDK drivers get a private host wrapper."""
    if not inspect.isclass(driver_class) or not issubclass(
        driver_class,
        ChannelDriver,
    ):
        return driver_class
    for name, count in (
        ("start", 2),
        ("stop", 2),
        ("send", 3),
        ("resolve_target", 3),
        ("on_stream", 3),
        ("on_run", 3),
        ("prepare_response", 3),
        ("reaction", 3),
        ("finish_response", 4),
    ):
        method = getattr(driver_class, name)
        parameters = tuple(inspect.signature(method).parameters.values())
        if (
            not inspect.iscoroutinefunction(method)
            or len(parameters) != count
            or any(
                p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                for p in parameters
            )
        ):
            raise ValueError(f"Invalid ChannelDriver.{name} signature")
    if (
        driver_class.start is ChannelDriver.start
        or driver_class.send is ChannelDriver.send
    ):
        raise ValueError("ChannelDriver must implement start and send")
    inspect.signature(driver_class).bind()
    management = inspect.getattr_static(driver_class, "manage")
    management_parameters = (
        tuple(inspect.signature(management.__func__).parameters.values())
        if isinstance(management, staticmethod)
        else ()
    )
    if (
        not isinstance(management, staticmethod)
        or not inspect.iscoroutinefunction(management.__func__)
        or len(management_parameters) != 1
        or management_parameters[0].kind
        not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ):
        raise ValueError("ChannelDriver.manage must be an async staticmethod")
    if not isinstance(driver_class.response_policy, ResponsePolicy):
        raise ValueError(
            "ChannelDriver.response_policy must be ResponsePolicy",
        )
    policy_method = driver_class.response_policy_for
    parameters = tuple(inspect.signature(policy_method).parameters.values())
    if (
        inspect.iscoroutinefunction(policy_method)
        or len(parameters) != 2
        or any(
            p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            for p in parameters
        )
    ):
        raise ValueError("Invalid ChannelDriver.response_policy_for signature")
    _native_policy(driver_class.response_policy, capabilities)
    if packet.get("mode", "run") != "probe" and any(
        not isinstance(packet.get(key), str) or not packet[key]
        for key in ("plugin_id", "workspace_id")
    ):
        raise ValueError(
            "SDK channel requires host-assigned plugin and workspace identity",
        )

    class Adapter(WorkerAdapter):
        def __init__(self):
            super().__init__(
                driver_class(),
                {
                    **packet,
                    "workspace_id": packet.get("sdk_workspace_id")
                    or packet["workspace_id"],
                },
            )

        @staticmethod
        async def manage(request):
            from ._channel_management import manage

            return await manage(
                driver_class,
                request,
                workspace_id=packet.get("sdk_workspace_id")
                or request.workspace_id,
            )

    return Adapter


def _part(block):
    from ..channel_protocol.models import validate_content_part

    if not isinstance(block, ContentBlock):
        raise ValueError("Channel messages require ContentBlock values")
    if block.type == "text":
        return validate_content_part({"type": "text", "text": block.text})
    if (
        block.type not in {"image", "audio", "video", "file"}
        or block.attachment is None
    ):
        raise ValueError(
            "Channel inbound content must be text or a media attachment",
        )
    attachment = block.attachment
    values = {
        "type": block.type,
        "data"
        if block.type == "audio"
        else block.type + "_url": attachment.url,
    }
    if attachment.name:
        values["filename"] = attachment.name
    if attachment.mime_type:
        values["mime_type"] = attachment.mime_type
    return validate_content_part(values)


def _block(part):
    kind = part["type"]
    role = part.get("role", "message")
    if kind == "text":
        return ChannelContent(
            "thinking" if role == "reasoning" else "text",
            text=part["text"],
            role=role,
        )
    if kind in {"tool_call", "tool_result"}:
        output = part.get("output", ())
        return ChannelContent(
            kind,
            id=part["id"],
            name=part["name"],
            arguments=part.get("arguments", ""),
            state=part.get("state", ""),
            output=(
                output
                if isinstance(output, str)
                else tuple(_block(p) for p in output)
            ),
            role=role,
        )
    return ChannelContent(
        kind,
        role=role,
        attachment=Attachment(
            part["data" if kind == "audio" else kind + "_url"],
            part.get("mime_type") or "application/octet-stream",
            part.get("filename") or "",
        ),
    )


def _target_data(target):
    if (
        not isinstance(target, ReplyTarget)
        or not isinstance(target.key, str)
        or not target.key
    ):
        raise ValueError("A response requires a nonempty ReplyTarget")
    if not isinstance(target.user_id, str) or not isinstance(
        target.session_id,
        str,
    ):
        raise ValueError("Reply target identity must be strings")
    return {
        "key": target.key,
        "user_id": target.user_id,
        "session_id": target.session_id,
        "metadata": json_mapping(target.metadata),
    }


class WorkerAdapter(SharedResponseDriver):
    def __init__(self, driver, packet):
        super().__init__("sdk", "sdk.responses.v1", ChannelDeliveryError)
        self.driver = driver
        self.packet = packet
        self.ch = None
        self._ingress = set()
        self._admitting = {}
        self._stop_lock = asyncio.Lock()
        self._target_lock = asyncio.Lock()
        self._started = False
        self._driver_stopped = False
        self.delivery = DeliveryBridge(self)
        from ._channel_runs import RunNotifications

        self.runs = RunNotifications(self)

    def _guard(self):
        if self._stopping:
            raise StaleContextError("Channel worker is stopping")

    def _storage_guard(self):
        if self.ch is not None and self.ch.resources.closed:
            raise StaleContextError("Channel worker resources have closed")

    def _require_connected(self):
        self._guard()
        if not self._connected:
            raise ValueError("NOT_CONNECTED")

    def bind(self, context):
        super().bind(context)
        context.peer.register_method("channel.run.event", self.runs.receive)
        identity = context.identity
        resources = ResourceScope(
            ResourceOwner(
                self.packet["plugin_id"],
                identity.generation,
                self.packet["workspace_id"],
                identity.instance_id,
            ),
            self._guard,
        )
        io_resources = ResourceScope(resources.owner, self._storage_guard)
        resources.defer(io_resources.close, "channel storage IO")
        ingress = IngressBridge(context, self.packet["plugin_id"], self._guard)
        resources.defer(ingress.close, "channel ingress forwarding")

        class WorkerStorage(PluginStorage):
            async def _io(self, operation):
                self._guard()
                return await io_resources.run_sync(operation)

            def _path(self, name):
                self._guard()
                return super()._path(name)

        roots = []
        for name in ("sdk_storage_root", "sdk_media_root"):
            value = self.packet.get(name)
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError(
                    "SDK channel requires host-assigned storage roots",
                )
            roots.append(Path(value))
        storage = WorkerStorage(roots[0], self._storage_guard)
        media = MediaStore(
            WorkerStorage(roots[1], self._storage_guard),
            "/api/files/preview/" + str(roots[1]),
        )
        log_owner = SimpleNamespace(
            plugin_id=self.packet["plugin_id"],
            generation=identity.generation,
            _storage_guard=self._storage_guard,
        )
        logger = PluginLogger(
            SimpleNamespace(
                _plugin=log_owner,
                workspace_id=self.packet["workspace_id"],
                session_id="",
                resources=resources,
                channel=identity.channel_key,
            ),
        )
        self.ch = ChannelWorkerContext(
            self.packet["plugin_id"],
            self.packet["workspace_id"],
            identity.channel_key,
            identity.instance_id,
            identity.generation,
            freeze(json_mapping(self.packet["config"])),
            resources,
            self.delivery.public,
            storage,
            media,
            logger,
            ChannelAuth(context.notify_auth_required, self._guard),
            ChannelApprovals(self._resolve_approval),
            ingress.public,
            self._receive_message,
            self._status,
            self._guard,
        )

    async def _status(self, state):
        if state not in PLATFORM_STATES:
            raise ValueError("PLATFORM_STATE_INVALID")
        connected = state == "connected"
        if connected != self._connected:
            self._connection_generation += 1
            self._connected = connected
        await self._context.set_platform_state(state)

    async def start(self, config):
        await self._restore_responses()
        self._started = True
        await self.driver.start(self.ch)

    async def stop(self):
        async with self._stop_lock:
            self._stopping = True
            self._connected = False
            self._connection_generation += 1
            for task in tuple(self._ingress):
                task.cancel()
            if self._ingress:
                await asyncio.gather(
                    *tuple(self._ingress),
                    return_exceptions=True,
                )
            await self.runs.quiesce()
            errors = []
            if self._started and not self._driver_stopped:
                try:
                    await self.driver.stop(self.ch)
                    self._driver_stopped = True
                except Exception as exc:
                    errors.append(exc)
            try:
                await self.ch.resources.close()
            except Exception as exc:
                errors.append(exc)
            if errors:
                raise ResourceError(
                    "Channel resources did not finish stopping",
                ) from errors[0]
            await self._checkpoint()
            await self._context.set_platform_state("disconnected")

    def response_policy(self, response_handle):
        saved = self._route_attrs(response_handle).get("policy")
        if saved is None:
            return self.response_open_policy()
        policy = NativePolicy.from_mapping(json.loads(saved))
        _validate_policy(policy, self._context.capabilities)
        return policy

    def response_open_policy(self):
        return _native_policy(
            self.driver.response_policy,
            self._context.capabilities,
        )

    async def _persist_target(
        self,
        handle,
        target,
        *,
        owner,
        connection_generation=None,
    ):
        async with self._target_lock:
            if connection_generation is not None:
                self._check_connection(connection_generation)
            attributes = {
                "target": json.dumps(
                    _target_data(target),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "owner": json.dumps(owner, separators=(",", ":")),
            }
            if self._routes.snapshot(handle) is not None:
                saved = self._route_attrs(handle).get("policy")
                if saved is not None:
                    attributes["policy"] = saved
            else:
                # Validate the public target before invoking author code.
                resolved = self._decode_target(attributes)
                policy = _native_policy(
                    self.driver.response_policy_for(resolved),
                    self._context.capabilities,
                )
                attributes["policy"] = json.dumps(
                    policy.to_mapping(),
                    separators=(",", ":"),
                )
            await self._persist_route(handle, attributes)

    def _target(self, handle):
        return self._decode_target(self._route_attrs(handle))

    @staticmethod
    def _decode_target(attributes):
        data = json.loads(attributes["target"])
        data["metadata"] = freeze(data["metadata"])
        return ReplyTarget(**data)

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        required = {
            *self._context.identity.to_mapping(),
            "to_handle",
            "meta",
        }
        if not required <= set(params) <= required | {"session_id"}:
            raise ValueError("SCHEMA_MISMATCH")
        decoded = decode_reply_target(params["to_handle"]) or {}
        target = ReplyTarget(
            (
                (decoded.get("session_id") or decoded.get("user_id"))
                if decoded
                else params["to_handle"]
            ),
            decoded.get("user_id", ""),
            decoded.get("session_id", params.get("session_id") or ""),
            freeze(
                {
                    key: value
                    for key, value in json_mapping(
                        params["meta"] or {},
                    ).items()
                    if not key.startswith("_")
                },
            ),
        )
        with self.target_resolution():
            target = await self._invoke(self.driver.resolve_target, target)
        handle = "sdk:reply:" + uuid.uuid4().hex
        await self._persist_target(
            handle,
            target,
            owner={
                "user_id": decoded.get("user_id", ""),
                "session_id": decoded.get(
                    "session_id",
                    params.get("session_id") or "",
                ),
            },
        )
        return {"response_handle": handle}

    async def _resolve_approval(self, action):
        from .channels import ChannelMessage

        self._require_connected()
        if (
            not isinstance(action, ChannelApprovalAction)
            or not isinstance(action.request_id, str)
            or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}",
                action.request_id,
            )
            or action.decision not in {"approve", "deny"}
            or not isinstance(action.message, ChannelMessage)
            or action.message.actor_unknown
            or not action.message.sender_id
        ):
            raise ValueError(
                "Invalid approval action or unknown platform actor",
            )
        message = replace(
            action.message,
            content=(
                ContentBlock(text=f"/{action.decision} {action.request_id}"),
            ),
            metadata={**action.message.metadata, "has_bot_command": True},
        )
        return await self._receive_message(message)

    async def _receive_message(self, message):
        self._require_connected()
        connection_generation = self._connection_generation
        if message.session_scope not in {"default", "sender", "group"}:
            raise ValueError("Unknown channel session scope")
        if message.session_scope == "group" and not message.is_group:
            raise ValueError("Shared group sessions require a group message")
        if any(
            type(value) is not bool
            for value in (
                message.is_group,
                message.mentioned,
                message.actor_unknown,
            )
        ):
            raise ValueError("Channel message identity flags must be booleans")
        if any(
            not isinstance(value, str) or not value
            for value in (message.message_id, message.session_id)
        ):
            raise ValueError(
                "Process channel messages require message_id and session_id",
            )
        if len(self._ingress) >= 128:
            raise ResourceError("Channel inbound capacity exceeded")
        task = asyncio.current_task()
        self._ingress.add(task)
        try:
            identity = json.dumps(
                [self.ch.instance_id, message.session_id, message.message_id],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            digest = hashlib.sha256(identity.encode()).hexdigest()
            handle = "sdk:reply:" + digest
            event_id = "sdk:message:" + digest
            metadata = {
                key: value
                for key, value in json_mapping(message.metadata).items()
                if not key.startswith("_")
            }
            user_id = (
                "group"
                if message.session_scope == "group"
                else message.sender_id
            )
            metadata.update(
                message_id=message.message_id,
                session_id=message.session_id,
                user_id=user_id,
                is_group=message.is_group,
                bot_mentioned=message.mentioned,
                debounce_key=message.session_id + ":" + user_id,
            )
            conversation = {
                "id": message.session_id,
                "type": "group" if message.is_group else "dm",
            }
            if message.thread_id:
                conversation["thread_id"] = message.thread_id
                metadata["thread_id"] = message.thread_id
            event = InboundEvent.from_mapping(
                {
                    **self._context.identity.to_mapping(),
                    "event_id": event_id,
                    "event_kind": "message",
                    "conversation": conversation,
                    "sender_id": message.sender_id,
                    "acl_sender_id": message.acl_sender_id
                    or message.sender_id,
                    "sender_name": message.sender_name,
                    "content_parts": [
                        _part(block) for block in message.content
                    ],
                    "metadata": metadata,
                    "response_handle": handle,
                    "actor_unknown": message.actor_unknown,
                },
            )
            ack, uncertain = await self._admit_message(
                event,
                message,
                metadata,
                connection_generation,
            )
            if ack:
                if event_id in ack.accepted_event_ids:
                    return ChannelReceiveResult("accepted", handle)
                if event_id in ack.duplicate_event_ids:
                    return ChannelReceiveResult("duplicate", handle)
                rejected = next(
                    (
                        row
                        for row in ack.rejected_events
                        if row.event_id == event_id
                    ),
                    None,
                )
                if rejected and not uncertain:
                    return ChannelReceiveResult(
                        "backpressure" if rejected.retryable else "rejected",
                        handle,
                        rejected.reason_code,
                        rejected.retryable,
                    )
            return ChannelReceiveResult(
                "unknown",
                handle,
                "HOST_ADMISSION_EXHAUSTED",
                True,
            )
        finally:
            self._ingress.discard(task)

    def _response(self, params, operation):
        approval = getattr(params, "approval", None)
        resolution = getattr(params, "approval_resolution", None)
        previous = None
        if getattr(params, "target_delivery_id", None):
            resource = self._delivery_resource(
                params.to_handle,
                params.target_delivery_id,
            )
            if resource is not None:
                previous = self._send_result(dict(resource.attributes))
        return ChannelResponse(
            params.delivery_id,
            self._target(params.to_handle),
            operation,
            tuple(
                _block(part) for part in getattr(params, "content_parts", ())
            ),
            getattr(params, "target_delivery_id", None),
            getattr(getattr(params, "stream_type", None), "value", None),
            getattr(params, "sequence", None),
            getattr(params, "accumulated_text", "") or "",
            previous,
            (
                ChannelApproval(
                    approval.request_id,
                    approval.tool_name,
                    approval.severity.value,
                )
                if approval
                else None
            ),
            (
                ChannelApprovalResolution(
                    resolution.request_id,
                    resolution.outcome.value,
                    resolution.actor_user_id,
                    resolution.tool_name,
                )
                if resolution
                else None
            ),
        )

    @staticmethod
    def _send_result(attributes):
        value = json.loads(attributes["result"])
        return ChannelSendResult(
            value["message_id"],
            freeze(value["metadata"]),
        )

    async def _admit_message(self, event, message, metadata, generation):
        handle = event.response_handle
        # Only the first admission can own rollback of a newly opened route.
        # Keep this separate from the lock used for replies and their cleanup.
        while previous := self._admitting.get(handle):
            await asyncio.shield(previous)
        self._check_connection(generation)
        done = asyncio.get_running_loop().create_future()
        self._admitting[handle] = done
        try:
            snapshot = self._routes.snapshot(handle)
            if snapshot is None or snapshot.kind.value != "terminal":
                target = await self.driver.resolve_target(
                    self.ch,
                    ReplyTarget(
                        message.reply_to or message.session_id,
                        message.sender_id,
                        message.session_id,
                        freeze(metadata),
                    ),
                )
                await self._persist_target(
                    handle,
                    target,
                    owner={
                        "user_id": metadata["user_id"],
                        "session_id": message.session_id,
                    },
                    connection_generation=generation,
                )
            return await self._admit_event(
                event,
                snapshot is None,
                detailed=True,
                connection_generation=generation,
            )
        finally:
            del self._admitting[handle]
            done.set_result(None)

    async def _invoke(
        self,
        method,
        *args,
        handle=None,
        delivery_id=None,
        cleanup_delivery=False,
    ):
        async def invoke():
            try:
                if handle is None:
                    return await method(self.ch, *args)
                with self.delivery.bind(handle, delivery_id, cleanup_delivery):
                    return await method(self.ch, *args)
            except Exception as exc:
                return exc

        result = await self.ch.resources.task(
            invoke(),
            "channel:" + method.__name__,
        )
        if isinstance(result, Exception):
            raise result
        return result

    async def _invoke_delivery(
        self,
        method,
        response,
        handle,
        *,
        cleanup_delivery=False,
    ):
        try:
            result = await self._invoke(
                method,
                response,
                handle=handle,
                delivery_id=response.delivery_id,
                cleanup_delivery=cleanup_delivery,
            )
        except ChannelDeliveryError as exc:
            if self._pending_steps(handle, response.delivery_id):
                raise ChannelDeliveryError(
                    exc.reason_code,
                    side_effect_possible=True,
                ) from exc
            raise
        if self._pending_steps(handle, response.delivery_id):
            raise ChannelDeliveryError(
                "STEP_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        if not isinstance(result, ChannelSendResult):
            raise TypeError("Channel callbacks must return ChannelSendResult")
        return result

    async def _perform(self, params, operation, method):
        result = await self._invoke_delivery(
            method,
            self._response(params, operation),
            params.to_handle,
        )
        data = {
            "message_id": result.message_id,
            "metadata": json_mapping(result.metadata),
        }
        attributes = {"result": json.dumps(data)}
        resource_id = params.delivery_id
        if operation.startswith("stream."):
            resource_id = params.target_delivery_id or params.delivery_id
            attributes.update(
                stream="true",
                handle=params.to_handle,
                sequence=str(params.sequence),
                text=params.accumulated_text,
                stream_type=params.stream_type.value,
                final="true" if operation == "stream.end" else "false",
            )
        return ResponseResourceRef.create(
            "sdk.delivery",
            resource_id,
            attributes,
        )

    def _pending_steps(self, handle, delivery_id):
        return any(
            ref.kind == "sdk.step"
            and dict(ref.attributes).get("delivery_id") == delivery_id
            and dict(ref.attributes).get("state") == "unknown"
            for ref in self._routes.snapshot(handle).resource_refs
        )

    def _compact_receipt(self, snapshot):
        compact = super()._compact_receipt(snapshot)
        unknown = tuple(
            ref
            for ref in snapshot.resource_refs
            if ref.kind == "sdk.step"
            and dict(ref.attributes).get("state") == "unknown"
        )
        if not unknown:
            return compact
        resources = tuple(
            ref for ref in snapshot.resource_refs if ref.kind == "sdk.resource"
        )
        return replace(
            compact,
            resource_refs=tuple(
                sorted(
                    set(
                        (
                            *compact.resource_refs,
                            *unknown,
                            *resources,
                            *snapshot.route_refs,
                        ),
                    ),
                ),
            ),
            expires_at_ms=2**63 - 1,
        )

    def _evictable(self, snapshot):
        return super()._evictable(snapshot) and not any(
            ref.kind == "sdk.step"
            and dict(ref.attributes).get("state") == "unknown"
            for ref in snapshot.resource_refs
        )

    async def _perform_send(self, params):
        method = (
            self.driver.on_stream
            if params.operation.value.startswith("stream.")
            else self.driver.send
        )
        return await self._perform(params, params.operation.value, method)

    async def _perform_prepare(self, params):
        return await self._perform(
            params,
            "prepare",
            self.driver.prepare_response,
        )

    async def _perform_reaction(self, params):
        return await self._perform(params, "reaction", self.driver.reaction)

    def _needs_stream_cleanup(self, ref):
        attributes = dict(ref.attributes)
        if attributes.get("stream") != "true":
            return False
        snapshot = self._routes.snapshot(attributes["handle"])
        # An uncertain newer update may already be visible. Finalizing with
        # the last confirmed text would overwrite it with stale content.
        return not any(
            attempt.kind == "sdk.attempt"
            and dict(attempt.attributes).get("target_delivery_id")
            == ref.resource_id
            and dict(attempt.attributes).get("state") == "unknown"
            for attempt in snapshot.resource_refs
        )

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        snapshot = self._routes.snapshot(resource["handle"])
        response = ChannelResponse(
            "cleanup:" + ref.resource_id,
            self._decode_target(dict(snapshot.route_refs[0].attributes)),
            "stream.end",
            target_delivery_id=ref.resource_id,
            stream_type=resource["stream_type"],
            sequence=sequence,
            text=resource["text"],
            previous=self._send_result(resource),
        )
        await self._invoke_delivery(
            self.driver.on_stream,
            response,
            resource["handle"],
            cleanup_delivery=True,
        )

    async def _before_local_retirement(self, snapshot):
        self.runs.require_finished(snapshot.response_handle)
        await self._invoke(
            self.driver.finish_response,
            self._decode_target(dict(snapshot.route_refs[0].attributes)),
            snapshot.outcome.value,
            handle=snapshot.response_handle,
        )
        self.runs.release(snapshot.response_handle)
        return snapshot

    async def _release_local_response(self, handle):
        self.runs.release(handle)
        await super()._release_local_response(handle)
