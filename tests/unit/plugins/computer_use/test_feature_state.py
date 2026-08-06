# -*- coding: utf-8 -*-
"""How the feature switch reads a state file it cannot trust.

The switch decides whether desktop automation is allowed at all. Its default
applies to an installation that has never chosen -- not to one whose recorded
choice has become unreadable, where reading it as on would restore access the
user may have deliberately withdrawn.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import computer_use_tool.dispatch as dispatch_module
from computer_use_tool.dispatch import computer_use
from computer_use_tool.feature_state import ComputerUseFeatureState


def test_a_fresh_installation_starts_from_the_default(tmp_path: Path) -> None:
    state = ComputerUseFeatureState(tmp_path / "absent.json")
    assert state.is_enabled() is True


def test_a_recorded_choice_is_honoured(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert ComputerUseFeatureState(path).is_enabled() is False

    path.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    assert ComputerUseFeatureState(path).is_enabled() is True


def test_an_unparseable_file_is_not_read_as_enabled(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The case that matters: a file exists, so a choice was made.

    Which choice cannot be recovered, and the one that must not be invented is
    the permissive one.
    """
    path = tmp_path / "state.json"
    path.write_text("{ this is not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert ComputerUseFeatureState(path).is_enabled() is False
    assert "unreadable" in caplog.text


def test_a_file_without_the_flag_is_not_read_as_enabled(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"something_else": 1}), encoding="utf-8")
    assert ComputerUseFeatureState(path).is_enabled() is False


def test_a_non_boolean_flag_is_not_coerced(tmp_path: Path) -> None:
    """``bool("false")`` is True, which is the wrong way to be wrong."""
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"enabled": "false"}), encoding="utf-8")
    assert ComputerUseFeatureState(path).is_enabled() is False


def test_turning_it_off_survives_a_reload(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    ComputerUseFeatureState(path).set_enabled(False)
    assert ComputerUseFeatureState(path).is_enabled() is False

    # And back on again, so the round trip is covered in both directions.
    ComputerUseFeatureState(path).set_enabled(True)
    assert ComputerUseFeatureState(path).is_enabled() is True


def _first_text_block(response) -> dict:
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return json.loads(block.text)
    raise AssertionError("tool response has no text block")


@pytest.mark.asyncio
async def test_dispatch_blocks_actions_while_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = ComputerUseFeatureState(tmp_path / "feature_state.json")
    state.set_enabled(False)
    monkeypatch.setattr(
        dispatch_module,
        "get_computer_use_feature_state",
        lambda: state,
    )

    def _unexpected_client():
        raise AssertionError("disabled feature must not touch the client")

    monkeypatch.setattr(
        dispatch_module,
        "get_computer_use_client",
        _unexpected_client,
    )

    payload = _first_text_block(await computer_use(action="list_apps"))

    assert payload["ok"] is False
    assert payload["error"]["code"] == "feature_disabled"


@pytest.mark.asyncio
async def test_dispatch_allows_wait_while_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = ComputerUseFeatureState(tmp_path / "feature_state.json")
    monkeypatch.setattr(
        dispatch_module,
        "get_computer_use_feature_state",
        lambda: state,
    )

    payload = _first_text_block(await computer_use(action="wait", wait_ms=0))

    assert payload["ok"] is True
    assert payload["action"] == "wait"
