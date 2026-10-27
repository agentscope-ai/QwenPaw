# -*- coding: utf-8 -*-
"""Whisper is opt-in and stays outside default/full installations."""

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def _dependency_names(project, extra):
    """Expand QwenPaw extras without resolving third-party packages."""
    pending = list(project["dependencies"])
    if extra is not None:
        pending.append(f"{project['name']}[{extra}]")
    names, visited = set(), set()
    while pending:
        requirement = Requirement(pending.pop())
        name = canonicalize_name(requirement.name)
        names.add(name)
        if name == canonicalize_name(project["name"]):
            for selected in requirement.extras - visited:
                visited.add(selected)
                pending.extend(project["optional-dependencies"][selected])
    return names


@pytest.mark.parametrize(
    ("extra", "includes_whisper"),
    [(None, False), ("full", False), ("whisper", True)],
    ids=["default-excludes-whisper", "full-excludes-whisper", "whisper-extra"],
)
def test_whisper_is_only_installed_when_requested(extra, includes_whisper):
    path = Path(__file__).parents[3] / "pyproject.toml"
    project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]

    assert (
        "openai-whisper" in _dependency_names(project, extra)
    ) is includes_whisper
