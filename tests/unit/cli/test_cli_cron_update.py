# -*- coding: utf-8 -*-
"""Tests for ``qwenpaw cron update`` CLI command."""

from __future__ import annotations

import json
from unittest.mock import Mock

from click.testing import CliRunner

from qwenpaw.cli.main import cli

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_EXISTING_CRON_JOB = {
    "id": "job-001",
    "name": "Daily report",
    "enabled": True,
    "schedule": {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"},
    "task_type": "text",
    "text": "Send daily summary",
    "dispatch": {
        "type": "channel",
        "channel": "console",
        "target": {"user_id": "u1", "session_id": "s1"},
        "mode": "stream",
        "meta": {"custom_key": "custom_value"},
    },
    "runtime": {
        "share_session": True,
        "max_concurrency": 1,
        "timeout_seconds": 120,
        "misfire_grace_seconds": 60,
    },
    "meta": {"notes": "important"},
}

_EXISTING_ONCE_JOB = {
    "id": "job-002",
    "name": "One-off task",
    "enabled": True,
    "schedule": {
        "type": "once",
        "run_at": "2026-12-31T23:59:00Z",
        "timezone": "UTC",
    },
    "task_type": "text",
    "text": "Run once",
    "dispatch": {
        "type": "channel",
        "channel": "console",
        "target": {"user_id": "u1", "session_id": "s1"},
        "mode": "stream",
        "meta": {},
    },
    "runtime": {
        "share_session": True,
        "max_concurrency": 1,
        "timeout_seconds": 120,
        "misfire_grace_seconds": 60,
    },
    "meta": {},
}

_EXISTING_AGENT_JOB = {
    "id": "job-003",
    "name": "Agent task",
    "enabled": True,
    "schedule": {"type": "cron", "cron": "0 12 * * *", "timezone": "UTC"},
    "task_type": "agent",
    "request": {
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [{"type": "text", "text": "Summarize the news"}],
            },
        ],
    },
    "dispatch": {
        "type": "channel",
        "channel": "console",
        "target": {"user_id": "u1", "session_id": "s1"},
        "mode": "stream",
        "meta": {},
    },
    "runtime": {
        "share_session": True,
        "max_concurrency": 1,
        "timeout_seconds": 120,
        "misfire_grace_seconds": 60,
    },
    "meta": {},
}


def _mock_cron_client(
    monkeypatch,
    get_job: dict,
) -> Mock:
    """Patch client() so GET returns *get_job* and PUT captures the payload."""
    put_payload: dict = {}

    get_response = Mock()
    get_response.status_code = 200
    get_response.json.return_value = get_job
    get_response.raise_for_status = Mock()

    put_response = Mock()
    put_response.status_code = 200
    put_response.json.return_value = {"id": get_job["id"], "ok": True}
    put_response.raise_for_status = Mock()

    def _put_capture(path, **kwargs):
        nonlocal put_payload
        put_payload.update(kwargs.get("json", {}))
        return put_response

    client = Mock()
    client.get.return_value = get_response
    client.put = Mock(side_effect=_put_capture)
    # Also mock delete for completeness
    client.delete.return_value = Mock(status_code=200)

    class _ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        "qwenpaw.cli.cron_cmd.client",
        lambda _base_url: _ClientContext(),
    )

    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_update_inline_cron_job_succeeds(monkeypatch) -> None:
    """Inline update of a cron-type text job — basic happy path."""
    client = _mock_cron_client(monkeypatch, _EXISTING_CRON_JOB)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-001",
            "--name",
            "Updated report",
            "--cron",
            "0 8 * * 1",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    # GET was called
    client.get.assert_called_once_with(
        "/cron/jobs/job-001",
        headers={"X-Agent-Id": "test-agent"},
    )
    # PUT was called
    assert client.put.call_count >= 1
    put_args = client.put.call_args
    assert put_args[0][0] == "/cron/jobs/job-001"
    payload = put_args[1]["json"]
    assert payload["id"] == "job-001"
    assert payload["name"] == "Updated report"
    assert payload["schedule"]["cron"] == "0 8 * * 1"
    # Unchanged fields preserved
    assert payload["task_type"] == "text"
    assert payload["text"] == "Send daily summary"


def test_update_once_schedule_type_does_not_error(monkeypatch) -> None:
    """Existing job has schedule type 'once' and user does NOT pass
    --schedule-type.  Previously this would fail with '--cron is required'.
    """
    client = _mock_cron_client(monkeypatch, _EXISTING_ONCE_JOB)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-002",
            "--run-at",
            "2027-01-01T00:00:00Z",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = client.put.call_args[1]["json"]
    assert payload["schedule"]["type"] == "once"
    assert payload["schedule"]["run_at"] == "2027-01-01T00:00:00Z"


def test_update_once_with_repeat_options(monkeypatch) -> None:
    """Existing 'once' job updated with repeating schedule options."""
    client = _mock_cron_client(monkeypatch, _EXISTING_ONCE_JOB)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-002",
            "--schedule-type",
            "scheduled",
            "--run-at",
            "2027-01-01T00:00:00Z",
            "--repeat-every-days",
            "7",
            "--repeat-end-type",
            "count",
            "--repeat-count",
            "10",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = client.put.call_args[1]["json"]
    assert payload["schedule"]["type"] == "once"
    assert payload["schedule"]["repeat_every_days"] == 7
    assert payload["schedule"]["repeat_end_type"] == "count"
    assert payload["schedule"]["repeat_count"] == 10


def test_update_agent_text_extraction_standard(monkeypatch) -> None:
    """Agent-type job: when --text is not passed, the existing prompt text
    is correctly extracted from request.input[0].content[0].text."""
    client = _mock_cron_client(monkeypatch, _EXISTING_AGENT_JOB)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-003",
            "--name",
            "Renamed agent",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = client.put.call_args[1]["json"]
    assert payload["name"] == "Renamed agent"
    assert payload["task_type"] == "agent"
    assert "request" in payload
    assert payload["request"]["input"][0]["content"][0]["text"] == (
        "Summarize the news"
    )


def test_update_agent_text_extraction_nonstandard_request(monkeypatch) -> None:
    """Agent job with a non-standard request structure should not crash.
    The fallback should produce None / empty, and the final spec builds
    from _build_spec_from_cli defaults."""
    broken_job = dict(_EXISTING_AGENT_JOB)
    # request has no "input" key — simulate a non-standard payload
    broken_job["request"] = {"raw": "some legacy format"}

    client = _mock_cron_client(monkeypatch, broken_job)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-003",
            "--name",
            "Fixed agent",
            "--text",
            "Fresh prompt",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = client.put.call_args[1]["json"]
    assert payload["name"] == "Fixed agent"
    # The explicit --text should win
    assert "request" in payload
    assert payload["request"]["input"][0]["content"][0]["text"] == "Fresh prompt"


def test_update_preserves_meta(monkeypatch) -> None:
    """Inline update must preserve existing top-level and dispatch meta."""
    client = _mock_cron_client(monkeypatch, _EXISTING_CRON_JOB)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-001",
            "--cron",
            "30 6 * * *",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = client.put.call_args[1]["json"]
    assert payload["meta"] == {"notes": "important"}
    assert payload["dispatch"]["meta"] == {"custom_key": "custom_value"}


def test_update_preserves_empty_meta(monkeypatch) -> None:
    """When existing meta is empty dict, update should not fail."""
    job_no_meta = dict(_EXISTING_AGENT_JOB)
    job_no_meta["meta"] = {}
    job_no_meta["dispatch"]["meta"] = {}
    client = _mock_cron_client(monkeypatch, job_no_meta)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-003",
            "--cron",
            "15 15 * * *",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = client.put.call_args[1]["json"]
    assert payload["meta"] == {}
    assert payload["dispatch"]["meta"] == {}


def test_update_no_meta_in_existing(monkeypatch) -> None:
    """When existing spec has no 'meta' key at all, update should not crash."""
    job_no_meta = dict(_EXISTING_AGENT_JOB)
    del job_no_meta["meta"]
    del job_no_meta["dispatch"]["meta"]
    _mock_cron_client(monkeypatch, job_no_meta)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-003",
            "--cron",
            "15 15 * * *",
            "--agent-id",
            "test-agent",
        ],
    )
    assert result.exit_code == 0, result.output


def test_update_overrides_text_for_text_task(monkeypatch) -> None:
    """Explicit --text for a text-type task overrides the existing value."""
    client = _mock_cron_client(monkeypatch, _EXISTING_CRON_JOB)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-001",
            "--text",
            "New message body",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = client.put.call_args[1]["json"]
    assert payload["text"] == "New message body"


def test_update_from_file(monkeypatch, tmp_path) -> None:
    """Update from a complete JSON spec file."""
    spec_file = tmp_path / "new_spec.json"
    new_spec = {
        "name": "From file",
        "enabled": False,
        "schedule": {"type": "cron", "cron": "0 0 * * 0", "timezone": "UTC"},
        "task_type": "text",
        "text": "file-based",
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {"user_id": "u2", "session_id": "s2"},
            "mode": "final",
            "meta": {},
        },
    }
    spec_file.write_text(json.dumps(new_spec), encoding="utf-8")

    client = _mock_cron_client(monkeypatch, _EXISTING_CRON_JOB)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-001",
            "-f",
            str(spec_file),
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = client.put.call_args[1]["json"]
    assert payload["id"] == "job-001"  # ID is injected
    assert payload["name"] == "From file"
    assert payload["text"] == "file-based"
    assert payload["enabled"] is False


def test_update_404_raises(monkeypatch) -> None:
    """Updating a non-existent job raises a clear error."""
    get_response = Mock()
    get_response.status_code = 404

    client = Mock()
    client.get.return_value = get_response

    class _ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        "qwenpaw.cli.cron_cmd.client",
        lambda _base_url: _ClientContext(),
    )

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "nonexistent",
            "--name",
            "nope",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code != 0
    assert "Job not found." in result.output


def test_update_switch_cron_to_scheduled(monkeypatch) -> None:
    """Switch a cron job to a one-time scheduled job."""
    client = _mock_cron_client(monkeypatch, _EXISTING_CRON_JOB)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-001",
            "--schedule-type",
            "scheduled",
            "--run-at",
            "2027-06-01T09:00:00Z",
            "--agent-id",
            "test-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = client.put.call_args[1]["json"]
    assert payload["schedule"]["type"] == "once"
    assert payload["schedule"]["run_at"] == "2027-06-01T09:00:00Z"


def test_update_with_default_agent_id(monkeypatch) -> None:
    """When --agent-id is omitted it defaults to 'default'."""
    client = _mock_cron_client(monkeypatch, _EXISTING_CRON_JOB)

    result = CliRunner().invoke(
        cli,
        [
            "cron",
            "update",
            "job-001",
            "--name",
            "no-agent-id",
        ],
    )

    assert result.exit_code == 0, result.output
    # GET should have used the default agent-id header
    client.get.assert_called_once_with(
        "/cron/jobs/job-001",
        headers={"X-Agent-Id": "default"},
    )
