# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Shared Channel handshake and context adapter for the common worker."""

from __future__ import annotations
import asyncio
import importlib.util
import inspect
import os
from pathlib import Path
import sys
from typing import Any


class DriverContext:
    """Preserve the Channel context and platform state wire contract."""

    def __init__(
        self,
        peer: Any,
        identity: Any,
        capabilities=(),
        *,
        send_timeout=120.0,
    ) -> None:
        from .outbound_budget import validate_send_timeout

        self.peer, self.identity = peer, identity
        self.capabilities = frozenset(capabilities)
        self.send_timeout = validate_send_timeout(send_timeout)

    async def notify_auth_required(self, scan_url: str) -> None:
        from .errors import ProtocolValidationError
        from .models import AUTH_QRCODE_CAPABILITY, AuthRequiredParams

        if AUTH_QRCODE_CAPABILITY not in self.capabilities:
            raise ProtocolValidationError(
                "QR authentication capability was not declared",
                reason_code="CAPABILITY_REQUIRED",
            )
        params = AuthRequiredParams.from_mapping(
            {**self.identity.to_mapping(), "scan_url": scan_url},
        )
        await self.peer.notify("channel.auth.required", params.to_mapping())

    async def set_platform_state(self, state: str) -> None:
        if state not in {"connecting", "connected", "disconnected", "failed"}:
            raise ValueError("PLATFORM_STATE_INVALID")
        await self.peer.notify(
            "shared.state",
            {**self.identity.to_mapping(), "platform_state": state},
        )


class ChannelRuntime:
    hello_method = "runner.hello"
    control_prefix = "shared."
    initial_state = "connecting"
    failed_state = "failed"

    def identity(self, packet):
        from .models import IdentityParams

        return IdentityParams.from_mapping(
            {
                name: packet[name]
                for name in ("channel_key", "instance_id", "generation")
            },
        )

    def peer(self, transport):
        from .errors import RPC_LIFECYCLE_ERROR, RpcError
        from .outbound_budget import (
            OUTBOUND_METHODS,
            await_send,
            send_budget,
        )
        from .rpc import RpcPeer

        runtime = self

        class ChannelPeer(RpcPeer):
            def register_method(self, method, handler):
                if method not in OUTBOUND_METHODS:
                    return super().register_method(method, handler)

                async def execute(params, request):
                    with send_budget(getattr(runtime, "_send_timeout", 120.0)):
                        if getattr(handler, "_channel_effect_budget", False):
                            return await handler(params, request)
                        try:
                            return await await_send(handler(params, request))
                        except TimeoutError as exc:
                            raise RpcError(
                                RPC_LIFECYCLE_ERROR,
                                "outbound result unknown",
                                data={
                                    "reason_code": "PLATFORM_RESULT_UNKNOWN",
                                    "retryable": False,
                                },
                            ) from exc

                return super().register_method(method, execute)

        return ChannelPeer(transport, params_validator=self._validate_params)

    def _validate_params(self, method, params):
        from .models import (
            validate_method_params,
            send_source_capability,
            RAW_COMPLETED_TEXT_CAPABILITY,
            APPROVAL_RESOLUTION_CAPABILITY,
        )
        from .errors import ProtocolValidationError

        parsed = validate_method_params(method, params)
        if method == "channel.send":
            source_capability = send_source_capability(
                parsed.content_source,
                self._capabilities,
            )
            for field, capability in (
                ("content_source", source_capability),
                ("approval_resolution", APPROVAL_RESOLUTION_CAPABILITY),
                ("raw_completed_text_sources", RAW_COMPLETED_TEXT_CAPABILITY),
            ):
                if field in params and capability not in self._capabilities:
                    raise ProtocolValidationError(
                        "Send capability was not declared",
                        reason_code="CAPABILITY_REQUIRED",
                    )
        return parsed

    def context(self, peer, identity):
        return DriverContext(
            peer,
            identity,
            self._capabilities,
            send_timeout=getattr(self, "_send_timeout", 120.0),
        )

    async def state(self, context, state):
        await context.set_platform_state(state)

    def bind_management(self, packet, component_class, peer, identity):
        """Bind only the fixed static operation, never a Driver instance."""
        from .errors import ProtocolValidationError
        from .management import (
            MANAGEMENT_CAPABILITIES,
            MANAGEMENT_METHOD,
            ManagementRequest,
            ManagementResult,
            ManagementReason,
            management_credential_keys,
        )
        from .shared import SharedChannelDescriptor

        method = inspect.getattr_static(component_class, "manage", None)
        function = (
            method.__func__ if isinstance(method, staticmethod) else None
        )
        parameters = (
            tuple(inspect.signature(function).parameters.values())
            if function
            else ()
        )
        if (
            not inspect.iscoroutinefunction(function)
            or len(parameters) != 1
            or parameters[0].kind
            not in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ):
            raise ProtocolValidationError(
                "invalid static management entrypoint",
                reason_code="ENTRYPOINT_INVALID",
            )
        descriptor = SharedChannelDescriptor.load(packet["descriptor_path"])
        keys = management_credential_keys(
            descriptor.channel_key,
            descriptor.config_schema,
        )
        scope = {
            **identity.to_mapping(),
            **{
                name: packet.get(name)
                for name in ("plugin_id", "workspace_id", "source_revision")
            },
        }
        if any(
            not isinstance(scope[name], str) or not scope[name]
            for name in ("plugin_id", "workspace_id")
        ):
            raise ProtocolValidationError(
                "invalid management scope",
                reason_code="IDENTITY_MISMATCH",
            )
        used = False
        current = None

        async def execute(params, _request):
            nonlocal used, current
            if used:
                raise ProtocolValidationError(
                    "management already executed",
                    reason_code="MANAGEMENT_UNSUPPORTED",
                )
            used = True
            request = ManagementRequest.from_mapping(
                (
                    params.to_mapping()
                    if isinstance(params, ManagementRequest)
                    else params
                ),
            )
            if any(
                getattr(request, name) != value
                for name, value in scope.items()
            ):
                raise ProtocolValidationError(
                    "management scope mismatch",
                    reason_code="IDENTITY_MISMATCH",
                )
            if (
                MANAGEMENT_CAPABILITIES[request.operation]
                not in descriptor.capabilities
            ):
                raise ProtocolValidationError(
                    "management capability unavailable",
                    reason_code="MANAGEMENT_UNSUPPORTED",
                )
            current = asyncio.current_task()
            try:
                try:
                    value = await asyncio.wait_for(
                        function(request),
                        request.timeout_ms / 1000,
                    )
                except asyncio.TimeoutError:
                    raise ProtocolValidationError(
                        "management timed out",
                        reason_code="MANAGEMENT_TIMEOUT",
                    ) from None
                except ProtocolValidationError as exc:
                    reason = (
                        exc.reason_code
                        if exc.reason_code
                        in {item.value for item in ManagementReason}
                        else "PLATFORM_REQUEST_FAILED"
                    )
                    raise ProtocolValidationError(
                        "management operation rejected",
                        reason_code=reason,
                    ) from None
                except Exception:
                    raise ProtocolValidationError(
                        "management operation failed",
                        reason_code="PLATFORM_REQUEST_FAILED",
                    ) from None
                result = ManagementResult.from_mapping(
                    (
                        value.to_mapping()
                        if isinstance(value, ManagementResult)
                        else value
                    ),
                )
                result.validate_for(request, credential_keys=keys)
                return result.to_mapping()
            finally:
                current = None

        async def drain():
            task = current
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        peer.register_method(MANAGEMENT_METHOD, execute)
        return drain

    def verify(self, boot, packet, identity):
        from .runner_host import RunnerProtocolHost
        from .shared import SharedChannelDescriptor
        from .outbound_budget import (
            DEFAULT_SEND_TIMEOUT,
            validate_send_timeout,
        )

        self._send_timeout = validate_send_timeout(
            packet.get("send_timeout", DEFAULT_SEND_TIMEOUT),
        )
        root = Path(packet["code_root"])
        if boot._hash_code_root(root) != packet["source_revision"]:
            raise boot.BootstrapError(
                "SOURCE_REVISION_MISMATCH",
                "source mismatch",
            )
        path = boot._absolute_existing_file(
            packet["descriptor_path"],
            "descriptor_path",
        )
        if not path.is_relative_to(root):
            raise boot.BootstrapError(
                "DESCRIPTOR_OUTSIDE_CODE_ROOT",
                "descriptor outside root",
            )
        descriptor = SharedChannelDescriptor.load(path)
        from .shared import validate_channel_contract

        validate_channel_contract(
            descriptor.channel_key,
            descriptor.capabilities,
        )
        self._capabilities = descriptor.capabilities
        if descriptor.channel_key != identity.channel_key:
            raise boot.BootstrapError("IDENTITY_MISMATCH", "identity mismatch")
        requirements = (path.parent / descriptor.requirements_file).resolve(
            strict=True,
        )
        if not requirements.is_relative_to(root):
            raise boot.BootstrapError(
                "DEPENDENCY_PATH_INVALID",
                "requirements outside root",
            )
        source = boot._entrypoint_source(root, descriptor.entrypoint)
        hello = RunnerProtocolHost(
            packet["source_revision"],
        ).create_shared_hello(
            channel_key=identity.channel_key,
            instance_id=identity.instance_id,
            generation=identity.generation,
            qwenpaw_version=packet["qwenpaw_version"],
            requirements_path=requirements,
            capabilities=descriptor.capabilities,
            versions=packet.get("dependency_versions"),
        )
        return descriptor.entrypoint, source, hello.to_mapping()


def main() -> int:
    path = Path(__file__).resolve().parents[1] / "plugins/execution/worker.py"
    spec = importlib.util.spec_from_file_location(
        "_qwenpaw_execution_worker",
        path,
    )
    if spec is None or spec.loader is None:
        return 70
    worker = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = worker
    spec.loader.exec_module(worker)

    def runtime():
        runtime_class = importlib.import_module(
            "qwenpaw.channel_protocol.shared_worker",
        ).ChannelRuntime
        return runtime_class()

    return worker.main(
        runtime,
        protected_namespaces=(
            "qwenpaw/channel_protocol",
            "qwenpaw/channel_protocol.py",
        ),
    )


if __name__ == "__main__":
    os._exit(main())
