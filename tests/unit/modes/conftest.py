# -*- coding: utf-8 -*-
"""Keep the advisor tests away from the real ``~/.qwenpaw``."""
from __future__ import annotations

import pytest

import qwenpaw.constant as _constant


@pytest.fixture(autouse=True)
def isolated_advisor_dir(monkeypatch, tmp_path):
    """``AdvisorMode.build_middleware`` resolves the transcript directory
    through ``default_log_dir``, so tests write transcripts to a temp dir."""
    monkeypatch.setattr(_constant, "WORKING_DIR", tmp_path)
    return tmp_path / "advisor"
