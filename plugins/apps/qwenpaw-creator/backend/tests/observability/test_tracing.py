# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from api.dependencies import CreatorErrorRoute, bind_creator_trace_request
from api.observability_routes import router as observability_router
from domain.errors import ValidationError
from schemas.observability import ObservabilityConfigData
from services.observability import (
    bind_trace_context,
    load_observability_config,
    observability_config_path,
    read_trace_records,
    save_observability_config,
    trace_event,
    trace_span,
)
from services.project_files import Project, ProjectStore
from utils.logger import (
    configure_creator_file_logging,
    creator_log_path,
    setup_logger,
    shutdown_creator_file_logging,
)


def _create_project(data_root, project_id: str) -> None:
    project = Project.new(project_id=project_id, name=f"Obs {project_id}")
    ProjectStore(data_root).create(project)


def _data_root(tmp_path, monkeypatch) -> Path:
    data_root = tmp_path / "creator-runtime"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    save_observability_config(ObservabilityConfigData())
    return data_root


def _traces(root: Path) -> list[Path]:
    pattern = "creator-trace-*.jsonl"
    return list((root / "observability" / "traces").glob(pattern))


def test_trace_span_context_redaction_and_error(tmp_path, monkeypatch):
    # Fail-open: without a data workspace tracing must be a silent no-op.
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    trace_event("test.no-root", component="test")

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path / "creator-runtime"))
    monkeypatch.setenv("CREATOR_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("CREATOR_TRACING_ENABLED", "true")
    monkeypatch.setenv("CREATOR_TRACE_CAPTURE_CONTENT", "false")

    async def scenario() -> None:
        async with trace_span(
            "test.root",
            component="test",
            sessionId="session-1",
            attributes={"apiKey": "top-secret", "content": "private prompt"},
        ):
            async with trace_span("test.child", component="test"):
                trace_event("test.task", component="test")
            with pytest.raises(RuntimeError, match="boom"):
                async with trace_span("test.failure", component="test"):
                    raise RuntimeError("boom")

    asyncio.run(scenario())
    trace_event("test.other", component="test", sessionId="other")
    records = read_trace_records(filters={"sessionId": "session-1"}, limit=100)
    # The reader honors the session filter: "other" never shows up.
    assert [item["name"] for item in records] == (
        "test.root.started test.child.started test.task test.child.finished "
        "test.failure.started test.failure.finished test.root.finished"
    ).split()
    child = next(i for i in records if i["name"] == "test.child.started")
    root = records[0]
    assert child["parentSpanId"] == root["spanId"]
    assert root["attributes"]["apiKey"] == "[REDACTED]"
    assert root["attributes"]["content"] == {"redacted": True, "chars": 14}
    failure = next(i for i in records if i["name"] == "test.failure.finished")
    assert failure["status"] == "error"
    attrs = failure["attributes"]
    assert attrs["errorType"] == "RuntimeError" and attrs["durationMs"] >= 0
    with pytest.raises(ValueError, match="between 1 and 2000"):
        read_trace_records(limit=0)


def test_observability_config_migrates_legacy_env_once_then_file_is_authoritative(
    tmp_path,
    monkeypatch,
):
    data_root = tmp_path / "creator-runtime"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    monkeypatch.setenv("CREATOR_TRACING_ENABLED", "false")
    monkeypatch.setenv("CREATOR_TRACE_DIR", str(tmp_path / "legacy-traces"))
    monkeypatch.setenv("CREATOR_TRACE_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("CREATOR_TRACE_CAPTURE_CONTENT", "true")

    migrated = load_observability_config()
    assert migrated == ObservabilityConfigData(
        enabled=False,
        traceDirectory=str(tmp_path / "legacy-traces"),
        logLevel="WARNING",
        captureContent=True,
    )
    assert observability_config_path().stat().st_mode & 0o777 == 0o600
    # The file is now authoritative: env flips no longer apply.
    monkeypatch.setenv("CREATOR_TRACING_ENABLED", "true")
    assert load_observability_config().enabled is False
    save_observability_config(
        ObservabilityConfigData(enabled=True, traceDirectory="diag/traces"),
    )
    saved = load_observability_config()
    assert saved.enabled is True and saved.trace_directory == "diag/traces"


def test_file_logging_and_traces_are_isolated_and_symlink_safe(
    tmp_path,
    monkeypatch,
):
    data_root = _data_root(tmp_path, monkeypatch)
    _create_project(data_root, "project-log-1")
    _create_project(data_root, "project-symlink")
    outside = tmp_path / "outside"
    outside.mkdir()
    observability_root = data_root / "project-symlink" / "observability"
    for sub in ("logs", "traces"):
        (observability_root / sub).rmdir()
    observability_root.rmdir()
    observability_root.symlink_to(outside, target_is_directory=True)

    try:
        system_log_path = configure_creator_file_logging(data_root)
        logger = setup_logger("test.creator.file")
        logger.info("system logging is active")
        trace_event("creator.test.system_logging", component="test")
        with bind_trace_context(projectId="project-log-1"):
            logger.info("project file logging is active")
        trace_event(
            "creator.test.file_logging",
            component="test",
            projectId="project-log-1",
        )
        with bind_trace_context(projectId="project-symlink"):
            logger.warning("unsafe project path is a system diagnostic")
        # Symlinked/unknown projectIds fall back to the system trace and
        # never create or write through the unsafe target.
        for name, pid in (
            ("creator.test.symlink_rejected", "project-symlink"),
            ("creator.test.unknown_project", "missing-project"),
        ):
            trace_event(name, component="test", projectId=pid)
        creator = logging.getLogger("qwenpaw.creator")
        for handler in logger.handlers + creator.handlers:
            handler.flush()

        project_log = creator_log_path(data_root, project_id="project-log-1")
        assert system_log_path.stat().st_mode & 0o777 == 0o600
        # Log files carry business lines only; traces go to jsonl files.
        system_content = system_log_path.read_text(encoding="utf-8")
        assert "system logging is active" in system_content
        assert "project file logging is active" not in system_content
        assert "unsafe project path is a system diagnostic" in system_content
        assert '"name":"creator.test.' not in system_content
        assert "project file logging is active" in project_log.read_text(
            encoding="utf-8",
        )

        assert not list(outside.iterdir())
        system_trace = _traces(data_root)[0].read_text(encoding="utf-8")
        assert '"name":"creator.test.system_logging"' in system_trace
        assert '"name":"creator.test.symlink_rejected"' in system_trace
        assert '"name":"creator.test.unknown_project"' in system_trace
        project_traces = _traces(data_root / "project-log-1")
        assert len(project_traces) == 1
        assert '"name":"creator.test.file_logging"' not in system_trace
        project_trace = project_traces[0].read_text(encoding="utf-8")
        assert '"name":"creator.test.file_logging"' in project_trace
        assert project_traces[0].stat().st_mode & 0o777 == 0o600
    finally:
        shutdown_creator_file_logging()


def test_creator_http_dependency_persists_correlated_request_span(
    tmp_path,
    monkeypatch,
):
    data_root = _data_root(tmp_path, monkeypatch)
    _create_project(data_root, "project-http-1")
    app = FastAPI()

    deps = [Depends(bind_creator_trace_request)]

    @app.get("/projects/{project_id}/probe", dependencies=deps)
    async def probe() -> dict[str, str]:
        return {"status": "ok"}

    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(
                "/projects/project-http-1/probe?refresh=true",
                headers={"X-Request-ID": "request-http-1"},
            )

    response = asyncio.run(scenario())
    assert response.status_code == 200
    trace_id = response.headers["X-Creator-Trace-ID"]

    records = read_trace_records(filters={"requestId": "request-http-1"})
    assert [item["name"] for item in records] == [
        "creator.http.request.started",
        "creator.http.request.finished",
    ]
    assert {item["traceId"] for item in records} == {trace_id}
    # Query keys only: values never enter the trace record.
    assert records[0]["attributes"] == {
        "method": "GET",
        "path": "/projects/project-http-1/probe",
        "queryKeys": ["refresh"],
    }
    assert not _traces(data_root)
    assert len(_traces(data_root / "project-http-1")) == 1


def test_creator_error_route_suppresses_successful_poll_but_keeps_failure(
    tmp_path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "creator-runtime"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    save_observability_config(ObservabilityConfigData())
    _create_project(data_root, "project-poll")
    app = FastAPI()
    poll_router = APIRouter(
        dependencies=[Depends(bind_creator_trace_request)],
        route_class=CreatorErrorRoute,
    )

    @poll_router.get("/projects/{project_id}/session")
    async def successful_poll() -> dict[str, str]:
        return {"status": "unchanged"}

    @poll_router.get("/projects/{project_id}/tasks")
    async def failed_poll() -> dict[str, str]:
        raise ValidationError("poll failed")

    app.include_router(poll_router)

    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            ok = await client.get(
                "/projects/project-poll/session",
                headers={"X-Request-ID": "poll-ok"},
            )
            failed = await client.get(
                "/projects/project-poll/tasks",
                headers={"X-Request-ID": "poll-failed"},
            )
            return ok, failed

    ok, failed = asyncio.run(scenario())
    assert ok.status_code == 200
    assert failed.status_code == 422
    assert read_trace_records(filters={"requestId": "poll-ok"}) == []
    failure = read_trace_records(filters={"requestId": "poll-failed"})
    assert [item["name"] for item in failure] == [
        "creator.error.reported",
    ]
    assert failure[0]["status"] == "error"
    assert failure[0]["attributes"]["errorCode"] == "VALIDATION_ERROR"
    assert failure[0]["attributes"]["errorId"] == failed.json()["errorId"]
    assert failed.json()["traceId"] == failed.headers["X-Creator-Trace-ID"]
    assert read_trace_records(filters={"errorId": failed.json()["errorId"]})


def test_observability_config_and_trace_query_api(
    tmp_path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "creator-runtime"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    save_observability_config(ObservabilityConfigData())
    trace_event(
        "creator.test.queryable",
        component="test",
        requestId="query-request",
    )
    app = FastAPI()
    app.include_router(observability_router)

    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            missing_key = await client.put(
                "/observability/config",
                json={"enabled": True, "retentionDays": 30},
            )
            saved = await client.put(
                "/observability/config",
                headers={"Idempotency-Key": "observability-config-1"},
                json={"enabled": True, "retentionDays": 30},
            )
            queried = await client.get(
                "/observability/traces?requestId=query-request",
            )
            return missing_key, saved, queried

    missing_key, saved, queried = asyncio.run(scenario())
    assert missing_key.status_code == 422
    assert saved.status_code == 200
    assert saved.json()["retentionDays"] == 30
    assert queried.status_code == 200
    assert queried.json()["count"] == 1
    assert queried.json()["items"][0]["name"] == "creator.test.queryable"


def test_trace_retention_removes_expired_jsonl_files(tmp_path, monkeypatch):
    data_root = tmp_path / "creator-runtime"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    save_observability_config(ObservabilityConfigData(retentionDays=1))
    trace_directory = data_root / "observability" / "traces"
    trace_directory.mkdir(parents=True, exist_ok=True)
    expired = trace_directory / "creator-trace-2020-01-01.jsonl"
    expired.write_text("{}\n", encoding="utf-8")
    old = time.time() - 3 * 24 * 60 * 60
    os.utime(expired, (old, old))

    trace_event("creator.test.retention", component="test")

    assert not expired.exists()
