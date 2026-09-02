# -*- coding: utf-8 -*-
"""Keep the advisor tests away from the real ``~/.qwenpaw``."""
from __future__ import annotations

import pytest

import qwenpaw.constant as _constant


@pytest.fixture(autouse=True)
def isolated_advisor_dir(monkeypatch, tmp_path):
    """Redirect advisor transcripts (``ADVISOR_DIR``) to a temp dir.

    ``AdvisorMode.build_middleware`` resolves the transcript directory
    through ``default_log_dir`` on every call, so without this every test
    that lets a plan or intervention land writes a ``<agent>/<session>.json``
    into the developer's real working directory.
    """
    advisor_dir = tmp_path / "advisor"
    monkeypatch.setattr(_constant, "ADVISOR_DIR", advisor_dir)
    return advisor_dir
