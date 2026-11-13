# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Shared fixtures for the file agent runtime test suite."""

from __future__ import annotations

import pytest

from services import external_skills


@pytest.fixture(autouse=True)
def _isolate_builtin_skills(tmp_path, monkeypatch):
    """Scan an empty builtin-skill directory by default.

    Code-vendored skills would otherwise join every test's skill pool and
    break exact tool-set assertions; the builtin-specific tests re-point
    the root at the real source tree explicitly.
    """

    monkeypatch.setattr(
        external_skills,
        "_BUILTIN_SKILLS_ROOT",
        tmp_path / "no-builtin-skills",
    )
    external_skills._clear_load_cache()
    yield
    external_skills._clear_load_cache()
