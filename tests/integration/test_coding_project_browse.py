# -*- coding: utf-8 -*-
"""Coding-project browsing, listing and request validation.

Covers the read-only and validation paths of
``app/routers/coding_project.py``: the server-side directory browser
(including its not-a-directory and missing-path guards and the
hidden-entry filter), the per-agent project listing, and the input
validation on create / import-local / clone.

Deliberately no test here creates or switches a coding project: doing so
would rewrite the agent's active project directory, which is shared
state other tests in the session depend on. Only the guards that reject
a request *before* any mutation are exercised.

API endpoints:
  - GET  /api/workspace/project-directory/browse-dirs
  - GET  /api/workspace/project-directory/list
  - POST /api/workspace/project-directory/create
  - POST /api/workspace/project-directory/import-local
  - POST /api/workspace/project-directory/clone
"""
from __future__ import annotations

from pathlib import Path

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)
_BASE = "/api/workspace/project-directory"


# ============================ A. directory browser =========================


@pytest.mark.integration
@pytest.mark.p1
def test_browse_dirs_lists_a_known_directory(app_server):
    """Browsing a real directory returns its subdirectories.

    Test purpose:
      - Cover browse_dirs' scan path against a directory whose contents
        the test controls, so the response can be checked for a specific
        entry rather than merely being a list.

    Test flow:
      1. Create two subdirectories (one hidden) under the app's temp
         working directory.
      2. Browse the parent and assert the visible one is listed and the
         hidden one is filtered out by default.
    """
    root = Path(app_server.working_dir) / "integ-browse-root"
    (root / "visible-child").mkdir(parents=True, exist_ok=True)
    (root / ".hidden-child").mkdir(parents=True, exist_ok=True)

    resp = app_server.api_request(
        "GET",
        f"{_BASE}/browse-dirs",
        params={"path": str(root)},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    names = {d["name"] for d in resp.json().get("dirs") or []}
    assert "visible-child" in names, names
    assert (
        ".hidden-child" not in names
    ), "hidden directory leaked with show_hidden=false"


@pytest.mark.integration
@pytest.mark.p2
def test_browse_dirs_show_hidden_includes_dotdirs(app_server):
    """show_hidden=true surfaces dot-directories.

    Test purpose:
      - Cover the show_hidden arm of the entry filter, which is a
        separate branch from the default listing above.
    """
    root = Path(app_server.working_dir) / "integ-browse-root"
    (root / ".hidden-child").mkdir(parents=True, exist_ok=True)

    resp = app_server.api_request(
        "GET",
        f"{_BASE}/browse-dirs",
        params={"path": str(root), "show_hidden": "true"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    names = {d["name"] for d in resp.json().get("dirs") or []}
    assert ".hidden-child" in names, names


@pytest.mark.integration
@pytest.mark.p2
def test_browse_dirs_missing_path_returns_400(app_server):
    """Browsing a path that does not exist is a 400.

    Test purpose:
      - Cover the ``not target.exists()`` guard ahead of the scan.
    """
    resp = app_server.api_request(
        "GET",
        f"{_BASE}/browse-dirs",
        params={"path": "/integ/no/such/browse/root/9913"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "does not exist" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_browse_dirs_file_path_returns_400(app_server):
    """Browsing a regular file is a 400, not an empty listing.

    Test purpose:
      - Cover the ``not target.is_dir()`` guard, which is a distinct
        branch from the missing-path check.
    """
    probe = Path(app_server.working_dir) / "integ-browse-file.txt"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("not a directory\n", encoding="utf-8")

    resp = app_server.api_request(
        "GET",
        f"{_BASE}/browse-dirs",
        params={"path": str(probe)},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "not a directory" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_browse_dirs_expands_home_shorthand(app_server):
    """The default ``~`` path is expanded, not treated literally.

    Test purpose:
      - Cover the expanduser step: a literal "~" directory does not
        exist, so a missing expansion would surface as a 400.
    """
    resp = app_server.api_request(
        "GET",
        f"{_BASE}/browse-dirs",
        params={"path": "~"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json().get("dirs"), list), resp.json()


# ============================= B. project listing ==========================


@pytest.mark.integration
@pytest.mark.p1
def test_list_projects_returns_list(app_server):
    """The coding-project listing answers with a well-formed list.

    Test purpose:
      - Cover list_projects / _projects_base on an agent that may have
        no projects yet; each entry must carry the fields the console
        renders.
    """
    resp = app_server.api_request(
        "GET",
        f"{_BASE}/list",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert isinstance(entries, list), entries
    for entry in entries:
        assert entry.get("path"), entry
        assert entry.get("name"), entry
        assert "is_git" in entry, entry


# =========================== C. request validation =========================


@pytest.mark.integration
@pytest.mark.p1
def test_create_project_rejects_blank_name(app_server):
    """A blank project name is refused before any directory is made.

    Test purpose:
      - Cover create_project's name guard. This runs ahead of mkdir and
        ahead of switching the active project, so nothing is mutated.
    """
    resp = app_server.api_request(
        "POST",
        f"{_BASE}/create",
        json={"name": "   "},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "empty" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_create_project_requires_name_field(app_server):
    """Omitting the name field is a schema validation error.

    Test purpose:
      - Cover CreateProjectRequest's required-field validation.
    """
    resp = app_server.api_request(
        "POST",
        f"{_BASE}/create",
        json={},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_import_local_rejects_missing_path(app_server):
    """Importing a directory that does not exist is refused.

    Test purpose:
      - Cover the existence check, which runs ahead of the containment
        guard and so is the branch a bogus path actually hits.
    """
    resp = app_server.api_request(
        "POST",
        f"{_BASE}/import-local",
        json={"path": "/integ/no/such/local/project/7781"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "does not exist" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p1
def test_import_local_rejects_path_outside_home(app_server):
    """An existing directory outside the user's home is refused.

    Test purpose:
      - Cover _validate_import_source's containment check (upstream
        #6487), which prevents arbitrary directory exfiltration. The
        path must exist for this branch to be reached, since the
        existence check runs first, so the filesystem anchor is used: it
        exists on every platform, is never under home, and nothing is
        written to it.
    """
    outside = Path(Path.home().resolve().anchor)

    resp = app_server.api_request(
        "POST",
        f"{_BASE}/import-local",
        json={"path": str(outside)},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 403, resp.text
    assert "home directory" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_clone_rejects_missing_url(app_server):
    """A clone request without a repository URL is rejected.

    Test purpose:
      - Cover the clone request schema validation, so no git subprocess
        is started for an unusable request.
    """
    resp = app_server.api_request(
        "POST",
        f"{_BASE}/clone",
        json={},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 422), resp.text
