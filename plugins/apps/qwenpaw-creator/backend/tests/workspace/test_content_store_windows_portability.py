# -*- coding: utf-8 -*-
from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from services.runtime_files import atomic_store as atomic_store_module
from services.workspace import content_store as content_store_module
from services.workspace.content_store import ContentStore


pytestmark = pytest.mark.unit


def test_content_store_tolerates_windows_like_private_file_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = os.open

    def windows_like_open(target, flags, mode=0o777, *args, **kwargs):
        if Path(target).is_dir():
            raise PermissionError(errno.EACCES, "Permission denied", target)
        return real_open(target, flags, mode, *args, **kwargs)

    monkeypatch.delattr(atomic_store_module.os, "fchmod", raising=False)
    monkeypatch.setattr(content_store_module.os, "open", windows_like_open)

    store = ContentStore(tmp_path)
    stored = store.put_bytes(b"creator-content")

    assert stored.path.read_bytes() == b"creator-content"
    assert stored.size == len(b"creator-content")
