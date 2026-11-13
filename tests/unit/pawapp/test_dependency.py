# -*- coding: utf-8 -*-
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from qwenpaw.pawapp import (
    DependencyError,
    DependencyHealth,
    DependencyLifecycle,
    DependencyProbe,
    DependencyRegistry,
)


@pytest.mark.asyncio
async def test_dependency_snapshot_caches_and_aggregates_capabilities():
    probe = AsyncMock(
        return_value=DependencyHealth(
            health="healthy",
            lifecycle="unmanaged",
            message="Ready",
        ),
    )
    registry = DependencyRegistry("fixture")
    registry.register(
        "warehouse",
        display_name="Warehouse",
        ownership="external",
        capabilities=("query",),
        probe=DependencyProbe(probe, cache_seconds=30),
    )

    first = await registry.snapshot()
    second = await registry.snapshot()

    assert probe.await_count == 1
    assert first["summary"] == "healthy"
    assert first["capabilities"] == [
        {
            "id": "query",
            "health": "healthy",
            "dependencies": ["warehouse"],
        },
    ]
    assert second["dependencies"][0]["actions"] == ["check"]


@pytest.mark.asyncio
async def test_dependency_action_waits_for_readiness_and_is_idempotent():
    running = False
    starts = 0

    async def probe() -> DependencyHealth:
        return DependencyHealth(
            health="healthy" if running else "unavailable",
            lifecycle="running" if running else "stopped",
        )

    async def start() -> None:
        nonlocal running, starts
        starts += 1
        running = True

    registry = DependencyRegistry("fixture")
    registry.register(
        "worker",
        ownership="app_managed",
        probe=DependencyProbe(probe, cache_seconds=0),
        lifecycle=DependencyLifecycle(start=start),
    )

    first = await registry.action("worker", "start", idempotency_key="once")
    second = await registry.action("worker", "start", idempotency_key="once")

    assert first["health"] == "healthy"
    assert second == first
    assert starts == 1


@pytest.mark.asyncio
async def test_dependency_probe_errors_are_redacted() -> None:
    async def probe() -> DependencyHealth:
        raise RuntimeError("password=secret")

    registry = DependencyRegistry("fixture")
    registry.register("service", probe=DependencyProbe(probe))

    status = await registry.get("service")

    assert status["error_code"] == "PROBE_FAILED"
    assert "secret" not in status["message"]


def test_external_dependency_cannot_register_lifecycle() -> None:
    registry = DependencyRegistry("fixture")

    with pytest.raises(ValueError, match="external dependencies"):
        registry.register(
            "warehouse",
            ownership="external",
            probe=DependencyProbe(
                lambda: DependencyHealth(health="healthy"),
            ),
            lifecycle=DependencyLifecycle(start=lambda: None),
        )


@pytest.mark.asyncio
async def test_unknown_dependency_returns_typed_error() -> None:
    registry = DependencyRegistry("fixture")

    with pytest.raises(DependencyError) as error:
        await registry.get("missing")

    assert error.value.code == "DEPENDENCY_NOT_FOUND"
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_registry_supports_unregister_and_replace() -> None:
    probe = AsyncMock(
        return_value=DependencyHealth(
            health="healthy",
            lifecycle="unmanaged",
        ),
    )
    registry = DependencyRegistry("fixture")
    registry.register(
        "source:pg",
        display_name="Demo PG",
        ownership="external",
        probe=DependencyProbe(probe, cache_seconds=30),
    )

    # Duplicate registration still fails unless replacement is explicit.
    with pytest.raises(ValueError, match="already registered"):
        registry.register("source:pg", probe=DependencyProbe(probe))

    await registry.get("source:pg")
    renamed_probe = AsyncMock(
        return_value=DependencyHealth(
            health="healthy",
            lifecycle="unmanaged",
        ),
    )
    renamed = registry.register(
        "source:pg",
        display_name="Prod PG",
        ownership="external",
        probe=DependencyProbe(renamed_probe, cache_seconds=30),
        replace=True,
    )
    status = await registry.get("source:pg")

    assert renamed.display_name == "Prod PG"
    assert status["display_name"] == "Prod PG"
    # Replacement drops the cached health so the new probe runs.
    assert renamed_probe.await_count == 1
    assert registry.ids(prefix="source:") == ["source:pg"]

    assert registry.unregister("source:pg") is True
    assert registry.unregister("source:pg") is False
    assert len(registry) == 0
    with pytest.raises(DependencyError):
        await registry.get("source:pg")


@pytest.mark.asyncio
async def test_snapshot_tolerates_mid_flight_unregister(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = AsyncMock(
        return_value=DependencyHealth(
            health="healthy",
            lifecycle="unmanaged",
        ),
    )
    registry = DependencyRegistry("fixture")
    registry.register(
        "kept",
        ownership="external",
        probe=DependencyProbe(probe),
    )
    registry.register(
        "removed",
        ownership="external",
        probe=DependencyProbe(probe),
    )

    original_get = registry.get

    async def racing_get(dependency_id: str, *, force: bool = False):
        if dependency_id == "removed":
            registry.unregister("removed")
        return await original_get(dependency_id, force=force)

    monkeypatch.setattr(registry, "get", racing_get)

    snapshot = await registry.snapshot()

    assert [item["id"] for item in snapshot["dependencies"]] == ["kept"]
    assert snapshot["summary"] == "healthy"
