# -*- coding: utf-8 -*-
"""App-scoped dependency health and lifecycle control for PawApps.

The SDK defines the contract and execution rules only. Runtime-specific
operations (Docker, systemd, cloud APIs, and so on) remain app-owned callback
implementations.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Sequence

from fastapi import APIRouter, Header, HTTPException

logger = logging.getLogger(__name__)

_DEPENDENCY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
_OWNERSHIP_VALUES = {"host_managed", "app_managed", "external"}
_HEALTH_VALUES = {"unknown", "checking", "healthy", "degraded", "unavailable"}
_LIFECYCLE_VALUES = {
    "unknown",
    "not_installed",
    "stopped",
    "starting",
    "running",
    "stopping",
    "failed",
    "unmanaged",
}
_MUTATING_ACTIONS = {"start", "stop", "restart", "provision"}

DependencyCallback = Callable[[], Any | Awaitable[Any]]


@dataclass(frozen=True)
class DependencyHealth:
    """Sanitized result returned by an app-owned dependency probe."""

    health: str
    lifecycle: str = "unknown"
    message: str = ""
    error_code: str | None = None
    remediation: str | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if self.health not in _HEALTH_VALUES:
            raise ValueError(f"unsupported dependency health: {self.health}")
        if self.lifecycle not in _LIFECYCLE_VALUES:
            raise ValueError(
                f"unsupported dependency lifecycle: {self.lifecycle}",
            )
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("dependency latency_ms cannot be negative")


@dataclass(frozen=True)
class DependencyProbe:
    """Deterministic dependency check with bounded execution and caching."""

    callback: DependencyCallback
    timeout_seconds: float = 3.0
    cache_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not callable(self.callback):
            raise ValueError("dependency probe callback must be callable")
        if self.timeout_seconds <= 0:
            raise ValueError(
                "dependency probe timeout_seconds must be positive",
            )
        if self.cache_seconds < 0:
            raise ValueError(
                "dependency probe cache_seconds cannot be negative",
            )


@dataclass(frozen=True)
class DependencyLifecycle:
    """Optional, typed lifecycle operations supplied by a trusted app."""

    start: DependencyCallback | None = None
    stop: DependencyCallback | None = None
    restart: DependencyCallback | None = None
    provision: DependencyCallback | None = None
    action_timeout_seconds: float = 30.0
    readiness_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        callbacks = (self.start, self.stop, self.restart, self.provision)
        if any(
            callback is not None and not callable(callback)
            for callback in callbacks
        ):
            raise ValueError("dependency lifecycle callbacks must be callable")
        if self.action_timeout_seconds <= 0:
            raise ValueError(
                "dependency action timeout_seconds must be positive",
            )
        if self.readiness_timeout_seconds <= 0:
            raise ValueError(
                "dependency readiness timeout_seconds must be positive",
            )


@dataclass(frozen=True)
class DependencySpec:
    """Static dependency declaration registered by a PawApp."""

    dependency_id: str
    display_name: str
    ownership: str
    capabilities: tuple[str, ...]
    required: bool
    probe: DependencyProbe
    lifecycle: DependencyLifecycle | None = None


class DependencyError(RuntimeError):
    """Typed dependency error safe to return through HTTP or agent tools."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        dependency_id: str = "",
        action: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.dependency_id = dependency_id
        self.action = action

    def detail(self) -> dict[str, str]:
        result = {"code": self.code, "message": self.message}
        if self.dependency_id:
            result["dependency_id"] = self.dependency_id
        if self.action:
            result["action"] = self.action
        return result


@dataclass
class _CachedHealth:
    health: DependencyHealth
    checked_at: datetime
    expires_at: float


class DependencyRegistry:
    """Per-app dependency registry and control-plane executor."""

    def __init__(self, app_id: str | Callable[[], str]):
        self._app_id = app_id if callable(app_id) else lambda: app_id
        self._specs: dict[str, DependencySpec] = {}
        self._cache: dict[str, _CachedHealth] = {}
        self._probe_locks: dict[str, asyncio.Lock] = {}
        self._action_locks: dict[str, asyncio.Lock] = {}
        self._transitions: dict[str, str] = {}
        self._idempotency: dict[
            tuple[str, str, str],
            tuple[float, dict[str, Any]],
        ] = {}

    def __len__(self) -> int:
        return len(self._specs)

    def register(
        self,
        dependency_id: str,
        *,
        display_name: str | None = None,
        ownership: str = "external",
        capabilities: Sequence[str] = (),
        required: bool = True,
        probe: DependencyProbe,
        lifecycle: DependencyLifecycle | None = None,
        replace: bool = False,
    ) -> DependencySpec:
        normalized_id = dependency_id.strip()
        if not _DEPENDENCY_ID_PATTERN.fullmatch(normalized_id):
            raise ValueError(
                "dependency id must use lowercase letters, numbers, '.', ':', "
                "'_', or '-'",
            )
        if normalized_id in self._specs and not replace:
            raise ValueError(f"dependency already registered: {normalized_id}")
        if ownership not in _OWNERSHIP_VALUES:
            raise ValueError(f"unsupported dependency ownership: {ownership}")
        if ownership == "external" and lifecycle is not None:
            raise ValueError(
                "external dependencies cannot declare lifecycle actions",
            )
        normalized_capabilities = tuple(dict.fromkeys(capabilities))
        if any(
            not item or not isinstance(item, str)
            for item in normalized_capabilities
        ):
            raise ValueError(
                "dependency capabilities must be non-empty strings",
            )
        spec = DependencySpec(
            dependency_id=normalized_id,
            display_name=(display_name or normalized_id).strip(),
            ownership=ownership,
            capabilities=normalized_capabilities,
            required=required,
            probe=probe,
            lifecycle=lifecycle,
        )
        self._specs[normalized_id] = spec
        # Keep any existing locks so an in-flight probe or action for a
        # replaced dependency still serializes with the new registration.
        self._probe_locks.setdefault(normalized_id, asyncio.Lock())
        self._action_locks.setdefault(normalized_id, asyncio.Lock())
        # Drop stale health so the next check runs the new probe.
        self._cache.pop(normalized_id, None)
        return spec

    def unregister(self, dependency_id: str) -> bool:
        """Remove one dependency so catalogs can shrink at runtime.

        Returns whether the dependency was registered. In-flight probes or
        actions finish on their own references; later calls surface
        ``DEPENDENCY_NOT_FOUND``.
        """
        normalized_id = dependency_id.strip()
        if self._specs.pop(normalized_id, None) is None:
            return False
        self._cache.pop(normalized_id, None)
        self._transitions.pop(normalized_id, None)
        self._probe_locks.pop(normalized_id, None)
        self._action_locks.pop(normalized_id, None)
        for key in [
            item for item in self._idempotency if item[0] == normalized_id
        ]:
            self._idempotency.pop(key, None)
        return True

    def ids(self, *, prefix: str = "") -> list[str]:
        """Return registered dependency ids, optionally filtered by prefix."""
        return [
            dependency_id
            for dependency_id in self._specs
            if dependency_id.startswith(prefix)
        ]

    @staticmethod
    def _reraise_unexpected(error: BaseException) -> None:
        """Swallow races with ``unregister``; anything else propagates."""
        if (
            isinstance(error, DependencyError)
            and error.code == "DEPENDENCY_NOT_FOUND"
        ):
            return
        raise error

    async def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        results = await asyncio.gather(
            *(
                self.get(dependency_id, force=force)
                for dependency_id in list(self._specs)
            ),
            return_exceptions=True,
        )
        # A dependency unregistered while the gather ran simply drops out of
        # the snapshot instead of failing the whole control plane.
        statuses: list[dict[str, Any]] = []
        for status in results:
            if isinstance(status, BaseException):
                self._reraise_unexpected(status)
                continue
            statuses.append(status)
        return {
            "schema_version": "1",
            "app_id": self._app_id(),
            "summary": self._summarize(statuses),
            "dependencies": statuses,
            "capabilities": self._capability_statuses(statuses),
        }

    async def capabilities(self, *, force: bool = False) -> dict[str, Any]:
        snapshot = await self.snapshot(force=force)
        return {
            "schema_version": snapshot["schema_version"],
            "app_id": snapshot["app_id"],
            "summary": snapshot["summary"],
            "capabilities": snapshot["capabilities"],
        }

    async def get(
        self,
        dependency_id: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        spec = self._require(dependency_id)
        cached = self._cache.get(spec.dependency_id)
        if not force and cached and cached.expires_at > time.monotonic():
            return self._public_status(spec, cached)

        async with self._probe_locks[spec.dependency_id]:
            cached = self._cache.get(spec.dependency_id)
            if not force and cached and cached.expires_at > time.monotonic():
                return self._public_status(spec, cached)
            checked_at = datetime.now(timezone.utc)
            started = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self._invoke(spec.probe.callback),
                    timeout=spec.probe.timeout_seconds,
                )
                if not isinstance(result, DependencyHealth):
                    raise TypeError("probe must return DependencyHealth")
                if result.latency_ms is None:
                    result = DependencyHealth(
                        health=result.health,
                        lifecycle=result.lifecycle,
                        message=result.message,
                        error_code=result.error_code,
                        remediation=result.remediation,
                        latency_ms=round((time.monotonic() - started) * 1000),
                    )
            except asyncio.TimeoutError:
                result = DependencyHealth(
                    health="unavailable",
                    lifecycle=self._fallback_lifecycle(spec),
                    error_code="PROBE_TIMEOUT",
                    message="Dependency health check timed out",
                    remediation="Retry the check or inspect the service owner",
                    latency_ms=round((time.monotonic() - started) * 1000),
                )
            except (ConnectionError, OSError):
                result = DependencyHealth(
                    health="unavailable",
                    lifecycle=self._fallback_lifecycle(spec),
                    error_code="CONNECTION_REFUSED",
                    message="Dependency is not accepting connections",
                    remediation=(
                        "Start the configured service or contact its owner"
                    ),
                    latency_ms=round((time.monotonic() - started) * 1000),
                )
            except Exception:  # noqa: BLE001 - redact app/driver failures
                logger.exception(
                    "Dependency probe failed for %s/%s",
                    self._app_id(),
                    spec.dependency_id,
                )
                result = DependencyHealth(
                    health="unavailable",
                    lifecycle=self._fallback_lifecycle(spec),
                    error_code="PROBE_FAILED",
                    message="Dependency health check failed",
                    remediation=(
                        "Inspect backend diagnostics and retry the check"
                    ),
                    latency_ms=round((time.monotonic() - started) * 1000),
                )

            cached = _CachedHealth(
                health=result,
                checked_at=checked_at,
                expires_at=time.monotonic() + spec.probe.cache_seconds,
            )
            self._cache[spec.dependency_id] = cached
            return self._public_status(spec, cached)

    async def action(  # pylint: disable=R0912
        self,
        dependency_id: str,
        action: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        spec = self._require(dependency_id)
        normalized_action = action.strip().lower()
        if normalized_action == "check":
            return await self.get(spec.dependency_id, force=True)
        if normalized_action not in _MUTATING_ACTIONS:
            raise DependencyError(
                "ACTION_NOT_ALLOWED",
                f"Unsupported dependency action: {normalized_action}",
                dependency_id=spec.dependency_id,
                action=normalized_action,
            )
        callback = (
            getattr(spec.lifecycle, normalized_action, None)
            if spec.lifecycle is not None
            else None
        )
        if callback is None:
            raise DependencyError(
                "NOT_MANAGED"
                if spec.ownership == "external"
                else "ACTION_NOT_ALLOWED",
                f"Action '{normalized_action}' is not available "
                f"for this dependency",
                dependency_id=spec.dependency_id,
                action=normalized_action,
            )

        cache_key = (
            spec.dependency_id,
            normalized_action,
            idempotency_key or "",
        )
        if idempotency_key:
            if len(idempotency_key) > 128:
                raise DependencyError(
                    "INVALID_IDEMPOTENCY_KEY",
                    "Idempotency-Key cannot exceed 128 characters",
                    dependency_id=spec.dependency_id,
                    action=normalized_action,
                )
            now = time.monotonic()
            self._idempotency = {
                key: value
                for key, value in self._idempotency.items()
                if value[0] > now
            }
            cached_action = self._idempotency.get(cache_key)
            if cached_action and cached_action[0] > time.monotonic():
                return cached_action[1]

        lock = self._action_locks[spec.dependency_id]
        async with lock:
            if idempotency_key:
                cached_action = self._idempotency.get(cache_key)
                if cached_action and cached_action[0] > time.monotonic():
                    return cached_action[1]
            transition = (
                "stopping" if normalized_action == "stop" else "starting"
            )
            self._transitions[spec.dependency_id] = transition
            try:
                await asyncio.wait_for(
                    self._invoke(callback),
                    timeout=spec.lifecycle.action_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise DependencyError(
                    "ACTION_TIMEOUT",
                    f"Dependency action '{normalized_action}' timed out",
                    status_code=504,
                    dependency_id=spec.dependency_id,
                    action=normalized_action,
                ) from exc
            except Exception as exc:  # noqa: BLE001 - expose stable error only
                logger.exception(
                    "Dependency action failed for %s/%s: %s",
                    self._app_id(),
                    spec.dependency_id,
                    normalized_action,
                )
                raise DependencyError(
                    "START_FAILED"
                    if normalized_action in {"start", "restart"}
                    else "ACTION_FAILED",
                    f"Dependency action '{normalized_action}' failed",
                    status_code=502,
                    dependency_id=spec.dependency_id,
                    action=normalized_action,
                ) from exc
            finally:
                self._transitions.pop(spec.dependency_id, None)

            if normalized_action in {"start", "restart", "provision"}:
                result = await self._wait_until_ready(spec)
            else:
                result = await self.get(spec.dependency_id, force=True)
            if idempotency_key:
                self._idempotency[cache_key] = (time.monotonic() + 300, result)
            logger.info(
                "Dependency action completed for %s/%s: %s",
                self._app_id(),
                spec.dependency_id,
                normalized_action,
            )
            return result

    def router(self) -> APIRouter:
        """Build app-scoped dependency and capability routes."""
        router = APIRouter()

        @router.get("/dependencies")
        async def list_dependencies(force: bool = False):
            return await self.snapshot(force=force)

        @router.get("/capabilities")
        async def list_capabilities(force: bool = False):
            return await self.capabilities(force=force)

        @router.get("/dependencies/{dependency_id}")
        async def get_dependency(dependency_id: str, force: bool = False):
            try:
                return await self.get(dependency_id, force=force)
            except DependencyError as exc:
                raise HTTPException(
                    exc.status_code,
                    detail=exc.detail(),
                ) from exc

        @router.post("/dependencies/{dependency_id}/actions/{action}")
        async def run_action(
            dependency_id: str,
            action: str,
            idempotency_key: str | None = Header(default=None),
        ):
            try:
                return await self.action(
                    dependency_id,
                    action,
                    idempotency_key=idempotency_key,
                )
            except DependencyError as exc:
                raise HTTPException(
                    exc.status_code,
                    detail=exc.detail(),
                ) from exc

        return router

    async def _wait_until_ready(self, spec: DependencySpec) -> dict[str, Any]:
        assert spec.lifecycle is not None
        deadline = time.monotonic() + spec.lifecycle.readiness_timeout_seconds
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            last = await self.get(spec.dependency_id, force=True)
            if last["health"] in {"healthy", "degraded"}:
                return last
            await asyncio.sleep(0.25)
        raise DependencyError(
            "READINESS_TIMEOUT",
            "Dependency did not become ready after the lifecycle action",
            status_code=504,
            dependency_id=spec.dependency_id,
            action="start",
        )

    def _require(self, dependency_id: str) -> DependencySpec:
        spec = self._specs.get(dependency_id)
        if spec is None:
            raise DependencyError(
                "DEPENDENCY_NOT_FOUND",
                f"Unknown dependency: {dependency_id}",
                status_code=404,
                dependency_id=dependency_id,
            )
        return spec

    @staticmethod
    async def _invoke(callback: DependencyCallback) -> Any:
        if inspect.iscoroutinefunction(callback):
            return await callback()
        result = await asyncio.to_thread(callback)
        if inspect.isawaitable(result):
            return await result
        return result

    def _public_status(
        self,
        spec: DependencySpec,
        cached: _CachedHealth,
    ) -> dict[str, Any]:
        health = cached.health
        return {
            "id": spec.dependency_id,
            "display_name": spec.display_name,
            "ownership": spec.ownership,
            "required": spec.required,
            "lifecycle": self._transitions.get(
                spec.dependency_id,
                health.lifecycle,
            ),
            "health": health.health,
            "error_code": health.error_code,
            "message": health.message,
            "remediation": health.remediation,
            "capabilities": list(spec.capabilities),
            "actions": self._actions(spec),
            "last_checked_at": cached.checked_at.isoformat(),
            "latency_ms": health.latency_ms,
        }

    @staticmethod
    def _actions(spec: DependencySpec) -> list[str]:
        actions = ["check"]
        if spec.lifecycle is not None:
            actions.extend(
                action
                for action in ("start", "stop", "restart", "provision")
                if getattr(spec.lifecycle, action) is not None
            )
        return actions

    @staticmethod
    def _fallback_lifecycle(spec: DependencySpec) -> str:
        return "unmanaged" if spec.ownership == "external" else "unknown"

    @staticmethod
    def _summarize(statuses: Sequence[Mapping[str, Any]]) -> str:
        if not statuses:
            return "unknown"
        if any(
            item["required"] and item["health"] == "unavailable"
            for item in statuses
        ):
            return "unavailable"
        if any(
            item["health"] in {"unavailable", "degraded"} for item in statuses
        ):
            return "degraded"
        if any(item["health"] in {"unknown", "checking"} for item in statuses):
            return "unknown"
        return "healthy"

    @staticmethod
    def _capability_statuses(
        statuses: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for status in statuses:
            for capability in status["capabilities"]:
                grouped.setdefault(capability, []).append(status)
        return [
            {
                "id": capability,
                "health": DependencyRegistry._summarize(items),
                "dependencies": [item["id"] for item in items],
            }
            for capability, items in grouped.items()
        ]
