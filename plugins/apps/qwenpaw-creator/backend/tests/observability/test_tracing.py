# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import Depends, FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
import pytest

from api.dependencies import bind_creator_trace_request
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
    ProjectStore(data_root).create(
        Project.new(
            project_id=project_id,
            name=f"Observability {project_id}",
        ),
    )


def test_trace_span_persists_parent_context_redaction_and_error(
    tmp_path,
    monkeypatch,
):
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
            async with trace_span(
                "test.child",
                component="test",
                runId="run-1",
            ):
                trace_event(
                    "test.task",
                    component="test",
                    taskId="task-1",
                    attributes={"authorization": "Bearer secret"},
                )
            with pytest.raises(RuntimeError, match="boom"):
                async with trace_span("test.failure", component="test"):
                    raise RuntimeError("boom")

    asyncio.run(scenario())
    records = read_trace_records(filters={"sessionId": "session-1"}, limit=100)

    assert [item["name"] for item in records] == [
        "test.root.started",
        "test.child.started",
        "test.task",
        "test.child.finished",
        "test.failure.started",
        "test.failure.finished",
        "test.root.finished",
    ]
    trace_ids = {item["traceId"] for item in records}
    assert len(trace_ids) == 1
    child = next(
        item for item in records if item["name"] == "test.child.started"
    )
    root = records[0]
    assert child["parentSpanId"] == root["spanId"]
    assert child["runId"] == "run-1"
    task = next(item for item in records if item["name"] == "test.task")
    assert task["taskId"] == "task-1"
    assert task["attributes"]["authorization"] == "[REDACTED]"
    assert root["attributes"]["apiKey"] == "[REDACTED]"
    assert root["attributes"]["content"] == {"redacted": True, "chars": 14}
    failure = next(
        item for item in records if item["name"] == "test.failure.finished"
    )
    assert failure["status"] == "error"
    assert failure["attributes"]["errorType"] == "RuntimeError"
    assert failure["attributes"]["durationMs"] >= 0


def test_trace_reader_filters_and_limits(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path / "creator-runtime"))
    monkeypatch.setenv("CREATOR_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("CREATOR_TRACING_ENABLED", "true")
    for index in range(5):
        trace_event(
            "test.record",
            component="test",
            sessionId="wanted" if index % 2 == 0 else "other",
            attributes={"index": index},
        )

    records = read_trace_records(filters={"sessionId": "wanted"}, limit=2)
    assert [item["attributes"]["index"] for item in records] == [2, 4]

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
    path = observability_config_path()
    assert migrated == ObservabilityConfigData(
        enabled=False,
        traceDirectory=str(tmp_path / "legacy-traces"),
        logLevel="WARNING",
        captureContent=True,
    )
    assert path == data_root / "config" / "observability.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert (
        json.loads(path.read_text(encoding="utf-8"))["captureContent"] is True
    )

    monkeypatch.setenv("CREATOR_TRACING_ENABLED", "true")
    assert load_observability_config().enabled is False

    save_observability_config(
        ObservabilityConfigData(
            enabled=True,
            traceDirectory="diagnostics/traces",
            logLevel="INFO",
            captureContent=False,
        ),
    )
    saved = load_observability_config()
    assert saved.enabled is True
    assert saved.trace_directory == "diagnostics/traces"


def test_tracing_never_breaks_runtime_without_a_data_workspace(monkeypatch):
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    trace_event("test.no-root", component="test")

    async def scenario() -> None:
        async with trace_span("test.no-root-span", component="test"):
            pass

    asyncio.run(scenario())


def test_creator_file_logging_and_trace_are_isolated_by_project(
    tmp_path,
    monkeypatch,
):
    data_root = tmp_path / "creator-runtime"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    save_observability_config(ObservabilityConfigData())
    project_id = "project-log-1"
    _create_project(data_root, project_id)

    try:
        system_log_path = configure_creator_file_logging(data_root)
        logger = setup_logger("test.creator.file")
        logger.info("system logging is active")
        trace_event(
            "creator.test.system_logging",
            component="test",
        )
        with bind_trace_context(projectId=project_id):
            logger.info("project file logging is active")
        trace_event(
            "creator.test.file_logging",
            component="test",
            projectId=project_id,
        )
        for handler in logger.handlers:
            handler.flush()
        for handler in logging.getLogger("qwenpaw.creator").handlers:
            handler.flush()

        project_log_path = creator_log_path(
            data_root,
            project_id=project_id,
        )
        assert system_log_path == creator_log_path(data_root)
        assert system_log_path.stat().st_mode & 0o777 == 0o600
        assert project_log_path.stat().st_mode & 0o777 == 0o600

        # Trace records persist only to the trace jsonl files; log files
        # carry business log lines exclusively.
        system_content = system_log_path.read_text(encoding="utf-8")
        assert "system logging is active" in system_content
        assert "project file logging is active" not in system_content
        assert '"name":"creator.test.' not in system_content

        project_content = project_log_path.read_text(encoding="utf-8")
        assert "project file logging is active" in project_content
        assert "system logging is active" not in project_content
        assert '"name":"creator.test.' not in project_content

        system_traces = list(
            (data_root / "observability" / "traces").glob(
                "creator-trace-*.jsonl",
            ),
        )
        project_traces = list(
            (data_root / project_id / "observability" / "traces").glob(
                "creator-trace-*.jsonl",
            ),
        )
        assert len(system_traces) == 1
        assert len(project_traces) == 1
        assert '"name":"creator.test.system_logging"' in system_traces[
            0
        ].read_text(encoding="utf-8")
        assert '"name":"creator.test.file_logging"' not in system_traces[
            0
        ].read_text(encoding="utf-8")
        assert '"name":"creator.test.file_logging"' in project_traces[
            0
        ].read_text(encoding="utf-8")
        assert project_traces[0].stat().st_mode & 0o777 == 0o600
        assert (
            read_trace_records(
                filters={"projectId": project_id},
            )[
                0
            ]["name"]
            == "creator.test.file_logging"
        )
    finally:
        shutdown_creator_file_logging()


def test_creator_http_dependency_persists_correlated_request_span(
    tmp_path,
    monkeypatch,
):
    data_root = tmp_path / "creator-runtime"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    save_observability_config(ObservabilityConfigData())
    _create_project(data_root, "project-http-1")
    app = FastAPI()

    @app.get(
        "/projects/{project_id}/probe",
        dependencies=[Depends(bind_creator_trace_request)],
    )
    async def probe(
        request: Request,
        response: Response,
    ) -> dict[str, str]:
        del request, response
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
    assert response.headers["X-Request-ID"] == "request-http-1"
    trace_id = response.headers["X-Creator-Trace-ID"]
    assert trace_id.startswith("trace-")

    records = read_trace_records(
        filters={"requestId": "request-http-1"},
        limit=10,
    )
    assert [item["name"] for item in records] == [
        "creator.http.request.started",
        "creator.http.request.finished",
    ]
    assert {item["traceId"] for item in records} == {trace_id}
    assert {item["projectId"] for item in records} == {"project-http-1"}
    assert records[0]["attributes"] == {
        "method": "GET",
        "path": "/projects/project-http-1/probe",
        "queryKeys": ["refresh"],
    }
    assert not list(
        (data_root / "observability" / "traces").glob(
            "creator-trace-*.jsonl",
        ),
    )
    assert (
        len(
            list(
                (
                    data_root / "project-http-1" / "observability" / "traces"
                ).glob("creator-trace-*.jsonl"),
            ),
        )
        == 1
    )


def test_unknown_project_trace_falls_back_to_system_without_creating_project(
    tmp_path,
    monkeypatch,
):
    data_root = tmp_path / "creator-runtime"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    save_observability_config(ObservabilityConfigData())

    trace_event(
        "creator.test.unknown_project",
        component="test",
        projectId="missing-project",
    )

    assert not (data_root / "missing-project").exists()
    system_traces = list(
        (data_root / "observability" / "traces").glob(
            "creator-trace-*.jsonl",
        ),
    )
    assert len(system_traces) == 1
    assert '"name":"creator.test.unknown_project"' in system_traces[
        0
    ].read_text(encoding="utf-8")


def test_project_observability_symlink_is_rejected_and_never_written(
    tmp_path,
    monkeypatch,
):
    data_root = tmp_path / "creator-runtime"
    project_id = "project-symlink"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    save_observability_config(ObservabilityConfigData())
    _create_project(data_root, project_id)
    outside = tmp_path / "outside"
    outside.mkdir()
    observability_root = data_root / project_id / "observability"
    (observability_root / "logs").rmdir()
    (observability_root / "traces").rmdir()
    observability_root.rmdir()
    observability_root.symlink_to(
        outside,
        target_is_directory=True,
    )

    try:
        system_log_path = configure_creator_file_logging(data_root)
        logger = setup_logger("test.creator.symlink")
        with bind_trace_context(projectId=project_id):
            logger.warning("unsafe project path is a system diagnostic")
        trace_event(
            "creator.test.symlink_rejected",
            component="test",
            projectId=project_id,
        )
        for handler in logger.handlers:
            handler.flush()

        assert not list(outside.iterdir())
        assert (
            "unsafe project path is a system diagnostic"
            in system_log_path.read_text(encoding="utf-8")
        )
        system_traces = list(
            (data_root / "observability" / "traces").glob(
                "creator-trace-*.jsonl",
            ),
        )
        assert len(system_traces) == 1
        assert '"name":"creator.test.symlink_rejected"' in system_traces[
            0
        ].read_text(encoding="utf-8")
    finally:
        shutdown_creator_file_logging()
