# -*- coding: utf-8 -*-
"""Tests for the Computer Use feature switch and its dispatch gate."""

from __future__ import annotations

import json

import pytest

import computer_use_tool.dispatch as dispatch_module
from computer_use_tool.dispatch import computer_use
from computer_use_tool.feature_state import ComputerUseFeatureState


def test_feature_state_defaults_to_enabled(tmp_path) -> None:
    state = ComputerUseFeatureState(tmp_path / "feature_state.json")

    assert state.is_enabled() is True


def test_feature_state_persists_across_instances(tmp_path) -> None:
    path = tmp_path / "feature_state.json"
    ComputerUseFeatureState(path).set_enabled(False)

    assert ComputerUseFeatureState(path).is_enabled() is False

    ComputerUseFeatureState(path).set_enabled(True)

    assert ComputerUseFeatureState(path).is_enabled() is True


def test_feature_state_survives_corrupt_file(tmp_path) -> None:
    path = tmp_path / "feature_state.json"
    path.write_text("{not json", encoding="utf-8")

    assert ComputerUseFeatureState(path).is_enabled() is True


def _first_text_block(response) -> dict:
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return json.loads(block.text)
    raise AssertionError("tool response has no text block")


@pytest.mark.asyncio
async def test_dispatch_blocks_actions_while_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
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
    tmp_path,
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
