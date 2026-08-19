# -*- coding: utf-8 -*-
"""A flaky download must not terminalize an already-generated video."""
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from domain.errors import ValidationError
from services.media_files import r2v_execution
from services.media_files.r2v_execution import (
    FileR2VExecutionService,
    _is_transient_materialize_error,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project


pytestmark = pytest.mark.unit

PROJECT_ID = "r2v-materialize-project"


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Materialize Retry"),
    )
    return services


def _worker(services) -> FileR2VExecutionService:
    return FileR2VExecutionService(
        services,
        materialize_retry_delays=(0.0, 0.0, 0.0),
    )


def _run_materialize(worker, monkeypatch, stub):
    monkeypatch.setattr(r2v_execution, "materialize_r2v_video", stub)

    async def live_claim(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        FileR2VExecutionService,
        "_require_live_materialize_claim",
        live_claim,
    )
    task = SimpleNamespace(project_id=PROJECT_ID, task_id="task-materialize")
    claim = SimpleNamespace(provider_result={"result_url": "https://x/v.mp4"})

    async def scenario():
        try:
            return await worker._materialize_video_with_retry(task, claim)
        finally:
            await worker.shutdown()

    return asyncio.run(scenario())


def test_transient_download_failures_are_retried(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)
    sentinel = object()
    calls = []

    async def stub(*_args, **_kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("All connection attempts failed")
        return sentinel

    result = _run_materialize(_worker(services), monkeypatch, stub)
    assert result is sentinel
    assert len(calls) == 3


def test_persistent_download_failure_raises_after_bounded_retries(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch)
    calls = []

    async def stub(*_args, **_kwargs):
        calls.append(1)
        raise httpx.ConnectError("All connection attempts failed")

    with pytest.raises(httpx.ConnectError):
        _run_materialize(_worker(services), monkeypatch, stub)
    assert len(calls) == 4  # first attempt + 3 retries


def test_deterministic_download_failure_is_not_retried(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch)
    calls = []

    async def stub(*_args, **_kwargs):
        calls.append(1)
        raise ValidationError("远程视频不允许访问本机、私有或保留网络")

    with pytest.raises(ValidationError):
        _run_materialize(_worker(services), monkeypatch, stub)
    assert len(calls) == 1


def test_transient_materialize_error_classifier():
    assert _is_transient_materialize_error(
        httpx.ConnectError("All connection attempts failed"),
    )
    assert _is_transient_materialize_error(
        httpx.ReadTimeout("read timed out"),
    )
    assert _is_transient_materialize_error(
        RuntimeError("provider returned status 503"),
    )
    assert not _is_transient_materialize_error(
        ValidationError("provider 视频为空"),
    )
