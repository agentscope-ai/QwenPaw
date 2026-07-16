# -*- coding: utf-8 -*-
import click
import pytest
from click.testing import CliRunner

from qwenpaw.cli.cron_cmd import (
    _build_spec_from_cli,
    _resolve_update_spec,
    cron_group,
)


def _agent_spec(**overrides):
    values = {
        "task_type": "agent",
        "schedule_type": "cron",
        "name": "Background refresh",
        "cron": "0 * * * *",
        "run_at": None,
        "repeat_every_days": None,
        "repeat_end_type": None,
        "repeat_until": None,
        "repeat_count": None,
        "channel": "console",
        "target_user": "u1",
        "target_session": "console:u1",
        "text": "Refresh the index",
        "timezone": "UTC",
        "enabled": True,
        "mode": "final",
        "silent": False,
    }
    values.update(overrides)
    return _build_spec_from_cli(**values)


def test_build_agent_spec_includes_silent_delivery():
    payload = _agent_spec(silent=True)

    assert payload["dispatch"]["silent"] is True


def test_build_text_spec_rejects_silent_delivery():
    with pytest.raises(click.UsageError, match="only supported.*agent"):
        _agent_spec(task_type="text", silent=True)


def test_create_help_exposes_silent_delivery_flag():
    result = CliRunner().invoke(cron_group, ["create", "--help"])

    assert result.exit_code == 0
    assert "--silent / --no-silent" in result.output


# --- _resolve_update_spec regression tests ---


def _update(full_spec: dict, **overrides) -> dict:
    """Thin wrapper: call _resolve_update_spec with all opt-out defaults."""
    return _resolve_update_spec(
        spec=full_spec,
        task_type=overrides.pop("task_type", None),
        schedule_type=overrides.pop("schedule_type", None),
        name=overrides.pop("name", None),
        cron=overrides.pop("cron", None),
        run_at=overrides.pop("run_at", None),
        repeat_every_days=overrides.pop("repeat_every_days", None),
        repeat_end_type=overrides.pop("repeat_end_type", None),
        repeat_until=overrides.pop("repeat_until", None),
        repeat_count=overrides.pop("repeat_count", None),
        channel=overrides.pop("channel", None),
        target_user=overrides.pop("target_user", None),
        target_session=overrides.pop("target_session", None),
        text=overrides.pop("text", None),
        timezone=overrides.pop("timezone", None),
        enabled=overrides.pop("enabled", None),
        mode=overrides.pop("mode", None),
        silent=overrides.pop("silent", None),
        save_result_to_inbox=overrides.pop("save_result_to_inbox", None),
        share_session=overrides.pop("share_session", None),
        timeout_seconds=overrides.pop("timeout_seconds", None),
        tool_safety=overrides.pop("tool_safety", None),
    )


def test_update_preserves_runtime_fields():
    """Renaming a job should keep max_concurrency & misfire_grace_seconds."""
    spec = {
        "name": "original",
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": "0 4 * * *",
            "timezone": "Asia/Shanghai",
        },
        "task_type": "text",
        "text": "hello",
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {"user_id": "u1", "session_id": "s1"},
            "mode": "final",
        },
        "runtime": {
            "max_concurrency": 4,
            "misfire_grace_seconds": 1800,
            "timeout_seconds": 300,
            "share_session": True,
            "tool_safety": False,
        },
    }

    result = _update(spec, name="renamed")

    assert result["name"] == "renamed"
    assert result["runtime"]["max_concurrency"] == 4
    assert result["runtime"]["misfire_grace_seconds"] == 1800
    assert result["runtime"]["timeout_seconds"] == 300


def test_update_preserves_request_extensions():
    """Updating an agent job should preserve model and request_context."""
    spec = {
        "name": "agent-job",
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": "*/5 * * * *",
            "timezone": "UTC",
        },
        "task_type": "agent",
        "request": {
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "text", "text": "run task"}],
                },
            ],
            "session_id": "s1",
            "user_id": "u1",
            "model": "custom-model",
            "request_context": {"source_tag": "ops"},
        },
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {"user_id": "u1", "session_id": "s1"},
            "mode": "final",
        },
        "runtime": {
            "max_concurrency": 1,
            "timeout_seconds": 120,
            "misfire_grace_seconds": 600,
            "share_session": False,
            "tool_safety": False,
        },
    }

    result = _update(spec, name="renamed-agent")

    assert result["name"] == "renamed-agent"
    assert result["request"]["model"] == "custom-model"
    assert result["request"]["request_context"] == {"source_tag": "ops"}


def test_update_cli_override_applies():
    """CLI-provided values should override existing fields."""
    spec = {
        "name": "original",
        "enabled": False,
        "schedule": {"type": "cron", "cron": "0 * * * *", "timezone": "UTC"},
        "task_type": "text",
        "text": "old",
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {"user_id": "u1", "session_id": "s1"},
            "mode": "final",
        },
        "runtime": {
            "max_concurrency": 1,
            "timeout_seconds": 120,
            "misfire_grace_seconds": 600,
        },
    }

    result = _update(
        spec,
        name="new-name",
        enabled=True,
        timeout_seconds=900,
    )

    assert result["name"] == "new-name"
    assert result["enabled"] is True
    assert result["runtime"]["timeout_seconds"] == 900
    # untouched fields preserved
    assert result["runtime"]["max_concurrency"] == 1
    assert result["runtime"]["misfire_grace_seconds"] == 600
