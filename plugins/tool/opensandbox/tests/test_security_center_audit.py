from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import requests

PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from security_center_audit import (  # noqa: E402
    AuditConfig,
    SecurityCenterAuditReporter,
    install_audit_hook,
)


@pytest.fixture(autouse=True)
def block_external_http(monkeypatch: pytest.MonkeyPatch):
    """Fail fast when a unit test attempts an unmocked HTTP request."""

    def blocked_request(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Unit tests must mock external HTTP requests")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked_request)


def _reporter() -> SecurityCenterAuditReporter:
    return SecurityCenterAuditReporter(
        AuditConfig(
            security_center_url="http://127.0.0.1:8091",
            agent_id="agent-test",
            timeout_seconds=2,
        ),
    )


def test_command_event_uses_existing_contract_and_redacts_secrets():
    reporter = _reporter()
    event = reporter.build_event(
        tool_name="command_run",
        arguments={
            "sandbox_id": "sandbox-1",
            "command": (
                "curl -H 'Authorization: Bearer bearer-secret' "
                "--token command-secret https://example.test"
            ),
            "working_directory": "/workspace",
        },
        duration_ms=17,
        result=([], {"id": "exec-1", "exit_code": 0}),
        occurred_at="2026-06-12T08:00:00Z",
    )

    assert event["sourceSystem"] == "opensandbox"
    assert event["eventTypeId"] == "opensandbox"
    assert event["schemaVersion"] == "1.0"
    assert event["severity"] == "DEBUG"
    assert event["payload"]["outcome"] == "SUCCEEDED"
    assert event["payload"]["executionId"] == "exec-1"
    assert event["payload"]["exitCode"] == 0
    serialized = json.dumps(event, ensure_ascii=False)
    assert "bearer-secret" not in serialized
    assert "command-secret" not in serialized
    assert "[REDACTED]" in serialized


def test_file_and_sandbox_arguments_hide_contents_and_env_values():
    reporter = _reporter()
    file_event = reporter.build_event(
        tool_name="file_write",
        arguments={
            "sandbox_id": "sandbox-1",
            "path": "/workspace/secret.txt",
            "content": "top-secret-file-content",
        },
        duration_ms=3,
    )
    create_event = reporter.build_event(
        tool_name="sandbox_create",
        arguments={
            "image": "docker.io/library/python:3.10-alpine",
            "env": {"ACCESS_TOKEN": "env-secret", "MODE": "test"},
            "auth_password": "registry-secret",
        },
        duration_ms=9,
    )

    serialized = json.dumps([file_event, create_event], ensure_ascii=False)
    assert "top-secret-file-content" not in serialized
    assert "env-secret" not in serialized
    assert "registry-secret" not in serialized
    file_content = file_event["payload"]["argumentSummary"]["content"]
    assert file_content["length"] == len("top-secret-file-content")
    assert len(file_content["sha256"]) == 64
    assert create_event["payload"]["argumentSummary"]["env"] == {
        "keys": ["ACCESS_TOKEN", "MODE"],
    }


def test_nonzero_command_exit_is_a_high_severity_failure():
    event = _reporter().build_event(
        tool_name="command_run",
        arguments={"sandbox_id": "sandbox-1", "command": "exit 7"},
        duration_ms=4,
        result=([], {"id": "exec-7", "exit_code": 7}),
    )

    assert event["severity"] == "HIGH"
    assert event["payload"]["outcome"] == "FAILED"
    assert event["payload"]["failureReason"] == "nonzero_exit_code"


def test_reporter_posts_with_requests_without_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: list[dict[str, Any]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url: str, **kwargs: Any) -> Response:
        captured.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(requests, "post", fake_post)
    reporter = _reporter()
    event = reporter.build_event(
        tool_name="sandbox_healthcheck",
        arguments={"sandbox_id": "sandbox-1"},
        duration_ms=2,
    )
    reporter.send(event)

    assert captured == [
        {
            "url": "http://127.0.0.1:8091/security-center/v1/events",
            "json": event,
            "timeout": 2,
        },
    ]


def test_audit_hook_reports_success_and_preserves_tool_result(
    monkeypatch: pytest.MonkeyPatch,
):
    sent: list[dict[str, Any]] = []
    reporter = _reporter()
    monkeypatch.setattr(reporter, "send", sent.append)

    class ToolManager:
        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            context: Any = None,
            convert_result: bool = False,
        ) -> Any:
            return ([], {"id": "exec-1", "exit_code": 0})

    class MCP:
        _tool_manager = ToolManager()

    install_audit_hook(MCP(), reporter)
    result = asyncio.run(
        MCP._tool_manager.call_tool(
            "command_run",
            {"sandbox_id": "sandbox-1", "command": "true"},
            convert_result=True,
        ),
    )

    assert result == ([], {"id": "exec-1", "exit_code": 0})
    assert len(sent) == 1
    assert sent[0]["payload"]["outcome"] == "SUCCEEDED"


def test_audit_hook_reports_failure_and_reraises_original_error(
    monkeypatch: pytest.MonkeyPatch,
):
    sent: list[dict[str, Any]] = []
    reporter = _reporter()
    monkeypatch.setattr(reporter, "send", sent.append)

    class ToolManager:
        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            context: Any = None,
            convert_result: bool = False,
        ) -> Any:
            raise ValueError("tool failed")

    class MCP:
        _tool_manager = ToolManager()

    install_audit_hook(MCP(), reporter)
    with pytest.raises(ValueError, match="tool failed"):
        asyncio.run(
            MCP._tool_manager.call_tool(
                "sandbox_create",
                {"image": "unsupported"},
            ),
        )

    assert len(sent) == 1
    assert sent[0]["severity"] == "HIGH"
    assert sent[0]["payload"]["outcome"] == "FAILED"
    assert sent[0]["payload"]["errorType"] == "ValueError"


def test_audit_upload_failure_does_not_replace_successful_tool_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    reporter = _reporter()

    def fail_upload(event: dict[str, Any]) -> None:
        raise requests.ConnectionError("8091 unavailable")

    monkeypatch.setattr(reporter, "send", fail_upload)

    class ToolManager:
        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            context: Any = None,
            convert_result: bool = False,
        ) -> Any:
            return {"status": "ok"}

    class MCP:
        _tool_manager = ToolManager()

    install_audit_hook(MCP(), reporter)
    result = asyncio.run(MCP._tool_manager.call_tool("sandbox_list", {}))

    assert result == {"status": "ok"}
    assert capsys.readouterr().out == ""
