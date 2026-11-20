# -*- coding: utf-8 -*-
"""Private translation into the existing fenced endpoint and ingress service."""

import asyncio
import hashlib
import hmac

from ..channel_protocol.models import (
    EndpointParams,
    EndpointRegistrationResult,
)
from .channel_ingress import (
    ChannelIngress,
    ChannelIngressBinding,
    ChannelIngressSpec,
)
from .errors import SDKAccessError, SDKError, StaleContextError


def ingress_path(plugin_id, channel_key):
    """Plugin IDs need not be URL-safe; never interpolate them into a route."""
    namespace = hashlib.sha256(plugin_id.encode("utf-8")).hexdigest()
    return "/channel-callbacks/" + namespace + "/" + channel_key


class IngressBridge:
    def __init__(self, context, plugin_id, guard):
        self.context, self.guard = context, guard
        self.path = ingress_path(plugin_id, context.identity.channel_key)
        self.lock = asyncio.Lock()
        self.attempted = False
        self.binding = None
        self.public = ChannelIngress(
            self.path,
            self.register,
            self.update,
            self.close,
        )

    async def register(self, spec):
        return await self._change("register", spec)

    async def update(self, spec):
        return await self._change("update", spec)

    async def _change(self, operation, spec):
        async with self.lock:
            self.guard()
            if not isinstance(spec, ChannelIngressSpec):
                raise TypeError("Expected ChannelIngressSpec")
            if "ingress_endpoint" not in self.context.capabilities:
                raise SDKAccessError(
                    "Channel ingress capability was not declared",
                )
            if (operation == "register") == self.attempted:
                raise SDKError(
                    "Register once, then update or close the listener",
                )
            params = EndpointParams.from_mapping(
                {
                    **self.context.identity.to_mapping(),
                    "host": spec.host,
                    "port": spec.port,
                    "path": self.path,
                    "protocol": spec.protocol,
                    "readiness": spec.readiness,
                    "public_base_url": spec.public_base_url,
                    "bound_externally": False,
                    "auth_required": True,
                },
            )
            self.attempted = True
            self.binding = None
            result = EndpointRegistrationResult.from_mapping(
                await self.context.peer.call(
                    "ingress.endpoint." + operation,
                    params.to_mapping(),
                ),
            )
            wire = result.forwarding
            if (
                result.generation != self.context.identity.generation
                or result.status
                != ("registered" if operation == "register" else "updated")
                or result.readiness != spec.readiness
                or wire is None
            ):
                raise SDKError("Host did not authorize channel forwarding")

            def current():
                self.guard()
                if self.binding is not binding:
                    raise StaleContextError(
                        "Channel ingress binding is no longer current",
                    )

            def verify(headers):
                values = {}
                for key, value in headers.items():
                    name = key.lower()
                    if name in {
                        "x-qwenpaw-ingress-token",
                        "x-qwenpaw-ingress-original-url",
                    }:
                        if name in values:
                            raise SDKAccessError(
                                "Duplicate host forwarding headers",
                            )
                        values[name] = value
                token = values.get("x-qwenpaw-ingress-token", "")
                url = values.get("x-qwenpaw-ingress-original-url", "")
                if (
                    not hmac.compare_digest(
                        token.encode(),
                        wire.bridge_token.encode(),
                    )
                    or not url
                ):
                    raise SDKAccessError(
                        "Request was not forwarded by this host binding",
                    )
                return url

            binding = ChannelIngressBinding(
                wire.host_port,
                wire.paths,
                spec.public_base_url,
                wire.route_query_key,
                wire.route_selector,
                verify,
                current,
            )
            self.binding = binding
            return binding

    async def close(self):
        async with self.lock:
            self.binding = None
            if not self.attempted:
                return
            identity = self.context.identity.to_mapping()
            result = await self.context.peer.call(
                "ingress.endpoint.unregister",
                identity,
            )
            if result != {
                "status": "unregistered",
                "generation": identity["generation"],
            }:
                raise SDKError("Host did not confirm ingress withdrawal")
            self.attempted = False
