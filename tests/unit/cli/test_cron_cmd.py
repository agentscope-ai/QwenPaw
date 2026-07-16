# -*- coding: utf-8 -*-
import click
import pytest
from click.testing import CliRunner

from qwenpaw.cli.cron_cmd import _build_spec_from_cli, cron_group


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
