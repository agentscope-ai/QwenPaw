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
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from qwenpaw.agents.skill_system.store import (
    _cancel_checker_ctx,
    ensure_not_cancelled,
    with_cancel_checker,
)
from qwenpaw.app.routers import skills as skills_module
from qwenpaw.app.routers.skills import (
    DownloadFromPoolRequest,
    PoolDownloadState,
    _ResolvedDownloadTarget,
)
from qwenpaw.exceptions import SkillImportCancelled, SkillScanError


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


def test_the_armed_checker_is_scoped_to_the_with_block():
    """The checker applies inside its block only, and fails safe."""
    assert _cancel_checker_ctx.get() is None
    with with_cancel_checker(lambda: True):
        with pytest.raises(SkillImportCancelled):
            ensure_not_cancelled()
    assert _cancel_checker_ctx.get() is None
    ensure_not_cancelled()  # unarmed again, so a copy is allowed to run

    def broken() -> bool:
        raise RuntimeError("the cancel channel is down")

    with with_cancel_checker(broken):
        ensure_not_cancelled()  # a dead channel must not fail a download


def _scan_result() -> SimpleNamespace:
    finding = SimpleNamespace(
        severity=SimpleNamespace(value="high"),
        title="blocked",
        description="blocked by policy",
        file_path="SKILL.md",
        line_number=1,
        rule_id="rule-1",
    )
    return SimpleNamespace(
        skill_name="demo",
        max_severity=SimpleNamespace(value="high"),
        findings=[finding],
    )


async def test_a_rejected_scan_fails_the_job(monkeypatch):
    """A blocked install must fail the job, never report it as completed.

    The blocking body used to turn the scanner exception into a JSONResponse,
    which the worker read as an ordinary result — so a download that was
    rejected by the scanner reported ``completed`` while nothing had been
    installed.
    """

    def fake_download(body, *, targets=None, cancel_checker=None):
        raise SkillScanError(_scan_result())

    monkeypatch.setattr(
        skills_module,
        "_resolve_download_targets",
        lambda body: [_target()],
    )
    monkeypatch.setattr(skills_module, "_download_pool_skill", fake_download)

    started = await skills_module.start_pool_download(_body())
    finished = await _wait_for_terminal(started.job_id)

    assert finished.state is PoolDownloadState.FAILED
    assert finished.error
    assert finished.result["type"] == "security_scan_failed"
    assert finished.result["skill_name"] == "demo"

    # The handle must carry the findings too: the console shows them from the
    # job response, not from the internal record.
    handle = await skills_module.get_pool_download_job(started.job_id)
    assert handle.state is PoolDownloadState.FAILED
    assert handle.result == finished.result
    assert handle.error == finished.error


async def test_the_direct_download_keeps_its_422_payload(monkeypatch):
    """The synchronous endpoint still answers 422, scoped to its own route."""

    def fake_download(body, *, targets=None, cancel_checker=None):
        raise SkillScanError(_scan_result())

    monkeypatch.setattr(skills_module, "_download_pool_skill", fake_download)

    response = await skills_module.download_pool_skill_to_workspaces(_body())

    assert response.status_code == 422
    payload = json.loads(response.body)
    assert payload["type"] == "security_scan_failed"
    assert payload["skill_name"] == "demo"


def _route_index(path_suffix: str, method: str) -> int:
    """Index of a registered route, so order itself can be asserted."""
    for index, route in enumerate(skills_module.router.routes):
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path.endswith(path_suffix) and method in methods:
            return index
    raise AssertionError(f"route not registered: {method} {path_suffix}")


@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_pool_config_routes_are_registered_before_download_jobs(method):
    """A skill actually named ``downloads`` keeps its config routes.

    ``/pool/downloads/{job_id}`` and ``/pool/{skill_name}/config`` share the
    same shape, so the first one registered wins. Registering the job route
    first made ``GET``/``DELETE /pool/downloads/config`` poll or delete a job
    whose id was literally ``config``.
    """
    config_index = _route_index("/pool/{skill_name}/config", method)
    job_index = _route_index("/pool/downloads/{job_id}", method)

    assert config_index < job_index
