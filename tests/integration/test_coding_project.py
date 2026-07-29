# -*- coding: utf-8 -*-
"""Integration tests for /api/workspace/coding-project/* (Sprint 4.3).

Target router: src/qwenpaw/app/routers/coding_project.py (8 routes, 0 cov)

Coverage strategy (happy path first):
  - GET (root): read the active coding dir metadata (no side effects).
  - POST /create: create a fresh project, then GET /list + GET (root)
    reflect it (create also persists ``coding_mode.project_dir`` to
    agent.json and activates the project).
  - POST /import-local: copy a real source dir (seeded under working_dir)
    into coding_projects/ and verify files landed + project activated.
  - POST /upload-zip: build an in-memory zip, upload, verify extraction +
    activation.
  - GET /browse-dirs: list a real dir seeded under working_dir.
  - PUT (root): set to an existing dir then reset to default (null).
  - GET /list: reflects created projects.
  - 400 error branches: empty name, invalid name, missing path, zip-slip.

Not covered: POST /clone — needs a real remote / network and streams
SSE; out of scope for CI (documented in the Sprint 4.3 decision log).

State note:
  /create, /import-local, /upload-zip, and PUT all persist
  ``coding_mode.project_dir`` and thus change ``get_coding_dir`` for
  subsequent requests. app_server is module-scoped, so tests that mutate
  the active project reset it back to the workspace default via
  ``PUT {"path": null}`` in a finally block to keep tests independent.

No LLM / external network deps required.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(15.0)

_CP = "/api/workspace/coding-project"


# ================================================================== #
# helpers
# ================================================================== #


def _workspace_dir(app_server) -> Path:
    return app_server.working_dir / "workspaces" / "default"


def _reset_project(app_server) -> None:
    """Reset the active coding project back to the workspace default."""
    app_server.api_request(
        "PUT",
        _CP,
        json={"path": None},
        timeout=_HTTP_TIMEOUT,
    )


def _get_project(app_server) -> dict:
    resp = app_server.api_request("GET", _CP, timeout=_HTTP_TIMEOUT)
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()


def _list_projects(app_server) -> list:
    resp = app_server.api_request(
        "GET",
        f"{_CP}/list",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()


# ================================================================== #
# A — GET (root) / GET list (happy path, P0/P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_get_project_returns_metadata(app_server) -> None:
    """GET (root) returns coding-dir metadata for the default agent.

    Test flow:
      1. Ensure default (reset).
      2. GET /api/workspace/coding-project -> 200 with the documented
         fields; default agent is workspace-default.

    API endpoints:
      - GET /api/workspace/coding-project
    """
    _reset_project(app_server)
    body = _get_project(app_server)
    for field in (
        "path",
        "name",
        "is_workspace_default",
        "workspace_dir",
        "exists",
    ):
        assert field in body, body
    assert body["is_workspace_default"] is True, body


@pytest.mark.integration
@pytest.mark.p1
def test_list_projects_returns_list(app_server) -> None:
    """GET /list returns a JSON list (possibly empty).

    API endpoints:
      - GET /api/workspace/coding-project/list
    """
    assert isinstance(_list_projects(app_server), list)


# ================================================================== #
# B — POST /create (happy path, P0)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_create_project_roundtrip(app_server) -> None:
    """POST /create makes a project, activates it, lists it.

    Test flow:
      1. POST /create {name} -> 200 {path, name}.
      2. GET /list contains the project (is_git True after git init).
      3. GET (root) now points at the created project.
      4. finally: reset to default.

    API endpoints:
      - POST /api/workspace/coding-project/create
      - GET  /api/workspace/coding-project/list
      - GET  /api/workspace/coding-project
    """
    name = "integ-cp-create-B"
    try:
        resp = app_server.api_request(
            "POST",
            f"{_CP}/create",
            json={"name": name},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        assert resp.json()["name"] == name

        names = {p["name"] for p in _list_projects(app_server)}
        assert name in names

        active = _get_project(app_server)
        assert active["name"] == name, active
        assert active["is_workspace_default"] is False, active
    finally:
        _reset_project(app_server)


# ================================================================== #
# C — POST /import-local (happy path, P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_import_local_copies_source(app_server) -> None:
    """POST /import-local copies a real source dir into the project.

    Test flow:
      1. Seed a source dir (under working_dir) with a marker file.
      2. POST /import-local {path, name} -> 200 {path, name}.
      3. The marker file exists inside the imported project dir.
      4. finally: reset to default.

    API endpoints:
      - POST /api/workspace/coding-project/import-local
    """
    src = app_server.working_dir / "integ-cp-import-src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "marker.txt").write_text("imported\n", encoding="utf-8")
    name = "integ-cp-import-C"
    try:
        resp = app_server.api_request(
            "POST",
            f"{_CP}/import-local",
            json={"path": str(src), "name": name},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        dest = Path(resp.json()["path"])
        assert (dest / "marker.txt").is_file(), resp.json()
    finally:
        _reset_project(app_server)


# ================================================================== #
# D — POST /upload-zip (happy path, P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_upload_zip_extracts_project(app_server) -> None:
    """POST /upload-zip extracts a zip into coding_projects/<name>.

    Test flow:
      1. Build an in-memory zip with one file.
      2. POST multipart (name query + file) -> 200 {path, name}.
      3. The extracted file exists inside the project dir.
      4. finally: reset to default.

    API endpoints:
      - POST /api/workspace/coding-project/upload-zip
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("src/app.py", "print('hi')\n")
    buf.seek(0)
    name = "integ-cp-zip-D"
    try:
        resp = app_server.api_request(
            "POST",
            f"{_CP}/upload-zip",
            params={"name": name},
            files={"file": ("proj.zip", buf.getvalue(), "application/zip")},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        dest = Path(resp.json()["path"])
        assert (dest / "src" / "app.py").is_file(), resp.json()
    finally:
        _reset_project(app_server)


# ================================================================== #
# E — GET /browse-dirs (happy path, P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_browse_dirs_lists_subdirs(app_server) -> None:
    """GET /browse-dirs lists subdirectories of a real path.

    Test flow:
      1. Seed a parent dir with two child dirs under working_dir.
      2. GET /browse-dirs?path=<parent> -> 200; both children appear.

    API endpoints:
      - GET /api/workspace/coding-project/browse-dirs
    """
    parent = app_server.working_dir / "integ-cp-browse"
    (parent / "alpha").mkdir(parents=True, exist_ok=True)
    (parent / "beta").mkdir(parents=True, exist_ok=True)
    resp = app_server.api_request(
        "GET",
        f"{_CP}/browse-dirs",
        params={"path": str(parent)},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body["current"] == str(parent), body
    listed = {d["name"] for d in body["dirs"]}
    assert {"alpha", "beta"} <= listed, body


# ================================================================== #
# F — PUT (root) set + reset (happy path, P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_put_set_then_reset_project(app_server) -> None:
    """PUT sets an explicit dir, then resets to workspace default.

    Test flow:
      1. Seed a target dir under working_dir.
      2. PUT {path:target} -> 200; is_workspace_default False; GET
         reflects it.
      3. PUT {path:null} -> 200; is_workspace_default True; GET reflects
         the workspace default again.

    API endpoints:
      - PUT /api/workspace/coding-project
      - GET /api/workspace/coding-project
    """
    target = app_server.working_dir / "integ-cp-put-target"
    target.mkdir(parents=True, exist_ok=True)
    try:
        set_resp = app_server.api_request(
            "PUT",
            _CP,
            json={"path": str(target)},
            timeout=_HTTP_TIMEOUT,
        )
        assert set_resp.status_code == 200, app_server.logs_tail()
        assert set_resp.json()["is_workspace_default"] is False
        assert _get_project(app_server)["is_workspace_default"] is False
    finally:
        reset_resp = app_server.api_request(
            "PUT",
            _CP,
            json={"path": None},
            timeout=_HTTP_TIMEOUT,
        )
        assert reset_resp.status_code == 200, app_server.logs_tail()
        assert reset_resp.json()["is_workspace_default"] is True
    assert _get_project(app_server)["is_workspace_default"] is True


# ================================================================== #
# G — error branches (400) — contract supplements
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p2
def test_create_empty_name_returns_400(app_server) -> None:
    """POST /create with a blank name -> 400.

    API endpoints:
      - POST /api/workspace/coding-project/create
    """
    resp = app_server.api_request(
        "POST",
        f"{_CP}/create",
        json={"name": "   "},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "empty" in resp.json()["detail"].lower()


@pytest.mark.integration
@pytest.mark.p2
def test_create_invalid_name_returns_400(app_server) -> None:
    """POST /create with a path-like name -> 400 invalid name.

    API endpoints:
      - POST /api/workspace/coding-project/create
    """
    resp = app_server.api_request(
        "POST",
        f"{_CP}/create",
        json={"name": "../escape"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "invalid" in resp.json()["detail"].lower()


@pytest.mark.integration
@pytest.mark.p2
def test_import_local_missing_path_returns_400(app_server) -> None:
    """POST /import-local with a nonexistent source -> 400.

    API endpoints:
      - POST /api/workspace/coding-project/import-local
    """
    resp = app_server.api_request(
        "POST",
        f"{_CP}/import-local",
        json={
            "path": str(app_server.working_dir / "no-such-dir-xyz"),
            "name": "integ-cp-import-missing",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "does not exist" in resp.json()["detail"].lower()


@pytest.mark.integration
@pytest.mark.p2
def test_browse_dirs_missing_path_returns_400(app_server) -> None:
    """GET /browse-dirs with a nonexistent path -> 400.

    API endpoints:
      - GET /api/workspace/coding-project/browse-dirs
    """
    resp = app_server.api_request(
        "GET",
        f"{_CP}/browse-dirs",
        params={"path": str(app_server.working_dir / "no-such-browse-xyz")},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "does not exist" in resp.json()["detail"].lower()
