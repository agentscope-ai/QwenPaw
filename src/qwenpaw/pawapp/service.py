# -*- coding: utf-8 -*-
"""Managed sidecar services for PawApps.

The public SDK owns process startup, health checking, and shutdown so an app
does not need to reach into QwenPaw's plugin runtime or hard-code a port.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import shutil
import socket
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class ManagedServiceUnavailable(RuntimeError):
    """An expected environment failure, with a browser-safe explanation."""

    def __init__(self, code: str, message: str, diagnostic: str = ""):
        super().__init__(diagnostic or message)
        self.code = code
        self.message = message


class ManagedServiceHealthTimeout(ManagedServiceUnavailable, TimeoutError):
    """Preserve the public timeout contract for readiness failures."""


class ManagedServiceConfigurationError(ManagedServiceUnavailable, ValueError):
    """Preserve URL validation errors while identifying environment issues."""


class ManagedServiceNotReady(HTTPException, RuntimeError):
    """Expose known dependency failures to legacy HTTP and runtime callers."""

    def __init__(self, name: str, error: ManagedServiceUnavailable):
        HTTPException.__init__(
            self,
            status_code=503,
            detail={
                "code": error.code,
                "message": error.message,
                "dependency_id": name,
            },
        )


def _validate_loopback_host(host: str) -> None:
    if host.lower() == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(
            "managed service host must be a loopback address",
        ) from exc
    if not address.is_loopback:
        raise ValueError("managed service host must be a loopback address")


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _replace_placeholders(value: str, *, host: str, port: int) -> str:
    """Replace only SDK-owned placeholders and preserve arbitrary braces."""
    return value.replace("{host}", host).replace("{port}", str(port))


def _normalize_external_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        # Accessing port also validates malformed port syntax.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("managed service external URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("managed service external URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ValueError(
            "managed service external URL cannot contain credentials",
        )
    if parsed.query or parsed.fragment:
        raise ValueError(
            "managed service external URL cannot contain a query or fragment",
        )
    return value.rstrip("/")


def _available_loopback_port(host: str) -> int:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


# Managed services live on loopback endpoints by contract, so health
# probes must never traverse a proxy. A plain urlopen() consults the
# environment and, on macOS, the system proxy configuration (scproxy),
# which can silently redirect 127.0.0.1 requests on managed machines
# and CI runners.
_DIRECT_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
)


def _health_request(url: str, timeout: float) -> bool:
    try:
        request = urllib.request.Request(  # noqa: S310 - URL is app-owned
            url,
            headers={"Accept": "application/json"},
        )
        with _DIRECT_OPENER.open(
            request,
            timeout=timeout,
        ) as response:  # noqa: S310
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, ValueError):
        return False


@dataclass(frozen=True)
class ManagedServiceSpec:
    """Declarative sidecar process configuration."""

    name: str
    command: Sequence[str]
    health_path: str = "/health"
    host: str = "127.0.0.1"
    startup_timeout: float = 30.0
    shutdown_timeout: float = 10.0
    cwd: Path | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    external_url_env: str | None = None
    mode_env: str | None = None
    on_before_start: Optional[Callable[[], Awaitable[None]]] = None


class ManagedService:
    """Runtime handle returned by :meth:`PawApp.managed_service`."""

    def __init__(self, spec: ManagedServiceSpec):
        if (
            not spec.name
            or not spec.command
            or isinstance(spec.command, (str, bytes))
        ):
            raise ValueError("managed service requires a name and command")
        if not spec.health_path.startswith("/"):
            raise ValueError("managed service health_path must start with '/'")
        _validate_loopback_host(spec.host)
        self.spec = spec
        self._process: asyncio.subprocess.Process | None = None
        self._base_url: str | None = None
        self._log_tasks: list[asyncio.Task] = []
        self._recent_logs: deque[str] = deque(maxlen=30)
        self._external = False
        self.startup_error: ManagedServiceUnavailable | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def base_url(self) -> str:
        if self._base_url is None:
            if self.startup_error is not None:
                raise ManagedServiceNotReady(
                    self.spec.name,
                    self.startup_error,
                )
            raise RuntimeError(
                f"managed service '{self.spec.name}' is not ready",
            )
        return self._base_url

    @property
    def is_ready(self) -> bool:
        return self._base_url is not None

    @property
    def is_external(self) -> bool:
        return self._external

    def _external_configured(self) -> bool:
        """Return whether the environment selects an external endpoint."""
        if self._external:
            return True
        if self.spec.mode_env:
            mode = os.getenv(self.spec.mode_env, "").strip().lower()
            if mode == "external":
                return True
        if self.spec.external_url_env:
            return bool(os.getenv(self.spec.external_url_env, "").strip())
        return False

    def runtime_available(self) -> bool:
        """Return whether a managed start could locate its executable.

        External mode never spawns a process, so it is always considered
        available; otherwise the command's executable must exist as a file
        or resolve on PATH.
        """
        if self._external_configured():
            return True
        executable = self.spec.command[0]
        return (
            Path(executable).is_file() or shutil.which(executable) is not None
        )

    def status(self) -> dict[str, object]:
        """Return browser-safe lifecycle state without endpoint details."""
        return {
            "name": self.spec.name,
            "ready": self.is_ready,
            "mode": "external" if self._external else "managed",
        }

    def diagnostics(self) -> dict[str, object]:
        """Return explicit backend-only details for logging and diagnostics."""
        return {
            **self.status(),
            "url": self._base_url,
            "pid": self._process.pid if self._process else None,
            "recent_logs": list(self._recent_logs),
        }

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("managed service has been closed")
        if self._start_task is None or self._start_task.done():
            self._start_task = asyncio.create_task(self._start())
            self._start_task.add_done_callback(self._observe_start)
        task = self._start_task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            raise
        except ManagedServiceUnavailable as exc:
            self.startup_error = exc
            raise
        self.startup_error = None

    @staticmethod
    def _observe_start(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _start(self) -> None:
        if self.is_ready:
            return

        if self.spec.on_before_start is not None:
            await self.spec.on_before_start()

        mode = (
            os.getenv(self.spec.mode_env, "managed").strip().lower()
            if self.spec.mode_env
            else "managed"
        )
        if mode not in {"managed", "external"}:
            raise ManagedServiceUnavailable(
                "SERVICE_CONFIGURATION_INVALID",
                "Service mode must be 'managed' or 'external'",
                f"{self.spec.mode_env} must be 'managed' or 'external'",
            )

        external_url = (
            os.getenv(self.spec.external_url_env, "").strip()
            if self.spec.external_url_env
            else ""
        )
        if mode == "external" or external_url:
            if not external_url:
                raise ManagedServiceUnavailable(
                    "SERVICE_CONFIGURATION_INVALID",
                    "External service URL is not configured",
                    "external service mode requires "
                    f"{self.spec.external_url_env}",
                )
            try:
                normalized_external_url = _normalize_external_url(external_url)
            except ValueError as exc:
                raise ManagedServiceConfigurationError(
                    "SERVICE_CONFIGURATION_INVALID",
                    str(exc),
                ) from exc
            self._external = True
            self._base_url = normalized_external_url
            try:
                await self._wait_until_healthy()
            except BaseException:
                await self.stop()
                raise
            logger.info(
                "PawApp service '%s' attached to external endpoint",
                self.spec.name,
            )
            return

        port = _available_loopback_port(self.spec.host)
        command = [
            _replace_placeholders(part, host=self.spec.host, port=port)
            for part in self.spec.command
        ]
        if not (
            Path(command[0]).is_file() or shutil.which(command[0]) is not None
        ):
            # Fail with an actionable message instead of the cryptic
            # FileNotFoundError a doomed spawn would raise.
            hint = (
                f" or set {self.spec.mode_env}=external with "
                f"{self.spec.external_url_env}"
                if self.spec.mode_env and self.spec.external_url_env
                else ""
            )
            raise ManagedServiceUnavailable(
                "RUNTIME_MISSING",
                "Service runtime is not provisioned",
                f"managed service '{self.spec.name}' executable does not "
                f"exist: {command[0]}. Provision the service runtime{hint}",
            )
        environment = os.environ.copy()
        environment.update(
            {
                key: _replace_placeholders(
                    value,
                    host=self.spec.host,
                    port=port,
                )
                for key, value in self.spec.env.items()
            },
        )
        self._base_url = f"http://{_url_host(self.spec.host)}:{port}"
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(self.spec.cwd) if self.spec.cwd else None,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            self._base_url = None
            raise ManagedServiceUnavailable(
                "SERVICE_START_FAILED",
                "Service process could not be started; check its runtime",
            ) from exc
        except BaseException:
            self._base_url = None
            raise

        self._log_tasks = [
            asyncio.create_task(self._drain(self._process.stdout, "stdout")),
            asyncio.create_task(self._drain(self._process.stderr, "stderr")),
        ]
        try:
            await self._wait_until_healthy()
        except BaseException:
            await self.stop()
            details = "\n".join(self._recent_logs)
            if details:
                logger.error(
                    "PawApp service '%s' startup output:\n%s",
                    self.spec.name,
                    details,
                )
            raise
        logger.info(
            "PawApp service '%s' ready on a managed loopback endpoint",
            self.spec.name,
        )

    async def stop(self) -> None:
        task = self._start_task
        if task is not None and task is not asyncio.current_task():
            if not task.done() and not task.cancelling():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        process = self._process
        self._base_url = None
        self._external = False
        if process and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=self.spec.shutdown_timeout,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                # An outer close budget must not restart this grace period.
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
                if isinstance(exc, asyncio.CancelledError):
                    raise
        self._process = None
        for task in self._log_tasks:
            task.cancel()
        if self._log_tasks:
            await asyncio.gather(*self._log_tasks, return_exceptions=True)
        self._log_tasks.clear()

    async def aclose(self) -> None:
        """Final hosted cleanup also prevents later dependency starts."""
        self._closed = True
        await self.stop()

    def reopen(self) -> None:
        """Allow a new plugin generation only after hosted cleanup finished."""
        if not self._closed:
            return
        if (self._start_task is not None and not self._start_task.done()) or (
            self._process is not None and self._process.returncode is None
        ):
            raise RuntimeError("previous managed service has not stopped")
        self._closed = False

    async def restart(self) -> None:
        """Restart the managed process with the existing safe spec."""
        await self.stop()
        await self.start()

    async def check_health(self) -> bool:
        """Run the configured readiness check without exposing its endpoint."""
        if not self.is_ready:
            return False
        return await asyncio.to_thread(
            _health_request,
            f"{self.base_url}{self.spec.health_path}",
            1.0,
        )

    async def _wait_until_healthy(self) -> None:
        deadline = (
            asyncio.get_running_loop().time() + self.spec.startup_timeout
        )
        health_url = f"{self.base_url}{self.spec.health_path}"
        while asyncio.get_running_loop().time() < deadline:
            if self._process and self._process.returncode is not None:
                raise ManagedServiceUnavailable(
                    "SERVICE_EXITED",
                    "Service process exited before becoming ready",
                    f"managed service '{self.spec.name}' exited with "
                    f"code {self._process.returncode}",
                )
            if await asyncio.to_thread(_health_request, health_url, 1.0):
                return
            await asyncio.sleep(0.15)
        details = "\n".join(self._recent_logs)
        raise ManagedServiceHealthTimeout(
            "SERVICE_HEALTH_TIMEOUT",
            "Service did not become healthy within its startup timeout",
            f"managed service '{self.spec.name}' did not become healthy "
            f"within {self.spec.startup_timeout:g}s"
            + (f"; recent output:\n{details}" if details else ""),
        )

    async def _drain(
        self,
        stream: asyncio.StreamReader | None,
        channel: str,
    ) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            self._recent_logs.append(f"{channel}: {text}")
            logger.debug("[%s:%s] %s", self.spec.name, channel, text)
