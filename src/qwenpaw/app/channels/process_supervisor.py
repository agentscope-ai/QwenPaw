# -*- coding: utf-8 -*-
"""Channel handshake adapter over the public plugin process component."""

from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from ...channel_protocol.artifacts import code_root_digest
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from ...plugins.execution.bootstrap import validate_private_environment
from ...plugins.execution.process import (  # pylint: disable=unused-import
    PluginProcess,
    ProcessError,
    CallUnknown,
    StopResult as _StopResult,
)
from ...channel_protocol.models import IdentityParams
from ...channel_protocol.outbound_budget import (
    DEFAULT_SEND_TIMEOUT,
    OUTBOUND_METHODS,
    SEND_RECEIPT_MARGIN,
    validate_send_timeout,
)
from ...channel_protocol.rpc import RpcPeer
from ...channel_protocol.shared import (
    SharedChannelDescriptor,
    validate_shared_hello,
    validate_channel_contract,
    _read_requirements,
)


@dataclass(frozen=True)
class LaunchSpec:
    """Explicit trusted executable/code/site roots and private launch data."""

    python_executable: str
    support_root: Path
    code_root: Path
    descriptor_path: Path
    source_revision: str
    descriptor: SharedChannelDescriptor
    requirements: tuple[str, ...]
    channel_key: str
    instance_id: str
    generation: int
    qwenpaw_version: str
    config: Mapping[str, Any] = field(repr=False)
    dependency_paths: tuple[Path, ...] = ()
    enabled: bool = True
    startup_timeout: float = 5.0
    shutdown_timeout: float = 2.0
    runtime_identity: Mapping[str, Any] | None = None
    restart_limit: int = 0
    restart_backoff: float = 0.1
    plugin_id: str | None = None
    workspace_id: str | None = None
    private_env: Mapping[str, str] = field(default_factory=dict, repr=False)
    send_timeout: float = DEFAULT_SEND_TIMEOUT

    def __post_init__(self):
        validate_send_timeout(self.send_timeout)
        object.__setattr__(
            self,
            "private_env",
            validate_private_environment(self.private_env),
        )


ChannelProcessError = ProcessError
ChannelCallUnknown = CallUnknown
StopResult = _StopResult


class ChannelProcess(PluginProcess):
    """Preserve Channel identity, platform states and shared v2 wire data."""

    identity_type = IdentityParams
    hello_method = "runner.hello"
    control_prefix = "shared."
    state_key = "platform_state"
    request_prefix = "channel"
    initial_state = "disconnected"
    connecting_state = "connecting"
    component_states = {"connecting", "connected", "disconnected", "failed"}
    failed_reason = "PLATFORM_START_FAILED"

    def endpoint_observation(self) -> dict[str, Any]:
        """Read current run/handshake custody without exposing launch secrets."""
        ready = self._ready
        hello = self.observed_hello
        spec = self._spec
        binding = getattr(self, "_endpoint_hello_binding", None)
        current_hello = (
            binding is not None
            and binding[0] is self._peer
            and binding[1] is ready
        )
        return {
            **self.health_snapshot(),
            "mode": self._mode,
            "run_id": id(ready) if ready is not None else None,
            "run_requested": self._restart_enabled,
            "channel_key": spec.channel_key if spec else None,
            "instance_id": spec.instance_id if spec else None,
            "source_revision": spec.source_revision if spec else None,
            "enabled": bool(spec and spec.enabled),
            "process_alive": bool(
                self._process is not None and self._process.returncode is None,
            ),
            "transport_open": bool(
                self._peer is not None and not self._peer.is_closed,
            ),
            "ready_confirmed": bool(
                current_hello
                and ready is not None
                and ready.done()
                and not ready.cancelled()
                and ready.exception() is None,
            ),
            "hello": (
                {
                    key: hello.get(key)
                    for key in (
                        "channel_key",
                        "instance_id",
                        "generation",
                        "source_revision",
                        "capabilities",
                    )
                }
                if hello is not None
                else None
            ),
        }

    async def start_management(self, spec: LaunchSpec) -> dict[str, Any]:
        """Start a scoped, single-operation worker without a runtime Driver."""
        if (
            any(
                not isinstance(value, str) or not value
                for value in (
                    spec.plugin_id,
                    spec.workspace_id,
                )
            )
            or spec.restart_limit != 0
        ):
            raise self.error_type("MANAGEMENT_INVALID_REQUEST")
        self._management_called = False
        return await self._start(
            replace(spec, config={}, enabled=True),
            mode="manage",
        )

    async def call(self, method, params=None, *, timeout=None):
        if timeout is None:
            timeout = (
                getattr(self._spec, "send_timeout", DEFAULT_SEND_TIMEOUT)
                + SEND_RECEIPT_MARGIN
                if method in OUTBOUND_METHODS and self._spec is not None
                else 5.0
            )
        if self._mode == "manage":
            from ...channel_protocol.management import (
                MANAGEMENT_CAPABILITIES,
                MANAGEMENT_METHOD,
                ManagementRequest,
            )

            if method != MANAGEMENT_METHOD or self._management_called:
                raise self.error_type("MANAGEMENT_UNSUPPORTED")
            request = ManagementRequest.from_mapping(params)
            spec = self._spec
            if any(
                getattr(request, name) != getattr(spec, name)
                for name in (
                    "plugin_id",
                    "workspace_id",
                    "channel_key",
                    "instance_id",
                    "generation",
                    "source_revision",
                )
            ):
                raise self.error_type("IDENTITY_MISMATCH")
            descriptor = spec.descriptor
            if (
                MANAGEMENT_CAPABILITIES[request.operation]
                not in descriptor.capabilities
            ):
                raise self.error_type("MANAGEMENT_UNSUPPORTED")
            self._management_called = True
        return await super().call(method, params, timeout=timeout)

    async def _evidence(self, params, request):
        result = await super()._evidence(params, request)
        from ...plugins.channel_bootstrap import validate_runtime_identity
        from ...plugins.execution.errors import ProtocolValidationError

        try:
            validate_runtime_identity(
                self.dependency_snapshot,
                self._spec.runtime_identity,
                self._spec.python_executable,
            )
        except ValueError as exc:
            reason = "CHANNEL_RUNTIME_IDENTITY_MISMATCH"
            if self._ready is not None and not self._ready.done():
                self._ready.set_exception(self.error_type(reason))
            raise ProtocolValidationError(reason, reason_code=reason) from exc
        return result

    def _identity(self, spec):
        return IdentityParams.from_mapping(
            {
                name: getattr(spec, name)
                for name in ("channel_key", "instance_id", "generation")
            },
        )

    def _snapshot_spec(self, spec):
        return replace(
            super()._snapshot_spec(spec),
            descriptor=SharedChannelDescriptor.from_mapping(
                spec.descriptor.to_mapping(),
            ),
            runtime_identity=(
                deepcopy(dict(spec.runtime_identity))
                if spec.runtime_identity is not None
                else None
            ),
        )

    def _validate_spec(self, spec):
        self._validate_launch(spec)
        descriptor = spec.descriptor
        validate_channel_contract(
            descriptor.channel_key,
            descriptor.capabilities,
        )
        self._identity(spec)

    def _prepare_spec(self, spec):
        self._validate_launch_paths(spec)
        path = Path(spec.descriptor_path)
        if not path.is_absolute() or not path.exists():
            raise ChannelProcessError("LAUNCH_PATH_INVALID")
        if not path.resolve().is_relative_to(Path(spec.code_root).resolve()):
            raise ChannelProcessError("DESCRIPTOR_OUTSIDE_CODE_ROOT")
        descriptor = SharedChannelDescriptor.load(spec.descriptor_path)
        requirements_path = path.parent / descriptor.requirements_file
        root = Path(spec.code_root).resolve()
        if not requirements_path.resolve().is_relative_to(root):
            raise self.error_type("DEPENDENCY_PATH_INVALID")
        requirements = _read_requirements(requirements_path)
        if (
            descriptor.to_mapping() != spec.descriptor.to_mapping()
            or descriptor.channel_key != spec.channel_key
            or requirements != spec.requirements
            or code_root_digest(root) != spec.source_revision
        ):
            raise self.error_type("SOURCE_REVISION_MISMATCH")
        return replace(
            spec,
            support_root=Path(spec.support_root).resolve(),
            code_root=root,
            descriptor_path=path.resolve(),
            dependency_paths=tuple(
                Path(p).resolve() for p in spec.dependency_paths
            ),
            descriptor=descriptor,
            requirements=requirements,
            config=deepcopy(dict(spec.config)),
            runtime_identity=deepcopy(spec.runtime_identity),
        )

    def _packet(self, spec):
        packet = {
            name: getattr(spec, name)
            for name in (
                "source_revision",
                "channel_key",
                "instance_id",
                "generation",
                "qwenpaw_version",
                "startup_timeout",
                "send_timeout",
            )
        }
        packet.update(
            {
                name: str(getattr(spec, name))
                for name in ("support_root", "code_root", "descriptor_path")
            },
        )
        packet["dependency_paths"] = [
            str(path) for path in spec.dependency_paths
        ]
        descriptor = spec.descriptor
        packet["requirements_path"] = str(
            (Path(spec.descriptor_path).parent / descriptor.requirements_file),
        )
        packet["config"] = dict(spec.config)
        packet["private_env"] = spec.private_env
        if self._mode == "manage":
            packet.update(
                plugin_id=spec.plugin_id,
                workspace_id=spec.workspace_id,
            )
        return self._encode_packet(packet)

    def _worker_path(self, spec):
        return (
            Path(spec.support_root)
            / "qwenpaw/channel_protocol/shared_worker.py"
        )

    def _make_peer(self, transport):
        return RpcPeer(transport)

    async def _hello(self, hello, _request):
        spec = self._spec
        descriptor = spec.descriptor
        validate_shared_hello(
            hello,
            channel_key=spec.channel_key,
            instance_id=spec.instance_id,
            generation=self._generation,
            source_revision=spec.source_revision,
            qwenpaw_version=spec.qwenpaw_version,
            capabilities=descriptor.capabilities,
            expected_requirements=spec.requirements,
        )
        self.observed_hello = (
            hello.to_mapping() if hasattr(hello, "to_mapping") else dict(hello)
        )
        self._endpoint_hello_binding = (self._peer, self._ready)
        return {"accepted": True}
