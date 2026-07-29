# -*- coding: utf-8 -*-
"""Tests for optional third-party agent dependencies."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from qwenpaw.harnesses.base import MissingDependencyAdapter
from qwenpaw.harnesses.registry import create_adapter


def test_codex_and_qoder_sdks_are_optional_and_in_full() -> None:
    pyproject_path = Path(__file__).parents[3] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data["project"]
    dependencies = project["dependencies"]
    extras = project["optional-dependencies"]

    assert not any("openai-codex" in item for item in dependencies)
    assert not any("qoder-agent-sdk" in item for item in dependencies)
    assert extras["codex"] == ["openai-codex==0.144.4"]
    assert extras["qoder"] == ["qoder-agent-sdk==1.0.9"]
    assert extras["full"] == ["qwenpaw[local,whisper,codex,qoder]"]


@pytest.mark.asyncio
async def test_missing_qoder_sdk_does_not_break_provider_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(
        sys.modules,
        "qwenpaw.harnesses.qoder.adapter",
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "qoder_agent_sdk", None)

    adapter = create_adapter("qoder", tmp_path)
    status = await adapter.status()

    assert isinstance(adapter, MissingDependencyAdapter)
    assert status.available is False
    assert status.installed is False
    assert status.error == "Install qwenpaw[qoder] to enable Qoder."
