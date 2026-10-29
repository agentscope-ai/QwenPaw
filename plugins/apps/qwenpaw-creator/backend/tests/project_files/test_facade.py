# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os

import pytest

from services.project_files import facade


pytestmark = pytest.mark.unit


def test_stale_runtime_owner_system_error_does_not_abort_startup(
    tmp_path,
    monkeypatch,
):
    marker = tmp_path / "runtime-owner.json"
    marker.write_text(
        json.dumps({"pid": os.getpid() + 1}),
        encoding="utf-8",
    )

    def raise_system_error(_pid, _signal):
        raise SystemError("wrapped os.kill failure")

    monkeypatch.setattr(facade.os, "kill", raise_system_error)

    # pylint: disable-next=protected-access
    assert facade._warn_on_second_backend(tmp_path) is False
    updated = json.loads(marker.read_text(encoding="utf-8"))
    assert updated["pid"] == os.getpid()
