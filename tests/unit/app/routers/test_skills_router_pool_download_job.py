# -*- coding: utf-8 -*-
"""Pool download as a job: start/state/cancel and the completion-wins rule.

The job adds no download logic of its own — it runs the same blocking body as
``POST /pool/download`` — so these tests pin the parts the job *is*: that it
hands the body through unchanged, that the state it reports is the outcome
the body produced, and that a cancellation which lands too late loses.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument  # noqa: E501

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, status

from qwenpaw.agents.skill_system.store import (
    _cancel_checker_ctx,
    ensure_not_cancelled,
    with_cancel_checker,
)
from qwenpaw.app.routers import skills as skills_module
from qwenpaw.app.routers.skills import (
    DownloadFromPoolRequest,
    PoolDownloadJob,
    PoolDownloadState,
    _ResolvedDownloadTarget,
)
from qwenpaw.exceptions import SkillImportCancelled


@pytest.fixture(autouse=True)
def _clean_registries():
    """Keep the module-level job registries from leaking between tests."""
    registries = (
        skills_module._pool_download_jobs,
        skills_module._pool_download_runtime_jobs,
        skills_module._pool_download_cancel_events,
    )
    for registry in registries:
        registry.clear()
    yield
    for registry in registries:
        registry.clear()


def _body(skill_name: str = "demo") -> DownloadFromPoolRequest:
    return DownloadFromPoolRequest(skill_name=skill_name)


def _target(workspace_id: str = "ws-1") -> _ResolvedDownloadTarget:
    return _ResolvedDownloadTarget(
        workspace_id=workspace_id,
        workspace_dir=Path("/tmp") / workspace_id,
    )


async def _wait_for_terminal(job_id: str, *, tries: int = 200) -> Any:
    for _ in range(tries):
        job = await skills_module._pool_download_job_get(job_id)
        if job is not None and (
            job.state in skills_module._POOL_DOWNLOAD_TERMINAL_STATES
        ):
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("the download job never reached a terminal state")


async def _wait_for(predicate, *, tries: int = 200) -> None:
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


def test_the_job_handles_are_the_approved_shape():
    """Pin the routes and the fields the design note was approved with.

    The note promises three routes under the skills router, a 202 on start,
    and a job id that carries no progress: no percentage, no file count, no
    total. These paths are the declared ones, prefix included.
    """
    routes = {
        (route.path, method): route
        for route in skills_module.router.routes
        for method in getattr(route, "methods", set())
    }

    start = routes[("/skills/pool/downloads", "POST")]
    assert start.status_code == status.HTTP_202_ACCEPTED
    assert ("/skills/pool/downloads/{job_id}", "GET") in routes
    assert ("/skills/pool/downloads/{job_id}", "DELETE") in routes
    # The direct download keeps its own route, unchanged.
    assert ("/skills/pool/download", "POST") in routes
    assert set(PoolDownloadJob.model_fields) == {
        "job_id",
        "state",
        "error",
    }
    assert {state.value for state in PoolDownloadState} == {
        "running",
        "cancelling",
        "completed",
        "failed",
        "cancelled",
    }


async def test_start_hands_the_blocking_body_through_unchanged(monkeypatch):
    """The job must run the shared body, not a job-specific copy of it."""
    seen: dict[str, Any] = {}

    def fake_download(body, *, targets=None, cancel_checker=None):
        seen["skill_name"] = body.skill_name
        seen["targets"] = targets
        seen["cancel_checker"] = cancel_checker
        return {"downloaded": [{"workspace_id": "ws-1", "name": "demo"}]}

    monkeypatch.setattr(
        skills_module,
        "_resolve_download_targets",
        lambda body: [_target()],
    )
    monkeypatch.setattr(skills_module, "_download_pool_skill", fake_download)

    started = await skills_module.start_pool_download(_body())
    assert started.state is PoolDownloadState.RUNNING

    finished = await _wait_for_terminal(started.job_id)
    assert finished.state is PoolDownloadState.COMPLETED
    assert finished.result == {
        "downloaded": [{"workspace_id": "ws-1", "name": "demo"}],
    }
    assert finished.error is None
    assert finished.workspace_ids == ["ws-1"]
    assert seen["skill_name"] == "demo"
    assert [target.workspace_id for target in seen["targets"]] == ["ws-1"]
    # The worker arms the shared checker rather than a job-local cancel flag.
    assert callable(seen["cancel_checker"])
    # The runtime slot is released once the worker has stopped.
    assert started.job_id not in skills_module._pool_download_runtime_jobs
    assert started.job_id not in skills_module._pool_download_cancel_events


async def test_start_pins_targets_so_the_worker_does_not_resolve_twice(
    monkeypatch,
):
    calls: list[Any] = []

    def fake_download(body, *, targets=None, cancel_checker=None):
        calls.append(targets)
        return {"downloaded": []}

    monkeypatch.setattr(
        skills_module,
        "_resolve_download_targets",
        lambda body: [_target("ws-1"), _target("ws-2")],
    )
    monkeypatch.setattr(skills_module, "_download_pool_skill", fake_download)

    started = await skills_module.start_pool_download(_body())
    job = await skills_module._pool_download_job_get(started.job_id)
    assert job.workspace_ids == ["ws-1", "ws-2"]

    await _wait_for_terminal(started.job_id)
    assert [target.workspace_id for target in calls[0]] == ["ws-1", "ws-2"]


async def test_start_rejects_an_empty_target_list(monkeypatch):
    monkeypatch.setattr(
        skills_module,
        "_resolve_download_targets",
        lambda body: [],
    )

    with pytest.raises(HTTPException) as caught:
        await skills_module.start_pool_download(_body())
    assert caught.value.status_code == 400


async def test_a_cancellation_at_a_file_boundary_is_recorded_as_cancelled(
    monkeypatch,
):
    def fake_download(body, *, targets=None, cancel_checker=None):
        assert cancel_checker is not None
        # Stand in for a copy that notices the cancel between two files.
        raise SkillImportCancelled("Skill import cancelled by user")

    monkeypatch.setattr(
        skills_module,
        "_resolve_download_targets",
        lambda body: [_target()],
    )
    monkeypatch.setattr(skills_module, "_download_pool_skill", fake_download)

    started = await skills_module.start_pool_download(_body())
    finished = await _wait_for_terminal(started.job_id)

    assert finished.state is PoolDownloadState.CANCELLED
    assert finished.error is None


async def test_a_cancellation_that_arrives_too_late_loses_to_completion(
    monkeypatch,
):
    """A cancel after the last boundary must not undo a finished download.

    Only a copy that *observes* the cancel can cancel anything, so an event
    that is set but never observed cannot turn a completed install into a
    cancelled one.
    """
    state: dict[str, Any] = {}
    reach_the_end = threading.Event()

    def fake_download(body, *, targets=None, cancel_checker=None):
        # Hold here until the test has the cancel event, then set it as a
        # cancel that landed after the last boundary would.
        reach_the_end.wait(timeout=10)
        state["event"].set()
        assert cancel_checker is not None
        return {"downloaded": [{"workspace_id": "ws-1", "name": "demo"}]}

    monkeypatch.setattr(
        skills_module,
        "_resolve_download_targets",
        lambda body: [_target()],
    )
    monkeypatch.setattr(skills_module, "_download_pool_skill", fake_download)

    started = await skills_module.start_pool_download(_body())
    state["event"] = skills_module._pool_download_cancel_events[started.job_id]
    reach_the_end.set()

    finished = await _wait_for_terminal(started.job_id)

    assert state["event"].is_set(), "the cancel really did arrive"
    assert finished.state is PoolDownloadState.COMPLETED
    assert finished.result == {
        "downloaded": [{"workspace_id": "ws-1", "name": "demo"}],
    }


async def test_the_cancel_route_reports_cancelling_and_arms_the_worker(
    monkeypatch,
):
    """Cancelling must not itself claim the terminal state.

    The worker is still holding the locks and may still be rolling back, so
    the honest answer is ``cancelling``; the terminal state is the worker's.
    """
    observed: dict[str, Any] = {}
    release = threading.Event()

    def fake_download(body, *, targets=None, cancel_checker=None):
        observed["checker"] = cancel_checker
        release.wait(timeout=10)
        if cancel_checker():
            raise SkillImportCancelled("Skill import cancelled by user")
        return {"downloaded": []}

    monkeypatch.setattr(
        skills_module,
        "_resolve_download_targets",
        lambda body: [_target()],
    )
    monkeypatch.setattr(skills_module, "_download_pool_skill", fake_download)

    started = await skills_module.start_pool_download(_body())
    await _wait_for(lambda: "checker" in observed)

    reply = await skills_module.cancel_pool_download(started.job_id)
    assert reply.job_id == started.job_id
    assert reply.state is PoolDownloadState.CANCELLING
    assert observed["checker"]() is True, "the worker can see the cancel"
    # The client keeps polling; the state is still not terminal.
    assert (
        await skills_module.get_pool_download_job(started.job_id)
    ).state is PoolDownloadState.CANCELLING

    release.set()
    finished = await _wait_for_terminal(started.job_id)
    assert finished.state is PoolDownloadState.CANCELLED


async def test_the_cancel_route_is_honest_about_a_finished_job(monkeypatch):
    monkeypatch.setattr(
        skills_module,
        "_resolve_download_targets",
        lambda body: [_target()],
    )
    monkeypatch.setattr(
        skills_module,
        "_download_pool_skill",
        lambda body, *, targets=None, cancel_checker=None: {"downloaded": []},
    )

    started = await skills_module.start_pool_download(_body())
    await _wait_for_terminal(started.job_id)

    reply = await skills_module.cancel_pool_download(started.job_id)
    assert reply.state is PoolDownloadState.COMPLETED


async def test_state_and_cancel_404_for_an_unknown_job():
    for call in (
        skills_module.get_pool_download_job,
        skills_module.cancel_pool_download,
    ):
        with pytest.raises(HTTPException) as caught:
            await call("nope")
        assert caught.value.status_code == 404


def test_a_broken_checker_never_fails_a_download():
    """A cancellation channel that errors must degrade to "not cancelled"."""

    def broken() -> bool:
        raise RuntimeError("the cancel channel is down")

    with with_cancel_checker(broken):
        ensure_not_cancelled()  # must not raise


def test_the_armed_checker_is_scoped_to_the_with_block():
    assert _cancel_checker_ctx.get() is None
    with with_cancel_checker(lambda: True):
        with pytest.raises(SkillImportCancelled):
            ensure_not_cancelled()
    assert _cancel_checker_ctx.get() is None
    ensure_not_cancelled()  # unarmed again, so a copy is allowed to run
