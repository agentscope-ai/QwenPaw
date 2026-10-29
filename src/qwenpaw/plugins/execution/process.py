# -*- coding: utf-8 -*-
"""Explicit shared-environment component supervision."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import json
import math
import os
from pathlib import Path
from typing import Any

from ...utils.io_utils import run_async_to_completion, run_sync_io

from .bootstrap import (
    BootstrapError,
    NETWORK_PROXY_ENVIRONMENT,
    validate_private_environment,
)
from .dependencies import DependencySnapshot
from .errors import FrameError, RpcClosedError, RpcTimeoutError
from .framing import FramedTransport
from .payloads import PayloadLimits, PayloadStore
from .models import PluginIdentity
from .process_tree import ProcessTree
from .rpc import RpcCallNotSent, RpcPeer
from .runtime import validate_hello, _requirements
from .worker_logs import WorkerLogs


@dataclass(frozen=True)
class PluginLaunchSpec:
    """Explicit trusted roots and private component launch data."""

    python_executable: str
    support_root: Path
    code_root: Path
    source_revision: str
    plugin_id: str
    instance_id: str
    generation: int
    entrypoint: str
    config: Mapping[str, Any] = field(repr=False)
    dependency_paths: tuple[Path, ...] = ()
    requirements_path: Path | None = None
    requirements: tuple[str, ...] = ()
    enabled: bool = True
    startup_timeout: float = 5.0
    shutdown_timeout: float = 2.0
    restart_limit: int = 0
    restart_backoff: float = 0.1
    private_env: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        object.__setattr__(
            self,
            "private_env",
            validate_private_environment(self.private_env),
        )


@dataclass(frozen=True)
class StopResult:
    """B-internal cleanup evidence, not the application StopReceipt."""

    exited: bool
    returncode: int | None
    forced: bool
    residual: tuple[str, ...] = ()


@dataclass(frozen=True)
class InspectionResult:
    """One-shot evidence is usable only after confirmed child-tree exit."""

    snapshot: DependencySnapshot
    hello: Mapping[str, Any] | None
    cleanup: StopResult


class ProcessError(RuntimeError):
    """Expose a safe reason code without launch data or SDK exceptions."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class CallUnknown(ProcessError):
    """A transmitted request may have completed despite a lost reply."""

    def __init__(self, request_id: str, method: str, generation: int) -> None:
        super().__init__("PLATFORM_RESULT_UNKNOWN")
        self.request_id, self.method, self.generation = (
            request_id,
            method,
            generation,
        )


async def _settle(task: asyncio.Task[Any]) -> Any:
    """Finish owned cleanup even under repeated caller cancellation."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


class PluginProcess:
    """Own one generation and its process tree until confirmed exit."""

    identity_type = PluginIdentity
    error_type = ProcessError
    unknown_type = CallUnknown
    hello_method = "execution.hello"
    control_prefix = "execution."
    state_key = "component_state"
    request_prefix = "plugin"
    component_states = {"starting", "ready", "failed", "stopped"}
    startup_errors = {
        "SOURCE_REVISION_MISMATCH",
        "DESCRIPTOR_OUTSIDE_CODE_ROOT",
        "IDENTITY_MISMATCH",
        "DEPENDENCY_PATH_INVALID",
        "HELLO_REJECTED",
        "ENTRYPOINT_INVALID",
        "ENTRYPOINT_OUTSIDE_CODE_ROOT",
        "ENTRYPOINT_IMPORT_FAILED",
        "DEPENDENCY_UNSATISFIED",
        "DEPENDENCY_METADATA_INVALID",
        "DEPENDENCY_ENVIRONMENT_AMBIGUOUS",
        "DEPENDENCY_REPAIR_REQUIRED",
        "DEPENDENCY_ORIGIN_INVALID",
        "PROBE_NETWORK_OR_PROCESS_DENIED",
        "SCHEMA_MISMATCH",
        "PROTOCOL_MISMATCH",
    }
    initial_state = "stopped"
    connecting_state = "starting"
    failed_reason = "COMPONENT_START_FAILED"

    def __init__(self, *, payload_limits: PayloadLimits | None = None) -> None:
        self._payload_limits = (
            PayloadLimits() if payload_limits is None else payload_limits
        )
        if not isinstance(self._payload_limits, PayloadLimits):
            raise ValueError("PayloadLimits required")
        self._payloads: PayloadStore | None = None
        self._spec: PluginLaunchSpec | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._spawn_task: asyncio.Task[Any] | None = None
        self._spawn_error: str | None = None
        self._tree: ProcessTree | None = None
        self._peer: RpcPeer | None = None
        self._start_task: asyncio.Task[Any] | None = None
        self._stop_task: asyncio.Task[Any] | None = None
        self._cleanup_task: asyncio.Task[Any] | None = None
        self._monitor_task: asyncio.Task[Any] | None = None
        self._log_task: asyncio.Task[Any] | None = None
        self._closed_task: asyncio.Task[Any] | None = None
        self._ready: asyncio.Future[Any] | None = None
        self._methods: dict[str, Any] = {}
        self._notifications: dict[str, Any] = {}
        self._unknown: deque[dict[str, Any]] = deque(maxlen=128)
        self._state = "idle"
        self._platform = self.initial_state
        self._last_error: str | None = None
        self._returncode: int | None = None
        self._restart_enabled = False
        self._restart_count = 0
        self._generation = 0
        self._counter = 0
        self._log_bytes = 0
        self._forced = False
        self._mode = "run"
        self.dependency_snapshot: DependencySnapshot | None = None
        self.dependency_observer = None
        self.observed_hello: Mapping[str, Any] | None = None
        self.last_cleanup: StopResult | None = None

    async def audit(self, spec: PluginLaunchSpec) -> InspectionResult:
        """Read real child metadata without importing candidate code."""
        return await self._inspect(spec, "audit")

    async def probe(self, spec: PluginLaunchSpec) -> InspectionResult:
        """Check Driver import/interface without creating a consumer."""
        return await self._inspect(spec, "probe")

    async def _inspect(self, spec: Any, mode: str) -> InspectionResult:
        if mode not in {"audit", "probe"}:
            raise self.error_type("EXECUTION_MODE_INVALID")
        if (
            self._process is not None
            or self._payloads is not None
            or any(
                task is not None and not task.done()
                for task in (
                    self._start_task,
                    self._stop_task,
                    self._monitor_task,
                    self._spawn_task,
                    self._cleanup_task,
                )
            )
        ):
            raise self.error_type("PROCESS_OWNED")
        spec = replace(spec, config={}, enabled=True, restart_limit=0)
        spec = self._snapshot_spec(spec)
        self._validate_spec(spec)
        self._spec, self._generation, self._mode = spec, spec.generation, mode
        self._restart_enabled = False
        self.dependency_snapshot = self.observed_hello = None
        self.last_cleanup = None
        self._start_task = asyncio.create_task(self._launch(spec))
        try:
            try:
                await asyncio.shield(self._start_task)
            except asyncio.CancelledError:
                self._start_task.cancel()
                try:
                    await _settle(self._start_task)
                except (asyncio.CancelledError, Exception):
                    pass
                raise
        finally:
            cleanup = await _settle(
                asyncio.create_task(
                    self._cleanup(spec.shutdown_timeout, graceful=False),
                ),
            )
            self.last_cleanup = cleanup
            if not cleanup.exited or cleanup.residual:
                self._state = "residual"
                error = self.error_type("PROBE_CLEANUP_FAILED")
                error.process = self
                error.cleanup = cleanup
                raise error
            self._state, self._mode = "stopped", "run"
        if self.dependency_snapshot is None:
            raise self.error_type("DEPENDENCY_METADATA_INVALID")
        return InspectionResult(
            self.dependency_snapshot,
            self.observed_hello,
            cleanup,
        )

    async def _evidence(self, params: Any, _request: Any) -> dict[str, bool]:
        assert self._spec is not None
        if not isinstance(params, Mapping) or set(params) != {
            "identity",
            "snapshot",
        }:
            raise self.error_type("DEPENDENCY_METADATA_INVALID")
        if params["identity"] != self._identity(self._spec).to_mapping():
            raise self.error_type("IDENTITY_MISMATCH")
        snapshot = DependencySnapshot.from_mapping(params["snapshot"])
        excluded = (self._spec.code_root,)
        if any(
            Path(site).is_relative_to(root)
            for site in snapshot.sites
            for root in excluded
        ):
            raise self.error_type("DEPENDENCY_ORIGIN_INVALID")
        self.dependency_snapshot = snapshot
        if self.dependency_observer is not None:
            self.dependency_observer(snapshot)
        return {"accepted": True}

    def _register(
        self,
        target: dict[str, Any],
        name: str,
        handler: Any,
    ) -> None:
        if self._mode == "manage":
            raise self.error_type("MODE_METHODS_DISABLED")
        if (
            self._state not in {"idle", "stopped", "disabled", "failed"}
            or self._process is not None
        ):
            raise self.error_type("PROCESS_OWNED")
        if (
            not name
            or name.startswith(self.control_prefix)
            or name in {self.hello_method, "execution.dependencies"}
            or name in target
            or not callable(handler)
        ):
            raise ValueError("invalid or reserved method")
        target[name] = handler

    def register_method(self, name: str, handler: Any) -> None:
        """Register a host request handler before launch."""
        self._register(self._methods, name, handler)

    def register_notification(self, name: str, handler: Any) -> None:
        """Register a host notification handler before launch."""
        self._register(self._notifications, name, handler)

    def health_snapshot(self) -> dict[str, Any]:
        """Return bounded safe diagnostics without starting any work."""
        return {
            "state": self._state,
            self.state_key: self._platform,
            "pid": self._process.pid if self._process else None,
            "generation": self._generation,
            "returncode": self._returncode,
            "restart_count": self._restart_count,
            "last_error": self._last_error,
            "log_bytes": self._log_bytes,
            "unknown_outcomes": [dict(item) for item in self._unknown],
        }

    async def start(self, spec: PluginLaunchSpec) -> dict[str, Any]:
        """Handshake and bind a component before awaiting its external work."""
        return await self._start(spec, mode="run")

    async def _start(self, spec: Any, *, mode: str) -> dict[str, Any]:
        """Share startup custody while keeping explicit modes separate."""
        if mode not in {"run", "manage"}:
            raise self.error_type("EXECUTION_MODE_INVALID")
        if (
            self._process is not None
            or self._payloads is not None
            or any(
                task is not None and not task.done()
                for task in (
                    self._start_task,
                    self._stop_task,
                    self._monitor_task,
                    self._spawn_task,
                    self._cleanup_task,
                )
            )
        ):
            raise self.error_type("PROCESS_OWNED")
        if not spec.enabled:
            self._state = "disabled"
            return self.health_snapshot()
        spec = self._snapshot_spec(spec)
        self._validate_spec(spec)
        self._mode = mode
        self.dependency_snapshot = self.observed_hello = None
        self._spec = spec
        self._generation = spec.generation
        self._restart_count = 0
        self._restart_enabled = mode == "run"
        self._start_task = asyncio.create_task(self._launch(spec))
        try:
            await asyncio.shield(self._start_task)
        except asyncio.CancelledError:
            self._restart_enabled = False
            self._start_task.cancel()
            try:
                await _settle(self._start_task)
            except (asyncio.CancelledError, Exception):
                pass
            await _settle(
                asyncio.create_task(
                    self._cleanup(spec.shutdown_timeout, graceful=False),
                ),
            )
            raise
        self._monitor_task = asyncio.create_task(self._monitor())
        return self.health_snapshot()

    def _snapshot_spec(self, spec):
        return replace(
            spec,
            config=deepcopy(dict(spec.config)),
            private_env=dict(spec.private_env),
        )

    def _validate_launch(self, spec: Any) -> None:
        try:
            validate_private_environment(getattr(spec, "private_env", {}))
        except BootstrapError:
            raise self.error_type("LAUNCH_ENVIRONMENT_INVALID") from None
        for value in (
            spec.startup_timeout,
            spec.shutdown_timeout,
            spec.restart_backoff,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise self.error_type("LAUNCH_INVALID")
        if (
            isinstance(spec.restart_limit, bool)
            or not isinstance(spec.restart_limit, int)
            or spec.restart_limit < 0
        ):
            raise self.error_type("LAUNCH_INVALID")
        try:
            self._identity(spec)
        except ValueError:
            raise self.error_type("LAUNCH_INVALID") from None
        if (
            not isinstance(spec.source_revision, str)
            or len(spec.source_revision) != 64
            or any(c not in "0123456789abcdef" for c in spec.source_revision)
        ):
            raise self.error_type("LAUNCH_INVALID")

    def _validate_spec(self, spec: PluginLaunchSpec) -> None:
        self._validate_launch(spec)
        if (
            not isinstance(spec.entrypoint, str)
            or spec.entrypoint.count(":") != 1
            or any(
                not part.isidentifier()
                for segment in spec.entrypoint.split(":")
                for part in segment.split(".")
            )
        ):
            raise self.error_type("ENTRYPOINT_INVALID")

    def _prepare_spec(self, spec):
        self._validate_launch_paths(spec)
        if spec.requirements_path is not None:
            path = Path(spec.requirements_path)
            if (
                not path.is_absolute()
                or not path.is_file()
                or not path.resolve().is_relative_to(
                    Path(spec.code_root).resolve(),
                )
            ):
                raise self.error_type("DEPENDENCY_PATH_INVALID")

        return replace(
            spec,
            support_root=Path(spec.support_root).resolve(),
            code_root=Path(spec.code_root).resolve(),
            dependency_paths=tuple(
                Path(p).resolve() for p in spec.dependency_paths
            ),
            requirements_path=(
                Path(spec.requirements_path).resolve()
                if spec.requirements_path is not None
                else None
            ),
            requirements=_requirements(spec.requirements_path),
            config=deepcopy(dict(spec.config)),
        )

    def _validate_launch_paths(self, spec):
        if not self._worker_path(spec).is_file():
            raise self.error_type("BOOTSTRAP_UNAVAILABLE")
        for value in (
            spec.python_executable,
            spec.support_root,
            spec.code_root,
            *spec.dependency_paths,
        ):
            path = Path(str(value))
            if not path.is_absolute() or not path.exists():
                raise self.error_type("LAUNCH_PATH_INVALID")
        for value in (
            spec.support_root,
            spec.code_root,
            *spec.dependency_paths,
        ):
            if not Path(value).is_dir():
                raise self.error_type("LAUNCH_PATH_INVALID")

    def _packet(self, spec: PluginLaunchSpec) -> bytes:
        packet = {
            name: getattr(spec, name)
            for name in ("source_revision", "entrypoint", "startup_timeout")
        }
        packet.update(self._identity(spec).to_mapping())
        packet.update(
            {
                name: str(getattr(spec, name))
                for name in ("support_root", "code_root")
            },
        )
        packet["requirements_path"] = (
            str(spec.requirements_path)
            if spec.requirements_path is not None
            else None
        )
        packet["dependency_paths"] = [
            str(path) for path in spec.dependency_paths
        ]
        packet["config"] = dict(spec.config)
        packet["private_env"] = getattr(spec, "private_env", {})
        return self._encode_packet(packet)

    def _encode_packet(self, packet: Mapping[str, Any]) -> bytes:
        if self._mode not in {"run", "manage", "audit", "probe"}:
            raise self.error_type("EXECUTION_MODE_INVALID")
        packet = {**packet, "mode": self._mode}
        if self._payloads is not None:
            packet["payload_transport"] = self._payloads.launch_context()
        try:
            private_env = validate_private_environment(
                packet.pop("private_env", {}),
            )
        except BootstrapError:
            raise self.error_type("LAUNCH_ENVIRONMENT_INVALID") from None
        if private_env and self._mode in {"run", "manage"}:
            packet["private_env"] = private_env
        if self._mode != "run":
            packet["config"] = {}
        try:
            data = (
                json.dumps(packet, allow_nan=False, separators=(",", ":"))
                + "\n"
            ).encode()
        except (ValueError, TypeError):
            raise self.error_type("LAUNCH_INVALID") from None
        if len(data) > 1024 * 1024:
            raise self.error_type("LAUNCH_TOO_LARGE")
        return data

    def _identity(self, spec: PluginLaunchSpec) -> PluginIdentity:
        return PluginIdentity(
            spec.plugin_id,
            spec.instance_id,
            spec.generation,
        )

    def _worker_path(self, spec: PluginLaunchSpec) -> Path:
        return Path(spec.support_root) / "qwenpaw/plugins/execution/worker.py"

    def _make_peer(self, transport: FramedTransport) -> RpcPeer:
        return RpcPeer(transport)

    async def _launch(self, spec: PluginLaunchSpec) -> None:
        self._state, self._platform = "starting", self.initial_state
        self._last_error = None
        self._forced = False
        self._cleanup_task = None
        self._ready = None
        self.observed_hello = None
        try:

            async def prepare_and_open():
                prepared = await run_sync_io(self._prepare_spec, spec)
                self._spec = prepared
                await self._open(prepared)

            await asyncio.wait_for(prepare_and_open(), spec.startup_timeout)
            self._state = "ready"
        except BaseException as exc:
            self._last_error = (
                "STARTUP_TIMEOUT"
                if isinstance(exc, asyncio.TimeoutError)
                else getattr(exc, "reason_code", "STARTUP_FAILED")
            )
            await self._cleanup(spec.shutdown_timeout, graceful=False)
            if self._state != "residual":
                self._state = "failed"
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise self.error_type(self._last_error) from None

    async def _open(self, spec: PluginLaunchSpec) -> None:
        async def create_payloads():
            self._payloads = await PayloadStore.acreate(self._payload_limits)

        await run_async_to_completion(create_payloads())
        packet = self._packet(spec)
        worker = self._worker_path(spec)
        self._ready = asyncio.get_running_loop().create_future()
        environment = {
            name: value
            for name, value in os.environ.items()
            if name.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "SYSTEMDRIVE",
                "WINDIR",
                "COMSPEC",
                "PATHEXT",
                "PROCESSOR_ARCHITECTURE",
                "PROCESSOR_ARCHITEW6432",
                "TEMP",
                "TMP",
                "TMPDIR",
                "SSL_CERT_FILE",
                "QWENPAW_DEPENDENCY_MAINTENANCE",
            }
            or name in NETWORK_PROXY_ENVIRONMENT
        }
        if ca_file := environment.get("SSL_CERT_FILE"):
            environment["SSL_CERT_FILE"] = str(Path(ca_file).absolute())
        if os.name == "nt":
            environment["USERPROFILE"] = str(Path.home().resolve())
        from ..dependency_maintenance import current_capability, state_root

        environment["QWENPAW_DEPENDENCY_STATE_DIR"] = str(state_root())
        capability = current_capability()
        if capability:
            environment["QWENPAW_DEPENDENCY_MAINTENANCE"] = capability
        options: dict[str, Any] = (
            {"start_new_session": True} if os.name != "nt" else {}
        )
        logs = WorkerLogs(spec, self._mode)
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                spec.python_executable,
                "-I",
                "-B",
                str(worker),
                str(os.getpid()),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                cwd=str(spec.code_root),
                **options,
            ),
        )
        self._spawn_task = spawn
        self._spawn_error = None
        spawn.add_done_callback(lambda task: self._spawn_done(task, logs))
        await asyncio.shield(spawn)
        if self._spawn_error is not None:
            raise self.error_type(self._spawn_error)
        process = self._process
        assert process is not None
        assert process.stdout is not None and process.stdin is not None
        self._peer = self._make_peer(
            FramedTransport(
                process.stdout,
                process.stdin,
                payloads=self._payloads,
            ),
        )
        self._peer.register_method(self.hello_method, self._hello)
        self._peer.register_method("execution.dependencies", self._evidence)
        for name in (
            self.control_prefix + suffix
            for suffix in ("ready", "inspected", "state", "error")
        ):
            self._peer.register_notification(name, self._control)
        if self._mode != "manage":
            for name, handler in self._methods.items():
                self._peer.register_method(name, handler)
            for name, handler in self._notifications.items():
                self._peer.register_notification(name, handler)
        # The host Job owns the child before releasing any private launch data.
        process.stdin.write(packet)
        await process.stdin.drain()
        await self._peer.start()
        closed = asyncio.create_task(self._peer.wait_closed())
        self._closed_task = closed
        try:
            await asyncio.wait(
                (self._ready, closed),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self._ready.done():
                self._ready.result()
            else:
                raise self.error_type("WORKER_EXITED")
        finally:
            if self._ready.done() and not self._ready.cancelled():
                self._ready.exception()

    def _spawn_done(self, task: asyncio.Task[Any], logs: WorkerLogs) -> None:
        """Take ownership even if cancellation beat subprocess creation."""
        try:
            self._process = task.result()
            assert self._process is not None
            self._log_task = asyncio.create_task(
                self._drain_logs(self._process, logs),
            )
            self._tree = ProcessTree(self._process.pid)
        except (asyncio.CancelledError, Exception):
            self._spawn_error = "PROCESS_TREE_UNAVAILABLE"
        if (
            self._state == "residual"
            and self._spec is not None
            and (self._cleanup_task is None or self._cleanup_task.done())
        ):
            self._cleanup_task = asyncio.create_task(
                self._cleanup_owned(
                    self._spec.shutdown_timeout,
                    graceful=False,
                ),
            )

    async def _hello(self, hello: Any, _request: Any) -> dict[str, bool]:
        assert self._spec is not None
        validate_hello(
            hello,
            self._spec,
            expected_requirements=self._spec.requirements,
        )
        self.observed_hello = dict(hello)
        return {"accepted": True}

    async def _control(self, params: Any, notification: Any) -> None:
        assert self._spec is not None
        try:
            expected = self._identity(self._spec).to_mapping()
            received = self.identity_type.from_mapping(
                {name: params.get(name) for name in expected},
            )
            if received.to_mapping() != expected:
                return
        except (ValueError, AttributeError):
            return
        ready = "ready" if self._mode in {"run", "manage"} else "inspected"
        if notification.method == self.control_prefix + ready:
            if self._ready is not None and not self._ready.done():
                if self.dependency_snapshot is None:
                    self._ready.set_exception(
                        self.error_type("DEPENDENCY_METADATA_INVALID"),
                    )
                    return
                if self._mode == "run":
                    self._platform = self.connecting_state
                self._ready.set_result(None)
        elif (
            self._mode != "manage"
            and notification.method == self.control_prefix + "state"
        ):
            state = params.get(self.state_key)
            if state in self.component_states:
                self._platform = state
                if state == "failed":
                    self._last_error = self.failed_reason
        elif self._ready is not None and not self._ready.done():
            reason = params.get("reason_code")
            self._ready.set_exception(
                self.error_type(
                    (
                        reason
                        if reason in self.startup_errors
                        else "WORKER_START_FAILED"
                    ),
                ),
            )

    async def _drain_logs(
        self,
        process: asyncio.subprocess.Process,
        logs: WorkerLogs | None,
    ) -> None:
        assert process.stderr is not None
        while True:
            chunk = await process.stderr.read(16384)
            if not chunk:
                if logs is not None:
                    try:
                        await logs.finish()
                    except Exception:
                        pass
                return
            self._log_bytes += len(chunk)
            if logs is not None:
                try:
                    logs.feed(chunk)
                except Exception:
                    # Forwarding is optional; always keep draining the pipe.
                    logs = None
            # StreamReader.read() may complete synchronously while buffered.
            # Bound uninterrupted parsing/draining work to one 16 KiB chunk.
            await asyncio.sleep(0)

    async def call(
        self,
        method: str,
        params: Any = None,
        *,
        timeout: float = 5.0,
    ) -> Any:
        """Forward once and retain uncertain outcomes without payloads."""
        if self._state != "ready" or self._peer is None:
            raise self.error_type("NOT_READY")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self._counter += 1
        generation = self._generation
        request_id = f"{self.request_prefix}-{generation}-{self._counter}"
        try:
            return await asyncio.wait_for(
                self._peer.call(
                    method,
                    params,
                    timeout=timeout,
                    request_id=request_id,
                ),
                timeout,
            )
        except RpcCallNotSent:
            raise self.error_type("NOT_READY") from None
        except (
            asyncio.TimeoutError,
            RpcTimeoutError,
            RpcClosedError,
            asyncio.CancelledError,
            FrameError,
        ) as exc:
            if isinstance(exc, FrameError) and not getattr(
                exc,
                "side_effect_possible",
                False,
            ):
                raise
            unknown = self.unknown_type(request_id, method, generation)
            self._unknown.append(
                {
                    "request_id": request_id,
                    "method": method,
                    "generation": generation,
                    "reason_code": unknown.reason_code,
                },
            )
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise unknown from None

    async def stop(self, *, timeout: float | None = None) -> StopResult:
        """Disable restart before waiting, then finish bounded tree cleanup."""
        self._restart_enabled = False
        budget = (
            timeout
            if timeout is not None
            else (self._spec.shutdown_timeout if self._spec else 2.0)
        )
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError("timeout must be positive")
        deadline = asyncio.get_running_loop().time() + budget
        if self._stop_task is None or self._stop_task.done():
            self._stop_task = asyncio.create_task(self._stop(budget))
        elif self._state == "residual":
            self._stop_task = asyncio.create_task(
                self._stop(budget, previous=self._stop_task),
            )
        wait = asyncio.create_task(self._wait_stop(self._stop_task, deadline))
        try:
            return await asyncio.shield(wait)
        except asyncio.CancelledError:
            await _settle(wait)
            raise

    async def _wait_stop(
        self,
        task: asyncio.Task[Any],
        deadline: float,
    ) -> StopResult:
        """Bound the caller's whole wait while retaining late cleanup work."""
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        done, _ = await asyncio.wait({task}, timeout=remaining)
        if done:
            return task.result()
        residual = []
        for owned, reason in (
            (self._spawn_task, "SPAWN_PENDING"),
            (self._start_task, "STARTUP_PENDING"),
            (self._cleanup_task, "CLEANUP_PENDING"),
        ):
            if owned is not None and not owned.done():
                residual.append(reason)
        if self._process is not None and self._process.returncode is None:
            residual.append("PROCESS_RUNNING")
        if self._tree is not None and self._tree.alive():
            residual.append("PROCESS_TREE_RUNNING")
        self._state = "residual"
        return StopResult(
            False,
            self._process.returncode if self._process else self._returncode,
            self._forced,
            tuple(residual) or ("STOP_PENDING",),
        )

    async def _stop(self, budget: float, *, previous=None) -> StopResult:
        if previous is not None:
            deadline = asyncio.get_running_loop().time() + budget
            result = await asyncio.shield(previous)
            budget = deadline - asyncio.get_running_loop().time()
            if result.exited or budget <= 0:
                return result
        self._state = "stopping"
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            try:
                await _settle(self._start_task)
            except (asyncio.CancelledError, Exception):
                pass
        result = await self._cleanup(budget, graceful=True)
        if (
            self._monitor_task is not None
            and self._monitor_task is not asyncio.current_task()
        ):
            self._monitor_task.cancel()
            await asyncio.gather(self._monitor_task, return_exceptions=True)
        if result.exited:
            self._state = "stopped"
        return result

    async def _cleanup(self, budget: float, *, graceful: bool) -> StopResult:
        if self._cleanup_task is None or (
            self._cleanup_task.done()
            and (
                self._process is not None
                or self._spawn_task is not None
                or self._payloads is not None
            )
        ):
            self._cleanup_task = asyncio.create_task(
                self._cleanup_owned(budget, graceful=graceful),
            )
        result = await asyncio.shield(self._cleanup_task)
        self.last_cleanup = result
        return result

    async def _close_peer(self, budget: float, *, graceful: bool) -> bool:
        """Request component shutdown and bound private transport closure."""
        peer = self._peer
        if (
            graceful
            and peer is not None
            and not peer.is_closed
            and self._spec is not None
        ):
            try:
                result = await asyncio.wait_for(
                    peer.call(
                        self.control_prefix + "stop",
                        self._identity(self._spec).to_mapping(),
                        timeout=budget / 3,
                    ),
                    budget / 3,
                )
            except Exception:
                return False
            if (
                not isinstance(result, dict)
                or result.get("stopped") is not True
            ):
                return False
        elif graceful:
            return False
        if peer is not None:
            try:
                await asyncio.wait_for(peer.aclose(), max(0.01, budget / 6))
            except Exception:
                pass
        return True

    async def _cleanup_owned(
        self,
        budget: float,
        *,
        graceful: bool,
    ) -> StopResult:
        if self._spawn_task is not None and not self._spawn_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._spawn_task),
                    budget / 3,
                )
            except asyncio.TimeoutError:
                self._state = "residual"
                return StopResult(False, None, False, ("SPAWN_PENDING",))
            except Exception:
                pass
        process, tree = self._process, self._tree
        if process is None:
            if (
                self._payloads is not None
                and not await self._payloads.cleanup(
                    deadline=asyncio.get_running_loop().time() + budget,
                )
            ):
                self._state = "residual"
                return StopResult(
                    False,
                    self._returncode,
                    False,
                    ("PAYLOAD_STORE_REMAINING",),
                )
            self._payloads = None
            return StopResult(True, self._returncode, False)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget
        confirmed = await self._close_peer(budget, graceful=graceful)
        if graceful and confirmed:
            until = min(deadline, loop.time() + budget / 6)
            while process.returncode is None and loop.time() < until:
                await asyncio.sleep(0.01)
        forced = await self._terminate_tree(process, tree, deadline, budget)
        if graceful and not confirmed:
            await self._close_peer(
                max(0.0, deadline - loop.time()),
                graceful=False,
            )
        residual = []
        if process.returncode is None:
            residual.append("PROCESS_RUNNING")
        if tree is not None and tree.alive():
            residual.append("PROCESS_TREE_RUNNING")
        if (
            not residual
            and self._payloads is not None
            and not await self._payloads.cleanup(deadline=deadline)
        ):
            residual.append("PAYLOAD_STORE_REMAINING")
        self._returncode = process.returncode
        self._platform = self.initial_state
        if residual:
            self._state = "residual"
        else:
            await self._release_tree(tree)
        return StopResult(
            not residual,
            process.returncode,
            forced,
            tuple(residual),
        )

    async def _release_tree(self, tree: ProcessTree | None) -> None:
        """Release transport/log handles only after the entire tree exits."""
        if tree is not None:
            tree.close()
        self._process, self._tree, self._peer = None, None, None
        self._payloads = None
        self._spawn_task = None
        if self._log_task is not None:
            try:
                await asyncio.wait_for(self._log_task, 0.1)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._log_task.cancel()
        if self._state == "residual":
            self._state = "stopped"

    async def _terminate_tree(
        self,
        process: asyncio.subprocess.Process,
        tree: ProcessTree | None,
        deadline: float,
        budget: float,
    ) -> bool:
        """Escalate against the owned group/job within the cleanup budget."""
        loop = asyncio.get_running_loop()
        forced = False
        for force in (False, True):
            if process.returncode is not None and (
                tree is None or not tree.alive()
            ):
                break
            forced = True
            self._forced = True
            try:
                if tree is not None:
                    tree.signal(force=force)
                elif process.returncode is None:
                    if force:
                        process.kill()
                    else:
                        process.terminate()
            except OSError:
                pass
            until = (
                deadline if force else min(deadline, loop.time() + budget / 3)
            )
            while loop.time() < until:
                if process.returncode is not None and (
                    tree is None or not tree.alive()
                ):
                    break
                await asyncio.sleep(min(0.02, max(0, until - loop.time())))
        return forced

    async def _monitor(self) -> None:
        while self._peer is not None:
            assert self._closed_task is not None
            await asyncio.shield(self._closed_task)
            if self._state == "ready":
                self._state = "stopping"
            assert self._spec is not None
            spec = self._spec
            result = await self._cleanup(spec.shutdown_timeout, graceful=False)
            if not result.exited:
                return
            if (
                not self._restart_enabled
                or self._restart_count >= spec.restart_limit
            ):
                if self._restart_enabled:
                    self._state, self._last_error = "failed", "WORKER_EXITED"
                return
            self._state = "backoff"
            delay = min(
                5.0,
                spec.restart_backoff * 2 ** min(self._restart_count, 16),
            )
            await asyncio.sleep(delay)
            if not self._restart_enabled:
                return
            self._restart_count += 1
            self._generation += 1
            self._spec = replace(spec, generation=self._generation)
            self._start_task = asyncio.create_task(self._launch(self._spec))
            try:
                await asyncio.shield(self._start_task)
            except self.error_type:
                return
