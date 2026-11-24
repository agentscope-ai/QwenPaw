# -*- coding: utf-8 -*-
"""Azure Bot native activity adapter over the shared response journal."""

import hashlib
import uuid

from qwenpaw.channel_protocol.models import EndpointParams, InboundEvent
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.channel_protocol.targets import decode_reply_target

from .platform import AzureBotDeliveryError, AzureBotPlatform


class AzureBotDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "azure_bot",
            "azure_bot.shared.responses",
            AzureBotDeliveryError,
        )
        self._endpoint_registered = self._endpoint_attempted = False

    async def start(self, config):
        if self._platform is not None:
            raise RuntimeError("AZURE_RESOURCES_ALREADY_OWNED")
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        if not config.get("enabled", False):
            await self._state_changed("disconnected")
            return
        self._platform = AzureBotPlatform(
            self._config,
            self._message,
            self._endpoint,
            self._state_changed,
            self._diagnostic,
        )
        await self._state_changed("connecting")
        try:
            await self._platform.start()
        except BaseException:
            await self._state_changed("failed")
            raise

    async def _state_changed(self, state):
        connected = state == "connected" and not self._stopping
        if connected != self._connected:
            self._connection_generation += 1
        self._connected = connected
        await self._context.set_platform_state(state)
        if connected and self._platform is not None:
            self._platform._spawn(self._resume_cleanups())

    async def _resume_cleanups(self):
        for snapshot in self._routes.pending_cleanups():
            async with self._lock(snapshot.response_handle):
                try:
                    await self._cleanup(snapshot)
                except Exception:
                    await self._diagnostic("AZURE_RESPONSE_CLEANUP_PENDING")

    async def _endpoint(self, readiness, quiescing):
        identity = self._context.identity.to_mapping()
        platform = self._platform
        params = EndpointParams.from_mapping(
            {
                **identity,
                "protocol": "http",
                "host": platform.host,
                "port": platform.port,
                "path": "/api/messages",
                "public_base_url": None,
                "readiness": readiness,
                "bound_externally": False,
                "auth_required": True,
                "quiescing": quiescing,
            },
        )
        if readiness != "stopped":
            operation = "update" if self._endpoint_registered else "register"
            self._endpoint_attempted = True
            result = await self._context.peer.call(
                "ingress.endpoint." + operation,
                params.to_mapping(),
            )
            expected = {
                "status": "registered"
                if operation == "register"
                else "updated",
                "generation": identity["generation"],
                "readiness": readiness,
            }
            if not isinstance(result, dict) or any(
                result.get(k) != v for k, v in expected.items()
            ):
                raise RuntimeError("AZURE_ENDPOINT_ACK_INVALID")
            self._endpoint_registered = True
        elif self._endpoint_attempted:
            # Even an uncertain register result must be reconciled on stop.
            result = await self._context.peer.call(
                "ingress.endpoint.unregister",
                identity,
            )
            if (
                not isinstance(result, dict)
                or result.get("status") != "unregistered"
                or result.get("generation") != identity["generation"]
            ):
                raise RuntimeError("AZURE_ENDPOINT_UNREGISTER_ACK_INVALID")
            self._endpoint_registered = self._endpoint_attempted = False

    def _require_connected(self):
        if (
            self._stopping
            or not self._connected
            or self._platform is None
            or not self._platform.connected
        ):
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        return ResponsePolicy(
            send_format=SendFormatPolicy(False, False, True, False, True),
        )

    async def _open(self, params, request):
        self._identity(params)
        platform = self._require_connected()
        target = decode_reply_target(str(params["to_handle"]))
        if target:
            session, user = target["session_id"], target["user_id"]
            destination = session if user == "group" else f"{session}:{user}"
        else:
            destination = str(params["to_handle"])
        route = platform.resolve_target(
            destination,
            dict(params.get("meta") or {}),
        )
        handle = "azure_bot:reply:" + uuid.uuid4().hex
        await self._persist_route(
            handle,
            {k: v for k, v in route.items() if isinstance(v, str)},
        )
        return {"response_handle": handle}

    async def _message(self, value):
        self._require_connected()
        event_id = value["event_id"]
        handle = (
            "azure_bot:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        created = self._routes.snapshot(handle) is None
        if created:
            await self._persist_route(
                handle,
                {
                    k: v
                    for k, v in value["route"].items()
                    if isinstance(v, str)
                },
            )
        route = value["route"]
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind="message",
            conversation={
                "id": route["conversation_id"],
                "type": "group" if route["is_group"] else "dm",
                "thread_id": None,
            },
            sender_id=value["sender_id"],
            acl_sender_id=value["acl_sender_id"],
            sender_name=value["sender_name"],
            content_parts=tuple(value["content_parts"]),
            metadata={
                **value["meta"],
                "session_id": value["session_id"],
                "user_id": value["sender_id"],
                "debounce_key": value["session_id"] + ":" + value["sender_id"],
            },
            response_handle=handle,
        )
        return await self._admit_event(event, created) is not None

    async def _perform_send(self, params):
        if params.operation.value != "message.create":
            raise AzureBotDeliveryError("OPERATION_UNSUPPORTED")
        receipt = await self._require_connected().send_parts(
            self._route_attrs(params.to_handle),
            params.content_parts,
            params.content_source,
        )
        return ResponseResourceRef.create(
            "azure_bot.delivery",
            params.delivery_id,
            receipt,
        )

    async def _perform_reaction(self, params):
        raise AzureBotDeliveryError("REACTION_UNSUPPORTED")
