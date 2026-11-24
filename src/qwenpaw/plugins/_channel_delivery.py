# -*- coding: utf-8 -*-
"""Callback-bound journal operations on the existing response aggregate."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from types import MappingProxyType

from ..channel_protocol.response_lifecycle import ResponseResourceRef
from ._models import json_mapping
from .channel_workers import (
    ChannelDelivery,
    ChannelDeliveryError,
    ChannelDeliveryStep,
    ChannelSendResult,
)
from .errors import SDKAccessError


class DeliveryBridge:
    def __init__(self, adapter):
        self.adapter = adapter
        self.current = ContextVar("channel_delivery_callback", default=None)
        self.public = ChannelDelivery(
            self.prepare,
            self.progress,
            self.resource,
            self.resources,
        )

    @contextmanager
    def bind(self, handle, delivery_id, cleanup=False):
        token = self.current.set(
            (handle, delivery_id, asyncio.current_task(), cleanup),
        )
        try:
            yield
        finally:
            self.current.reset(token)

    def scope(self):
        value = self.current.get()
        if value is None or value[2] is not asyncio.current_task():
            raise SDKAccessError(
                "Delivery journal is only available in the current channel callback",
            )
        self.adapter.ch.check_cancelled()
        snapshot = self.adapter._routes.snapshot(value[0])
        if snapshot is None:
            raise SDKAccessError("Response journal is no longer available")
        return value[0], value[1], snapshot, value[3]

    def _record_ref(self, handle, ref, cleanup):
        routes = self.adapter._routes
        if cleanup:
            routes.record_cleanup_delivery(handle, [ref])
        else:
            routes.record_delivery(handle, [ref])

    @staticmethod
    def name(value):
        if (
            not isinstance(value, str)
            or not value
            or len(value.encode()) > 128
        ):
            raise ValueError(
                "Delivery step/resource names require 1 to 128 UTF-8 bytes",
            )

    def step_id(self, handle, delivery_id, name):
        self.name(name)
        if delivery_id is None:
            raise SDKAccessError(
                "Only a delivery callback can prepare platform effects",
            )
        return hashlib.sha256(
            json.dumps([handle, delivery_id, name]).encode(),
        ).hexdigest()

    @staticmethod
    def result_data(result):
        if not isinstance(result, ChannelSendResult) or not isinstance(
            result.message_id,
            str,
        ):
            raise TypeError("A confirmed effect requires ChannelSendResult")
        return json.dumps(
            {
                "message_id": result.message_id,
                "metadata": json_mapping(result.metadata),
            },
            separators=(",", ":"),
        )

    async def prepare(self, name):
        handle, delivery_id, snapshot, cleanup = self.scope()
        step_id = self.step_id(handle, delivery_id, name)
        ref = next(
            (
                r
                for r in snapshot.resource_refs
                if r.kind == "sdk.step" and r.resource_id == step_id
            ),
            None,
        )
        if ref:
            attributes = dict(ref.attributes)
            if attributes["state"] != "acknowledged":
                raise ChannelDeliveryError(
                    "STEP_RESULT_UNKNOWN",
                    side_effect_possible=True,
                )
            return ChannelDeliveryStep(
                step_id,
                name,
                True,
                self.adapter._send_result(attributes),
            )
        ref = ResponseResourceRef.create(
            "sdk.step",
            step_id,
            {"name": name, "delivery_id": delivery_id, "state": "unknown"},
        )
        self._record_ref(handle, ref, cleanup)
        await self.adapter._checkpoint()
        return ChannelDeliveryStep(step_id, name, False)

    async def progress(self, step, result):
        handle, delivery_id, snapshot, cleanup = self.scope()
        if not isinstance(
            step,
            ChannelDeliveryStep,
        ) or step.id != self.step_id(
            handle,
            delivery_id,
            step.name,
        ):
            raise SDKAccessError("Delivery step belongs to another callback")
        old = next(
            (
                r
                for r in snapshot.resource_refs
                if r.kind == "sdk.step" and r.resource_id == step.id
            ),
            None,
        )
        if old is None:
            raise SDKAccessError(
                "Prepare the delivery step before recording progress",
            )
        attributes = {
            "name": step.name,
            "delivery_id": delivery_id,
            "state": "acknowledged",
            "result": self.result_data(result),
        }
        if (
            dict(old.attributes).get("state") == "acknowledged"
            and dict(old.attributes) != attributes
        ):
            raise SDKAccessError("A confirmed step cannot be rewritten")
        self._record_ref(
            handle,
            ResponseResourceRef.create("sdk.step", step.id, attributes),
            cleanup,
        )
        try:
            await self.adapter._checkpoint()
        except BaseException:
            self._record_ref(handle, old, cleanup)
            raise

    async def resource(self, name, result):
        handle, delivery_id, _snapshot, cleanup = self.scope()
        self.name(name)
        if delivery_id is None:
            raise SDKAccessError(
                "Only a delivery callback can record platform resources",
            )
        ref = ResponseResourceRef.create(
            "sdk.resource",
            name,
            {"result": self.result_data(result)},
        )
        self._record_ref(handle, ref, cleanup)
        await self.adapter._checkpoint()

    def resources(self):
        _handle, _delivery_id, snapshot, _cleanup = self.scope()
        return MappingProxyType(
            {
                r.resource_id: self.adapter._send_result(dict(r.attributes))
                for r in snapshot.resource_refs
                if r.kind == "sdk.resource"
            },
        )
