# -*- coding: utf-8 -*-
"""Unit tests for the process-wide runtime readiness gate."""

from __future__ import annotations

import asyncio

import pytest

from qwenpaw.utils import runtime_readiness as readiness


@pytest.fixture(autouse=True)
def _reset_readiness():
    readiness.reset_runtime_readiness()
    yield
    readiness.reset_runtime_readiness()


@pytest.mark.asyncio
async def test_unbound_gate_is_a_noop() -> None:
    """CLI and embedded callers must not block on a missing lifespan."""
    assert readiness.is_runtime_ready() is True
    await readiness.wait_runtime_ready(timeout=0)


@pytest.mark.asyncio
async def test_ready_gate_returns_immediately() -> None:
    event = asyncio.Event()
    readiness.bind_runtime_ready(event)
    readiness.mark_runtime_ready()

    assert readiness.is_runtime_ready() is True
    await readiness.wait_runtime_ready(timeout=0)


@pytest.mark.asyncio
async def test_wait_times_out_with_startup_reason() -> None:
    event = asyncio.Event()
    readiness.bind_runtime_ready(event)

    with pytest.raises(readiness.RuntimeNotReadyError) as exc_info:
        await readiness.wait_runtime_ready(timeout=0.05)

    assert exc_info.value.reason == "startup timeout"
    assert "startup has been in progress" in str(exc_info.value)


@pytest.mark.asyncio
async def test_failure_wakes_waiters_with_reason() -> None:
    event = asyncio.Event()
    readiness.bind_runtime_ready(event)

    waiter = asyncio.create_task(readiness.wait_runtime_ready(timeout=5))
    await asyncio.sleep(0)
    readiness.mark_runtime_failed("plugin activation exploded")

    with pytest.raises(readiness.RuntimeNotReadyError) as exc_info:
        await waiter
    assert exc_info.value.reason == "plugin activation exploded"
    assert readiness.is_runtime_ready() is False


@pytest.mark.asyncio
async def test_mark_ready_wakes_waiter() -> None:
    event = asyncio.Event()
    readiness.bind_runtime_ready(event)

    waiter = asyncio.create_task(readiness.wait_runtime_ready(timeout=5))
    await asyncio.sleep(0)
    readiness.mark_runtime_ready()

    await asyncio.wait_for(waiter, timeout=1)
    assert readiness.is_runtime_ready() is True


@pytest.mark.asyncio
async def test_late_failure_does_not_undo_ready() -> None:
    event = asyncio.Event()
    readiness.bind_runtime_ready(event)
    readiness.mark_runtime_ready()

    readiness.mark_runtime_failed("teardown failed")

    assert readiness.is_runtime_ready() is True
    assert readiness.runtime_failure_reason() is None


@pytest.mark.asyncio
async def test_wait_budget_env_override(monkeypatch) -> None:
    monkeypatch.setenv("QWENPAW_RUNTIME_READY_TIMEOUT", "0.05")
    assert readiness.default_wait_timeout() == pytest.approx(0.05)

    event = asyncio.Event()
    readiness.bind_runtime_ready(event)
    with pytest.raises(readiness.RuntimeNotReadyError):
        await readiness.wait_runtime_ready()


@pytest.mark.asyncio
async def test_invalid_wait_budget_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("QWENPAW_RUNTIME_READY_TIMEOUT", "not-a-number")
    assert readiness.default_wait_timeout() == pytest.approx(
        readiness.DEFAULT_WAIT_TIMEOUT_SECONDS,
    )

    monkeypatch.setenv("QWENPAW_RUNTIME_READY_TIMEOUT", "-1")
    assert readiness.default_wait_timeout() == pytest.approx(
        readiness.DEFAULT_WAIT_TIMEOUT_SECONDS,
    )


@pytest.mark.asyncio
async def test_http_gate_maps_not_ready_to_503(monkeypatch) -> None:
    from fastapi import HTTPException

    from qwenpaw.app.routers.console import _require_runtime_ready_for_chat

    monkeypatch.setenv("QWENPAW_RUNTIME_READY_HTTP_TIMEOUT", "0")
    event = asyncio.Event()
    readiness.bind_runtime_ready(event)

    with pytest.raises(HTTPException) as exc_info:
        await _require_runtime_ready_for_chat()

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "5"}
    assert "Runtime is not ready" in str(exc_info.value.detail)


def test_cross_loop_wait_raises_instead_of_hanging() -> None:
    first = asyncio.new_event_loop()
    second = asyncio.new_event_loop()
    try:

        async def _bind():
            readiness.bind_runtime_ready(asyncio.Event())

        first.run_until_complete(_bind())

        with pytest.raises(
            readiness.RuntimeNotReadyError,
            match="different event loop",
        ):
            second.run_until_complete(
                readiness.wait_runtime_ready(timeout=5),
            )
    finally:
        first.close()
        second.close()


@pytest.mark.asyncio
async def test_agent_builder_checks_the_gate_first(monkeypatch) -> None:
    import qwenpaw.runtime.builder as builder_module

    async def _raise_not_ready() -> None:
        raise readiness.RuntimeNotReadyError("startup timeout", 1.0)

    monkeypatch.setattr(
        builder_module,
        "wait_runtime_ready",
        _raise_not_ready,
    )

    with pytest.raises(readiness.RuntimeNotReadyError):
        await builder_module.AgentBuilder().build(None)


def test_console_chat_endpoint_returns_503_before_admission(
    monkeypatch,
) -> None:
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from qwenpaw.app.routers.console import router as console_router

    @asynccontextmanager
    async def lifespan(_app):
        readiness.bind_runtime_ready(asyncio.Event())
        yield

    monkeypatch.setenv("QWENPAW_RUNTIME_READY_HTTP_TIMEOUT", "0")
    app = FastAPI(lifespan=lifespan)
    app.include_router(console_router, prefix="/api")

    with TestClient(app) as client:
        response = client.post(
            "/api/console/chat",
            json={
                "session_id": "readiness-session",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "hi"}],
                    },
                ],
            },
        )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert "Runtime is not ready" in response.json()["detail"]
