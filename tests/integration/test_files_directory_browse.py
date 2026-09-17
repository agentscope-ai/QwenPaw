# -*- coding: utf-8 -*-
"""Integration tests for the Files directory browser."""
from __future__ import annotations

from pathlib import Path

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)
_BASE = "/api/workspace/project-directory"


@pytest.mark.integration
@pytest.mark.p1
def test_create_browsed_directory_creates_direct_child(app_server):
    """Creating a browsed folder makes one direct child directory."""
    root = Path(app_server.working_dir) / "integ-create-folder-root"
    root.mkdir(parents=True, exist_ok=True)

    resp = app_server.api_request(
        "POST",
        f"{_BASE}/browse-dirs/create",
        json={"parent": str(root), "name": "new-folder"},
        timeout=_HTTP_TIMEOUT,
    )

    target = root / "new-folder"
    assert resp.status_code == 201, resp.text
    assert target.is_dir()
    assert resp.json() == {"path": str(target), "name": "new-folder"}


@pytest.mark.integration
@pytest.mark.p2
def test_create_browsed_directory_rejects_traversal(app_server):
    """A folder name cannot escape the browsed parent directory."""
    root = Path(app_server.working_dir) / "integ-create-folder-safe-root"
    root.mkdir(parents=True, exist_ok=True)
    escaped = root.parent / "escaped-folder"

    resp = app_server.api_request(
        "POST",
        f"{_BASE}/browse-dirs/create",
        json={"parent": str(root), "name": "../escaped-folder"},
        timeout=_HTTP_TIMEOUT,
    )

    assert resp.status_code == 400, resp.text
    assert not escaped.exists()


@pytest.mark.integration
@pytest.mark.p2
def test_create_browsed_directory_rejects_existing_name(app_server):
    """Creating an existing child reports a conflict."""
    root = Path(app_server.working_dir) / "integ-create-folder-conflict"
    target = root / "existing"
    target.mkdir(parents=True, exist_ok=True)

    resp = app_server.api_request(
        "POST",
        f"{_BASE}/browse-dirs/create",
        json={"parent": str(root), "name": "existing"},
        timeout=_HTTP_TIMEOUT,
    )

    assert resp.status_code == 409, resp.text
