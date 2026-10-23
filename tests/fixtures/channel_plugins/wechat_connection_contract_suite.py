"""Trusted platform connection budget stays separate from process startup."""

from dataclasses import fields
from pathlib import Path
import sys

import pytest

from qwenpaw.app.channels.process_supervisor import LaunchSpec
from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings


def settings(**values):
    return ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        qwenpaw_version="2.2.2b4",
        startup_timeout=0.15,
        **values,
    )


def test_trusted_connection_budget_is_independent_of_short_process_startup():
    value = settings(connection_timeout=0.8)
    assert value.connection_timeout == 0.8
    assert value.startup_timeout == 0.15
    assert "connection_timeout" not in {f.name for f in fields(LaunchSpec)}


def test_unspecified_connection_budget_keeps_the_original_default():
    value = settings()
    assert value.connection_timeout is None
    assert value.startup_timeout == 0.15


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_trusted_connection_budget_is_rejected(timeout):
    with pytest.raises(ValueError):
        settings(connection_timeout=timeout)
