# -*- coding: utf-8 -*-
"""Core-owned Channel endpoint services and bounded routing state."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from typing import Protocol
from urllib.parse import unquote, urlsplit

from .core_lifecycle import CoreAuthorizationSnapshot, CoreSlotSnapshot
from .errors import (
    ProtocolValidationError,
    RPC_AUTH_ERROR,
    RPC_CAPABILITY_ERROR,
    RPC_FENCING_ERROR,
    RPC_LIFECYCLE_ERROR,
    RpcError,
)
from .models import (
    EndpointParams,
    EndpointRegistrationResult,
    IdentityParams,
    is_external_host,
)


class EndpointAuthority(Protocol):
    """Only the identity and generation evidence needed by endpoint storage."""

    channel_key: str
    instance_id: str

    @property
    def snapshot(self) -> CoreAuthorizationSnapshot:
        ...

    def check_identity(self, params: IdentityParams) -> None:
        ...

    def endpoint_snapshot(
        self,
        generation: int,
    ) -> CoreSlotSnapshot | None:
        ...

    def route_snapshot(self, generation: int) -> CoreSlotSnapshot | None:
        ...

    def generation_error(self, generation: int) -> RpcError:
        ...


class CoreEndpointRegistry:
    """Own bounded candidate and active endpoints for Core routing."""

    def __init__(
        self,
        *,
        channel_key: str,
        instance_id: str,
        authority: EndpointAuthority,
    ) -> None:
        self.channel_key = channel_key
        self.instance_id = instance_id
        if (
            authority.channel_key != channel_key
            or authority.instance_id != instance_id
        ):
            raise ValueError(
                "endpoint registry and authority identity must match",
            )
        self.authority = authority
        self._entries: dict[int, tuple[int, EndpointParams]] = {}

    def register(self, endpoint: EndpointParams) -> None:
        """Store one generation endpoint without making it routable early."""
        self.authority.check_identity(endpoint)
        slot = self.authority.endpoint_snapshot(endpoint.generation)
        if slot is None:
            raise self.authority.generation_error(endpoint.generation)
        if "ingress_endpoint" not in slot.capabilities:
            raise RpcError(
                RPC_CAPABILITY_ERROR,
                "ingress endpoint capability was not selected",
                data={
                    "reason_code": "CAPABILITY_REQUIRED",
                    "capability": "ingress_endpoint",
                },
            )
        if is_external_host(endpoint.host) and slot.phase != "active":
            raise self._fencing_error("STANDBY_ENDPOINT_FORBIDDEN")
        self._entries[endpoint.generation] = (slot.epoch, endpoint)

    def unregister(self, params: IdentityParams) -> None:
        """Idempotently remove one generation endpoint."""
        self.authority.check_identity(params)
        self._entries.pop(params.generation, None)

    def resolve(self, generation: int) -> EndpointParams | None:
        """Return only an endpoint whose generation is currently routable."""
        entry = self._entries.get(generation)
        if entry is None:
            return None
        epoch, endpoint = entry
        slot = self.authority.route_snapshot(generation)
        if slot is None or slot.epoch != epoch:
            return None
        if endpoint.readiness != "ready" or endpoint.quiescing:
            return None
        return endpoint

    def snapshot(self) -> dict[int, EndpointParams]:
        """Return a copy containing only currently routable endpoints."""
        snapshot: dict[int, EndpointParams] = {}
        for generation in tuple(self._entries):
            endpoint = self.resolve(generation)
            if endpoint is not None:
                snapshot[generation] = endpoint
        return snapshot

    def prune(self) -> None:
        """Keep endpoint storage bounded to active and candidate slots."""
        snapshot = self.authority.snapshot
        retained = {
            slot.generation
            for slot in (snapshot.active, snapshot.candidate)
            if slot is not None
        }
        for generation in tuple(self._entries):
            if generation not in retained:
                self._entries.pop(generation, None)

    @staticmethod
    def _fencing_error(reason_code: str) -> RpcError:
        """Return one stable Core route fencing error."""
        return RpcError(
            RPC_FENCING_ERROR,
            reason_code,
            data={"reason_code": reason_code},
        )


class SharedEndpointAuthority:
    """Authorize endpoints from the real shared run, without v1 leases."""

    def __init__(
        self,
        *,
        channel_key,
        instance_id,
        source_revision,
        capabilities,
        process,
        enabled,
        ingress_open,
    ):
        self.channel_key = channel_key
        self.instance_id = instance_id
        self.source_revision = source_revision
        self.capabilities = frozenset(capabilities)
        self.process = process
        self._enabled = enabled
        self._ingress_open = ingress_open
        self._slot = None
        self._pid = None
        self._run_id = None
        self._epoch = 0
        self._highest_generation = -1
        self._fenced_generation = -1

    def check_identity(self, params):
        if params.channel_key != self.channel_key:
            raise self._error("CHANNEL_KEY_MISMATCH")
        if params.instance_id != self.instance_id:
            raise self._error("INSTANCE_ID_MISMATCH")

    @staticmethod
    def _error(reason):
        return RpcError(
            RPC_FENCING_ERROR,
            reason,
            data={"reason_code": reason},
        )

    def fence(self):
        """Revoke routing synchronously; never release a process/resource owner."""
        observation = self.process.endpoint_observation()
        generation = observation["generation"]
        if self._slot is not None:
            generation = max(generation, self._slot.generation)
        if observation["mode"] == "run" or self._slot is not None:
            self._fenced_generation = max(self._fenced_generation, generation)
        self._slot = None
        self._pid = None
        self._run_id = None

    def _current(self, *, allow_paused=False):
        observation = self.process.endpoint_observation()
        generation = observation["generation"]
        if self._slot is not None:
            changed = (
                generation != self._slot.generation
                or observation["pid"] != self._pid
                or observation["run_id"] != self._run_id
            )
            retired = (
                observation["mode"] != "run"
                or not observation["run_requested"]
                or not observation["process_alive"]
                or not observation["transport_open"]
                or not observation["ready_confirmed"]
                or observation["state"] not in {"starting", "ready"}
            )
            if changed or retired:
                self._fenced_generation = max(
                    self._fenced_generation,
                    self._slot.generation,
                )
                self._slot = None
                self._pid = None
                self._run_id = None
        if not self._enabled():
            self.fence()
            return None
        if not allow_paused and not self._ingress_open():
            return None
        if (
            observation["mode"] != "run"
            or not observation["run_requested"]
            or not observation["enabled"]
            or not observation["process_alive"]
            or not observation["transport_open"]
            or not observation["ready_confirmed"]
            or observation["state"] not in {"starting", "ready"}
            or generation <= self._fenced_generation
        ):
            return None
        # The ready Future belongs to the current launch. It can be settled
        # just before _launch publishes health state=ready; the child's
        # start(config) may register in that same scheduling interval.
        hello = observation["hello"]
        expected = {
            "channel_key": self.channel_key,
            "instance_id": self.instance_id,
            "generation": generation,
            "source_revision": self.source_revision,
        }
        if (
            hello is None
            or any(hello.get(key) != value for key, value in expected.items())
            or any(
                observation[key] != expected[key]
                for key in ("channel_key", "instance_id", "source_revision")
            )
            or frozenset(hello.get("capabilities") or ()) != self.capabilities
        ):
            return None
        if self._slot is None:
            self._epoch += 1
            self._highest_generation = max(
                self._highest_generation,
                generation,
            )
            self._pid = observation["pid"]
            self._run_id = observation["run_id"]
            self._slot = CoreSlotSnapshot(
                generation,
                self._epoch,
                "active",
                self.capabilities,
            )
        return self._slot

    @property
    def snapshot(self):
        return CoreAuthorizationSnapshot(
            active=self._current(),
            highest_generation=self._highest_generation,
            fenced_generation=(
                self._fenced_generation
                if self._fenced_generation >= 0
                else None
            ),
        )

    def endpoint_snapshot(self, generation, *, allow_paused=False):
        slot = self._current(allow_paused=allow_paused)
        if slot is None or slot.generation != generation:
            return None
        if self.process.endpoint_observation()["platform_state"] not in {
            "connecting",
            "connected",
        }:
            return None
        return slot

    def route_snapshot(self, generation):
        slot = self.endpoint_snapshot(generation)
        if slot is None:
            return None
        observation = self.process.endpoint_observation()
        if (
            observation["state"] != "ready"
            or observation["platform_state"] != "connected"
        ):
            return None
        return slot

    def generation_error(self, generation):
        self._current()
        return self._error(
            "GENERATION_REVOKED"
            if generation
            <= max(self._highest_generation, self._fenced_generation)
            else "GENERATION_UNKNOWN",
        )


@dataclass(frozen=True)
class SharedEndpointReference:
    """Host-owned listener revision; an A3 consumer must revalidate custody."""

    endpoint: EndpointParams
    revision: int
    source_revision: str
    plugin_id: str | None
    workspace_id: str | None
    loopback_host: str | None


class SharedEndpointService:
    """One bounded v2 listener registry, not a forwarding or process owner."""

    def __init__(
        self,
        *,
        authority: SharedEndpointAuthority,
        plugin_id=None,
        workspace_id=None,
    ):
        self.authority = authority
        self.plugin_id = plugin_id
        self.workspace_id = workspace_id
        self.registry = CoreEndpointRegistry(
            channel_key=authority.channel_key,
            instance_id=authority.instance_id,
            authority=authority,
        )
        self._revision = 0
        self._reference = None
        self.forwarder = None

    def register_rpc_methods(self, peer):
        for operation in ("register", "update", "unregister"):

            async def handle(params, request, operation=operation):
                return await getattr(self, operation)(params)

            peer.register_method("ingress.endpoint." + operation, handle)

    @staticmethod
    def _invalid(reason):
        return RpcError(-32602, reason, data={"reason_code": reason})

    @classmethod
    def _parse(cls, value, model):
        try:
            return model.from_mapping(
                value.to_mapping() if isinstance(value, model) else value,
            )
        except ProtocolValidationError as exc:
            raise RpcError(
                RPC_AUTH_ERROR if exc.reason_code == "AUTH_FAILED" else -32602,
                "Invalid shared endpoint parameters",
                data={"reason_code": exc.reason_code},
            ) from exc

    @staticmethod
    def _loopback_host(host):
        normalized = host.strip().lower()
        if normalized == "localhost":
            # No DNS lookup or hostfile/proxy-dependent upstream selection.
            return "127.0.0.1"
        if "%" in normalized:
            return None
        try:
            address = ipaddress.ip_address(normalized.strip("[]"))
        except ValueError:
            return None
        return address.compressed if address.is_loopback else None

    @classmethod
    def _validate_endpoint(cls, endpoint):
        if endpoint.protocol not in {"http", "ws", "http+ws"}:
            raise cls._invalid("ENDPOINT_PROTOCOL_UNSUPPORTED")
        if endpoint.port > 65535 or (
            endpoint.readiness == "ready" and endpoint.port == 0
        ):
            raise cls._invalid("ENDPOINT_PORT_INVALID")
        host = endpoint.host
        if (
            host != host.strip()
            or any(c.isspace() or ord(c) < 32 for c in host)
            or any(c in host for c in "/\\?#@%")
            or ("[" in host or "]" in host)
            and not (
                host.startswith("[")
                and host.endswith("]")
                and "[" not in host[1:-1]
                and "]" not in host[1:-1]
                and ":" in host[1:-1]
            )
        ):
            raise cls._invalid("ENDPOINT_HOST_INVALID")
        if ":" in host or host.startswith("["):
            try:
                ipaddress.ip_address(host.strip("[]"))
            except ValueError:
                raise cls._invalid("ENDPOINT_HOST_INVALID") from None
        try:
            decoded = unquote(endpoint.path, errors="strict")
            parts = urlsplit(endpoint.path)
        except (ValueError, UnicodeError):
            raise cls._invalid("ENDPOINT_PATH_INVALID") from None
        if (
            not endpoint.path.startswith("/")
            or parts.netloc
            or parts.query
            or parts.fragment
            or any(c in decoded for c in ("?", "#", "\\", "%"))
            or any(c.isspace() or ord(c) < 32 for c in decoded)
            or decoded.startswith("//")
            or ".." in decoded
            or any(segment == "." for segment in decoded.split("/"))
        ):
            raise cls._invalid("ENDPOINT_PATH_INVALID")
        if is_external_host(host) and not endpoint.auth_required:
            raise RpcError(
                RPC_AUTH_ERROR,
                "External endpoint requires authentication",
                data={"reason_code": "AUTH_FAILED"},
            )

    async def register(self, params):
        endpoint = self._parse(params, EndpointParams)
        self._validate_endpoint(endpoint)
        # No await separates authorization, epoch capture and mutation.
        # The existing registry owns capability/readiness/quiesce validation.
        self.authority.check_identity(endpoint)
        if self.authority.endpoint_snapshot(endpoint.generation) is None:
            raise self.authority.generation_error(endpoint.generation)
        self.registry.prune()
        self.registry.register(endpoint)
        self._revision += 1
        self._reference = SharedEndpointReference(
            endpoint,
            self._revision,
            self.authority.source_revision,
            self.plugin_id,
            self.workspace_id,
            self._loopback_host(endpoint.host),
        )
        try:
            forwarding = (
                self.forwarder.endpoint_changed(self, self._reference)
                if self.forwarder is not None
                else None
            )
        except RuntimeError as exc:
            self.forwarder.fence_endpoint(self)
            raise RpcError(
                RPC_LIFECYCLE_ERROR,
                str(exc),
                data={"reason_code": str(exc)},
            ) from exc
        return EndpointRegistrationResult(
            "registered",
            endpoint.generation,
            endpoint.readiness,
            forwarding,
        ).to_mapping()

    async def update(self, params):
        result = await self.register(params)
        result["status"] = "updated"
        return result

    async def unregister(self, params):
        identity = self._parse(params, IdentityParams)
        self.authority.check_identity(identity)
        if (
            identity.generation
            > self.authority.process.endpoint_observation()["generation"]
        ):
            raise self.authority.generation_error(identity.generation)
        self.registry.unregister(identity)
        if (
            self._reference is not None
            and self._reference.endpoint.generation == identity.generation
        ):
            if self.forwarder is not None:
                self.forwarder.fence_endpoint(self)
            self._revision += 1
            self._reference = None
        return {"status": "unregistered", "generation": identity.generation}

    def pause(self):
        """Close active forwards while retaining the current run's custody."""
        if self.forwarder is not None:
            self.forwarder.pause_endpoint(self)

    def fence(self):
        self.authority.fence()
        if self.forwarder is not None:
            self.forwarder.fence_endpoint(self)

    def resolve(self, generation=None, *, forwarding=False):
        """Resolve a current listener, optionally requiring a fixed local IP.

        This selects no host route and opens no connection. A3 must also
        authorize its host binding/path and revalidate this exact reference.
        External standalone listeners can never become forwarding targets.
        """
        ref = self._reference
        if ref is None or (
            generation is not None and ref.endpoint.generation != generation
        ):
            return None
        endpoint = self.registry.resolve(ref.endpoint.generation)
        if endpoint is None or (forwarding and ref.loopback_host is None):
            return None
        return ref

    def is_current(self, reference, *, forwarding=False):
        return reference is not None and reference is self.resolve(
            forwarding=forwarding,
        )


__all__ = ["CoreEndpointRegistry"]
