# -*- coding: utf-8 -*-
"""Owned, one-shot management of installed Channel sources."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from ...channel_protocol.artifacts import code_root_digest
from ...channel_protocol.errors import ProtocolValidationError, RpcError
from ...channel_protocol.management import (
    MANAGEMENT_CAPABILITIES,
    MANAGEMENT_METHOD,
    ManagementReason,
    ManagementRequest,
    ManagementResult,
    management_credential_keys,
    management_options,
)
from ...plugins.dependency_usage import DependencyDeclaration
from ...utils.io_utils import run_sync_io
from ...plugins.ownership import (
    RuntimeKey,
    RuntimeLease,
    RuntimeSourceBusyError,
    RuntimeStopReceipt,
)
from .process_supervisor import (
    ChannelProcess,
    LaunchSpec,
    ProcessError,
    CallUnknown,
)

if TYPE_CHECKING:
    from ...plugins.loader import PluginLoader


class ManagementError(RuntimeError):
    """Safe host outcome; never carry configuration or SDK exception text."""

    def __init__(
        self,
        reason_code: str,
        *,
        side_effect_possible: bool = False,
        needs_restart: bool = False,
        receipt: RuntimeStopReceipt | None = None,
        lease: RuntimeLease | None = None,
    ):
        self.reason_code = str(ManagementReason(reason_code))
        self.side_effect_possible = side_effect_possible
        self.needs_restart = needs_restart
        self.receipt = receipt
        self.lease = lease
        super().__init__(self.reason_code)


class ManagementCancelled(asyncio.CancelledError):
    reason_code = "MANAGEMENT_CANCELLED"

    def __init__(self, *, side_effect_possible: bool = False):
        self.side_effect_possible = side_effect_possible
        super().__init__(self.reason_code)


@dataclass
class _Work:
    lease: RuntimeLease
    process: ChannelProcess
    token: object = None
    task: asyncio.Task | None = None
    cleanup: asyncio.Task | None = None
    side_effect_possible: bool = False
    finished: bool = False


async def _settle(task):
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            continue
    return task.result(), cancelled


def _source_matches(current, snapshot):
    """Match description/settings/binding identity and source path value."""
    return not (
        any(current[index] is not snapshot[index] for index in range(3))
        or current[3] != snapshot[3]
    )


class ChannelManagementService:
    """Use existing exact custody, without starting message runtimes."""

    def __init__(self, loader: PluginLoader) -> None:
        self._loader = loader
        self._work: dict[RuntimeLease, _Work] = {}
        self._closed = False

    async def execute(
        self,
        workspace_id: str,
        channel_key: str,
        operation: str,
        parameters: Mapping[str, Any],
        *,
        timeout: float,
    ) -> ManagementResult:
        if self._closed:
            raise ManagementError("MANAGEMENT_CLOSED")
        if (
            any(
                not isinstance(value, str) or not value
                for value in (workspace_id, channel_key)
            )
            or not isinstance(operation, str)
            or operation not in MANAGEMENT_CAPABILITIES
            or type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0.001 <= timeout <= 65
        ):
            raise ManagementError("MANAGEMENT_INVALID_REQUEST")
        owners = self._loader.registry.runtime_owners
        usage = self._loader.registry.dependency_usage
        row = self._loader.registry.get_channel_catalog_entry(channel_key)
        if row is None or row.description_record is None:
            raise ManagementError("PLUGIN_NOT_INSTALLED")
        work = None
        try:
            async with self._loader.execution_source(row.plugin_id) as record:
                if self._closed:
                    raise ManagementError("MANAGEMENT_CLOSED")
                source = self._source_snapshot(row, record, channel_key)
                description, settings, _, _ = source
                if (
                    MANAGEMENT_CAPABILITIES[operation]
                    not in description.descriptor.capabilities
                ):
                    raise ManagementError("MANAGEMENT_UNSUPPORTED")
                leases = owners.leases()
                key = RuntimeKey("management", channel_key, workspace_id)
                if (
                    any(lease.key == key for lease in leases)
                    or sum(lease.key.kind == "management" for lease in leases)
                    >= 4
                ):
                    current = next(
                        (lease for lease in leases if lease.key == key),
                        None,
                    )
                    process = owners.resource(current) if current else None
                    cleanup = getattr(process, "last_cleanup", None)
                    raise ManagementError(
                        "MANAGEMENT_BUSY",
                        needs_restart=bool(
                            cleanup
                            and (not cleanup.exited or cleanup.residual),
                        ),
                    )
                values = self._parameters(description, parameters)
                lease = owners.reserve(
                    description.plugin_id,
                    key,
                    description.code_root,
                    instance_id=str(uuid4()),
                )
                try:
                    work = _Work(lease, ChannelProcess())
                    owners.attach(
                        lease,
                        lambda: self._stop(work, settings.shutdown_timeout),
                        resource=work.process,
                    )
                    work.token = usage.declare(
                        DependencyDeclaration(
                            description.plugin_id,
                            description.source_revision,
                            description.requirements,
                            None,
                        ),
                    )
                    usage.bind(lease, work.token)
                    work.process.dependency_observer = (
                        lambda snapshot: usage.observe(lease, snapshot)
                    )
                    request = ManagementRequest.from_mapping(
                        {
                            "request_id": str(uuid4()),
                            "plugin_id": description.plugin_id,
                            "workspace_id": workspace_id,
                            "channel_key": channel_key,
                            "instance_id": lease.instance_id,
                            "generation": lease.generation,
                            "source_revision": description.source_revision,
                            "operation": operation,
                            "timeout_ms": max(1, int(timeout * 1000)),
                            "parameters": values,
                        },
                    )
                    from ...plugins.official_channel_catalog import (
                        official_channel_for_plugin,
                    )

                    private_env = {}
                    official = official_channel_for_plugin(
                        description.plugin_id,
                    )
                    if official is not None and (
                        official["channel_key"] == channel_key
                    ):
                        import os
                        from pathlib import Path
                        from ...constant import WORKING_DIR
                        from ...plugins.official_execution_context import (
                            project_official_execution,
                        )

                        _, private_env = project_official_execution(
                            channel_key,
                            values["config"],
                            working_dir=Path.cwd(),
                            legacy_state_dir=WORKING_DIR,
                            environment=os.environ,
                        )
                    spec = LaunchSpec(
                        python_executable=settings.python_executable,
                        support_root=settings.support_root,
                        code_root=description.code_root,
                        descriptor_path=description.descriptor_path,
                        source_revision=description.source_revision,
                        descriptor=description.descriptor,
                        requirements=description.requirements,
                        channel_key=channel_key,
                        instance_id=lease.instance_id,
                        generation=lease.generation,
                        qwenpaw_version=settings.qwenpaw_version,
                        config={},
                        dependency_paths=settings.dependency_paths,
                        startup_timeout=settings.startup_timeout,
                        shutdown_timeout=settings.shutdown_timeout,
                        runtime_identity=settings.runtime_identity,
                        restart_limit=0,
                        plugin_id=description.plugin_id,
                        workspace_id=workspace_id,
                        private_env=private_env,
                    )
                except BaseException:
                    owners.release(
                        lease,
                        RuntimeStopReceipt(True, "PROCESS_NOT_STARTED"),
                    )
                    if work is not None and work.token is not None:
                        usage.withdraw(work.token)
                    work = None
                    raise
                self._work[lease] = work
            # Source validation belongs to this exact owner's tracked task.
            work.task = asyncio.create_task(
                self._execute(work, spec, request, row, record, source),
            )
            try:
                return await asyncio.shield(work.task)
            except asyncio.CancelledError:
                raise ManagementCancelled(
                    side_effect_possible=work.side_effect_possible,
                ) from None
        except (ProtocolValidationError, ValueError, TypeError):
            raise ManagementError("MANAGEMENT_INVALID_REQUEST") from None
        except RuntimeSourceBusyError:
            raise ManagementError("MANAGEMENT_BUSY") from None
        except ProcessError as exc:
            reason = (
                exc.reason_code
                if exc.reason_code
                in {"PLUGIN_NOT_INSTALLED", "PLUGIN_DISABLED"}
                else "CHANNEL_UNAVAILABLE"
            )
            raise ManagementError(
                reason,
                needs_restart=exc.reason_code == "SOURCE_UNAVAILABLE",
            ) from None
        finally:
            if work is not None:
                if await self._finish(work):
                    raise ManagementCancelled(
                        side_effect_possible=work.side_effect_possible,
                    ) from None

    def _source_snapshot(self, row, record, channel_key):
        if (
            self._loader.registry.get_channel_catalog_entry(channel_key)
            is not row
        ):
            raise ManagementError("PLUGIN_NOT_INSTALLED")
        if self._loader.get_loaded_plugin(row.plugin_id) is not record:
            raise ManagementError("PLUGIN_NOT_INSTALLED")
        description = row.description_record
        binding = record.backend_binding
        if (
            description is None
            or description.plugin_id != row.plugin_id
            or record.manifest.id != row.plugin_id
            or binding is None
            or binding.description.payload != description
        ):
            raise ManagementError("CHANNEL_UNAVAILABLE")
        enabled = record.global_enabled
        if not row.global_enabled or not (
            record.enabled if enabled is None else enabled
        ):
            raise ManagementError("PLUGIN_DISABLED")
        settings = row.runtime_settings
        if settings is None or not settings.allows(channel_key):
            raise ManagementError("CHANNEL_UNAVAILABLE")
        return description, settings, binding, record.source_path

    async def _source(self, row, record, channel_key, *, snapshot=None):
        current = self._source_snapshot(row, record, channel_key)
        if snapshot is None:
            snapshot = current
        elif not _source_matches(current, snapshot):
            raise ManagementError("SOURCE_REVISION_MISMATCH")
        description, settings, _, source_path = snapshot
        code_root = description.code_root
        expected_revision = description.source_revision

        def read_source():
            if source_path.resolve() != code_root.resolve():
                raise ManagementError("CHANNEL_UNAVAILABLE")
            return code_root_digest(code_root)

        try:
            revision = await run_sync_io(read_source)
        except (OSError, ValueError, RuntimeError):
            raise ManagementError("SOURCE_REVISION_MISMATCH") from None
        current = self._source_snapshot(row, record, channel_key)
        if not _source_matches(current, snapshot):
            raise ManagementError("SOURCE_REVISION_MISMATCH")
        if revision != expected_revision:
            raise ManagementError("SOURCE_REVISION_MISMATCH")
        return description, settings

    @staticmethod
    def private_config_fields():
        """Execution authority is never a management config parameter."""
        private = set(LaunchSpec.__dataclass_fields__) - {"config", "enabled"}
        private.update(
            {
                "workspace_dir",
                "media_dir",
                "token_file",
                "token_file_path",
                "bot_token_file",
                "context_file",
                "context_tokens_file",
                "entrypoint",
                "management_entrypoint",
                "credential_keys",
            },
        )
        return frozenset(private)

    @staticmethod
    def _parameters(description, parameters):
        from ...plugins.channel_config import validate_channel_config

        if not isinstance(parameters, Mapping) or not isinstance(
            parameters.get("config"),
            Mapping,
        ):
            raise ManagementError("MANAGEMENT_INVALID_REQUEST")
        private = ChannelManagementService.private_config_fields()
        if private.intersection(parameters["config"]):
            raise ManagementError("MANAGEMENT_INVALID_REQUEST")
        try:
            config = validate_channel_config(
                description.descriptor.config_schema,
                parameters["config"],
            )
            options = (
                {
                    "options": management_options(
                        parameters["options"],
                        fields=description.descriptor.config_schema.get(
                            "properties",
                            {},
                        ),
                        forbidden=private,
                    ),
                }
                if "options" in parameters
                else {}
            )
        except (ValueError, TypeError):
            raise ManagementError("MANAGEMENT_INVALID_REQUEST") from None
        return {
            **parameters,
            **options,
            "config": {
                key: value
                for key, value in config.items()
                if key not in private
            },
        }

    async def _execute(self, work, spec, request, row, record, source):
        try:
            description, _ = await self._source(
                row,
                record,
                request.channel_key,
                snapshot=source,
            )
            if self._closed:
                raise ManagementError("MANAGEMENT_CLOSED")
            owners = self._loader.registry.runtime_owners
            if (
                work.lease not in owners.leases()
                or owners.resource(work.lease) is not work.process
            ):
                raise ManagementError("IDENTITY_MISMATCH")
            await work.process.start_management(spec)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + request.timeout_ms / 1000
            data = request.to_mapping()
            data["timeout_ms"] = max(1, int((deadline - loop.time()) * 1000))
            request = ManagementRequest.from_mapping(data)
            work.side_effect_possible = True
            try:
                value = await work.process.call(
                    MANAGEMENT_METHOD,
                    request.to_mapping(),
                    timeout=max(0.001, deadline - loop.time()),
                )
            except CallUnknown:
                reason = (
                    "MANAGEMENT_TIMEOUT"
                    if loop.time() >= deadline
                    else "PLATFORM_RESULT_UNKNOWN"
                )
                raise ManagementError(
                    reason,
                    side_effect_possible=True,
                ) from None
            result = ManagementResult.from_mapping(value)
            result.validate_for(
                request,
                credential_keys=management_credential_keys(
                    description.descriptor.channel_key,
                    description.descriptor.config_schema,
                ),
            )
            if (
                result.outcome == "ok"
                and result.operation == "qrcode.poll"
                and set(result.result.get("metadata", {})).intersection(
                    description.descriptor.config_schema.get("properties", {}),
                )
            ):
                raise ProtocolValidationError(
                    "management metadata cannot replace configuration",
                    reason_code="MANAGEMENT_INVALID_RESULT",
                )
            return result
        except (ProcessError, RpcError, ProtocolValidationError) as exc:
            reason = getattr(exc, "reason_code", None)
            if isinstance(exc, RpcError) and isinstance(exc.data, Mapping):
                reason = exc.data.get("reason_code")
            if reason not in {item.value for item in ManagementReason}:
                reason = (
                    "PLATFORM_RESULT_UNKNOWN"
                    if work.side_effect_possible
                    else "CHANNEL_UNAVAILABLE"
                )
            raise ManagementError(
                reason,
                side_effect_possible=work.side_effect_possible,
            ) from None

    async def _stop(self, work, budget):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget
        if work.task is not None and not work.task.done():
            work.task.cancel()
        try:
            result = await work.process.stop(timeout=budget)
            residual = result.residual
            if work.task is not None and not work.task.done():
                done, _ = await asyncio.wait(
                    {work.task},
                    timeout=max(0, deadline - loop.time()),
                )
                if not done:
                    residual = (*residual, "MANAGEMENT_OPERATION_PENDING")
            stopped = result.exited and not residual
            if stopped:
                # Lifecycle callers can recover a retained lease after execute
                # has already failed; do not leave its admission pending.
                self._loader.registry.dependency_usage.withdraw(work.token)
                self._work.pop(work.lease, None)
            return RuntimeStopReceipt(
                stopped,
                "" if stopped else "MANAGEMENT_CLEANUP_FAILED; needs_restart",
                result.exited,
                result.returncode,
                result.forced,
                residual,
            )
        except Exception:
            return RuntimeStopReceipt(
                False,
                "MANAGEMENT_CLEANUP_FAILED; needs_restart",
                exited=False,
            )

    async def _finish(self, work):
        if work.finished:
            return False
        if work.cleanup is None or work.cleanup.done():
            work.cleanup = asyncio.create_task(
                self._loader.registry.runtime_owners.stop(work.lease),
            )
        receipt, cancelled = await _settle(work.cleanup)
        if not receipt.stopped:
            raise ManagementError(
                "MANAGEMENT_CLEANUP_FAILED",
                side_effect_possible=work.side_effect_possible,
                needs_restart=True,
                receipt=receipt,
                lease=work.lease,
            )
        self._loader.registry.dependency_usage.withdraw(work.token)
        self._work.pop(work.lease, None)
        work.finished = True
        return cancelled

    async def aclose(self) -> None:
        self._closed = True
        failure = None
        cancelled = False
        for work in tuple(self._work.values()):
            try:
                cancelled = await self._finish(work) or cancelled
            except ManagementError as exc:
                failure = exc
        if failure is not None:
            raise failure
        if cancelled:
            raise ManagementCancelled()
