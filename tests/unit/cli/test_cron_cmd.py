# -*- coding: utf-8 -*-
import copy

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


# --- _resolve_update_spec regression tests (issue #6176) ---


def _update(full_spec: dict, **overrides) -> dict:
    """Thin wrapper: call _resolve_update_spec with all opt-out defaults."""
    defaults = {
        "task_type": None,
        "schedule_type": None,
        "name": None,
        "cron": None,
        "run_at": None,
        "repeat_every_days": None,
        "repeat_end_type": None,
        "repeat_until": None,
        "repeat_count": None,
        "channel": None,
        "target_user": None,
        "target_session": None,
        "text": None,
        "timezone": None,
        "enabled": None,
        "mode": None,
        "silent": None,
        "save_result_to_inbox": None,
        "share_session": None,
        "timeout_seconds": None,
        "tool_safety": None,
    }
    defaults.update(overrides)
    return _resolve_update_spec(spec=full_spec, **defaults)


def _text_job_spec() -> dict:
    return {
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
            "meta": {"origin": "console"},
        },
        "runtime": {
            "max_concurrency": 4,
            "misfire_grace_seconds": 1800,
            "timeout_seconds": 300,
            "share_session": True,
            "tool_safety": False,
        },
        "meta": {"team": "ops"},
    }


def _agent_job_spec() -> dict:
    return {
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


def test_update_preserves_runtime_fields():
    """Renaming a job must keep max_concurrency & misfire_grace_seconds."""
    result = _update(_text_job_spec(), name="renamed")

    assert result["name"] == "renamed"
    assert result["runtime"]["max_concurrency"] == 4
    assert result["runtime"]["misfire_grace_seconds"] == 1800
    assert result["runtime"]["timeout_seconds"] == 300


def test_update_preserves_request_extensions():
    """Renaming an agent job must preserve model and request_context."""
    result = _update(_agent_job_spec(), name="renamed-agent")

    assert result["name"] == "renamed-agent"
    assert result["request"]["model"] == "custom-model"
    assert result["request"]["request_context"] == {"source_tag": "ops"}


def test_update_preserves_meta_and_dispatch_meta():
    """Job meta and dispatch.meta survive a partial update."""
    result = _update(_text_job_spec(), name="renamed")

    assert result["meta"] == {"team": "ops"}
    assert result["dispatch"]["meta"] == {"origin": "console"}


def test_update_cli_override_applies():
    """CLI-provided values override; untouched fields survive."""
    result = _update(
        _text_job_spec(),
        name="new-name",
        enabled=False,
        timeout_seconds=900,
        channel="dingtalk",
        target_user="u2",
    )

    assert result["name"] == "new-name"
    assert result["enabled"] is False
    assert result["runtime"]["timeout_seconds"] == 900
    assert result["dispatch"]["channel"] == "dingtalk"
    assert result["dispatch"]["target"]["user_id"] == "u2"
    # untouched fields preserved
    assert result["runtime"]["max_concurrency"] == 4
    assert result["runtime"]["misfire_grace_seconds"] == 1800
    assert result["dispatch"]["target"]["session_id"] == "s1"


def test_update_does_not_mutate_input_spec():
    """The existing spec dict must not be modified in place."""
    spec = _text_job_spec()
    snapshot = copy.deepcopy(spec)

    _update(spec, name="renamed", timeout_seconds=900)

    assert spec == snapshot


def test_update_schedule_type_scheduled_maps_to_once():
    """--schedule-type scheduled must write API value 'once'."""
    spec = _text_job_spec()
    spec["schedule"] = {
        "type": "once",
        "run_at": "2026-08-01T09:00:00",
        "timezone": "UTC",
    }

    result = _update(
        spec,
        schedule_type="scheduled",
        run_at="2026-09-01T10:00:00",
    )

    assert result["schedule"]["type"] == "once"
    assert result["schedule"]["run_at"] == "2026-09-01T10:00:00"


def test_update_once_schedule_survives_rename():
    """A once-schedule with repeat fields is kept intact on rename."""
    spec = _text_job_spec()
    spec["schedule"] = {
        "type": "once",
        "run_at": "2026-08-01T09:00:00",
        "timezone": "Asia/Shanghai",
        "repeat_every_days": 2,
        "repeat_end_type": "count",
        "repeat_count": 5,
    }

    result = _update(spec, name="renamed")

    assert result["schedule"] == spec["schedule"]


def test_update_agent_text_replaces_prompt_keeps_extensions():
    """--text on an agent job replaces the prompt but keeps model etc."""
    result = _update(_agent_job_spec(), text="new prompt")

    content = result["request"]["input"][0]["content"][0]
    assert content["text"] == "new prompt"
    assert result["request"]["model"] == "custom-model"
    assert result["request"]["request_context"] == {"source_tag": "ops"}


def test_update_agent_text_with_malformed_input_rebuilds():
    """--text on an agent job with empty/malformed input rebuilds it."""
    spec = _agent_job_spec()
    spec["request"]["input"] = []

    result = _update(spec, text="fresh prompt")

    content = result["request"]["input"][0]["content"][0]
    assert content["text"] == "fresh prompt"

    spec2 = _agent_job_spec()
    spec2["request"]["input"] = [
        {"role": "user", "type": "message", "content": []},
    ]

    result2 = _update(spec2, text="fresh prompt")

    content2 = result2["request"]["input"][0]["content"][0]
    assert content2["text"] == "fresh prompt"
