# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

from copaw.agents.react_agent import CoPawAgent


def _make_agent_with_formatter(formatter):
    agent = object.__new__(CoPawAgent)
    agent.formatter = formatter
    return agent


def test_detects_request_time_media_normalization() -> None:
    agent = _make_agent_with_formatter(SimpleNamespace())
    assert agent._uses_request_time_media_normalization() is True


def test_rejects_missing_formatter() -> None:
    agent = _make_agent_with_formatter(None)
    assert agent._uses_request_time_media_normalization() is False


def test_toggles_formatter_media_strip_flag() -> None:
    formatter = SimpleNamespace()
    agent = _make_agent_with_formatter(formatter)

    agent._set_formatter_media_strip(True)
    assert getattr(formatter, "_copaw_force_strip_media") is True

    agent._set_formatter_media_strip(False)
    assert getattr(formatter, "_copaw_force_strip_media") is False
