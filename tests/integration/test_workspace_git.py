# -*- coding: utf-8 -*-
"""Integration tests for /api/workspace/git/* (Sprint 4.3).

Target router: src/qwenpaw/app/routers/git.py (11 routes, 0 cov)
Backing: real ``git`` binary via ``_git()`` shelling out; the endpoints
operate on ``get_agent_project_dir(workspace)`` which, for the default agent,
resolves to ``<working_dir>/workspaces/default``.

Coverage strategy (happy path first):
  - GET /status auto-initialises a git repo (with an initial commit) on
    first call, so it doubles as our fixture: one call gives us a real
    repo + a HEAD commit to exercise log / commit-diff / revert / diff.
  - Seed files directly into the default workspace dir (the app subprocess
    re-reads the working tree on every request) and then drive the full
    stage -> commit -> log -> commit-diff happy path over HTTP.
  - branch listing + checkout -b create.
  - 400 error branches (empty commit message, nothing staged, bad branch,
    path traversal, bad commit hash).

Isolation note:
  app_server is module-scoped and all git endpoints act on the SINGLE
  default-agent repo, so tests share one working tree. Each test seeds
  files with a UNIQUE name (``integ-git-<scenario>-*.txt``) and scopes its
  assertions to those files, so ordering / cross-test bleed does not
  matter. ``_ensure_repo`` makes the first /status call idempotent.

No LLM / external network deps required (clone is intentionally not
covered here — it needs a real remote).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(15.0)

_GIT = "/api/workspace/git"


# ================================================================== #
# helpers
# ================================================================== #


def _workspace_dir(app_server) -> Path:
    """Default agent's coding dir (== workspace_dir when unset)."""
    return app_server.working_dir / "workspaces" / "default"


def _ensure_repo(app_server) -> None:
    """Trigger auto-init by hitting GET /status once; assert 200."""
    resp = app_server.api_request(
        "GET",
        f"{_GIT}/status",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


def _seed_file(app_server, name: str, content: str = "hello\n") -> str:
    """Write a file into the default workspace; return its rel path."""
    ws = _workspace_dir(app_server)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / name).write_text(content, encoding="utf-8")
    return name


def _status(app_server) -> dict:
    resp = app_server.api_request(
        "GET",
        f"{_GIT}/status",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()


def _paths_in_status(status: dict) -> set[str]:
    return {c["path"] for c in status.get("changes", [])}


# ================================================================== #
# A — status / auto-init (happy path, P0)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_status_auto_inits_repo(app_server) -> None:
    """GET /status on a fresh workspace auto-inits a repo.

    Test flow:
      1. GET /status (first call triggers auto-init + initial commit).
      2. Assert 200 and a non-empty branch name.

    API endpoints:
      - GET /api/workspace/git/status
    """
    status = _status(app_server)
    assert isinstance(status.get("branch"), str)
    assert status["branch"] != "", status
    assert isinstance(status.get("changes"), list)


@pytest.mark.integration
@pytest.mark.p1
def test_status_shows_untracked_file(app_server) -> None:
    """A newly seeded file shows up as an untracked change.

    Test flow:
      1. Ensure repo, seed a unique untracked file.
      2. GET /status; assert the file appears with status '?'.

    API endpoints:
      - GET /api/workspace/git/status
    """
    _ensure_repo(app_server)
    name = _seed_file(app_server, "integ-git-untracked-A.txt")
    status = _status(app_server)
    assert name in _paths_in_status(status), status
    entry = next(c for c in status["changes"] if c["path"] == name)
    assert entry["status"] == "?", entry
    assert entry["staged"] is False, entry


# ================================================================== #
# B — stage / unstage / commit roundtrip (happy path, P0/P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_stage_marks_file_staged(app_server) -> None:
    """POST /stage moves a file into the staged set.

    Test flow:
      1. Seed a unique file.
      2. POST /stage {paths:[file]} -> 200 {staged:[file]}.
      3. GET /status; the file now has staged=True.

    API endpoints:
      - POST /api/workspace/git/stage
      - GET  /api/workspace/git/status
    """
    _ensure_repo(app_server)
    name = _seed_file(app_server, "integ-git-stage-B.txt")
    resp = app_server.api_request(
        "POST",
        f"{_GIT}/stage",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json()["staged"] == [name]
    status = _status(app_server)
    staged = {c["path"] for c in status["changes"] if c["staged"]}
    assert name in staged, status


@pytest.mark.integration
@pytest.mark.p1
def test_unstage_reverts_staging(app_server) -> None:
    """POST /unstage moves a staged file back to untracked.

    Test flow:
      1. Seed + stage a unique file.
      2. POST /unstage {paths:[file]} -> 200 {unstaged:[file]}.
      3. GET /status; the file is no longer staged.

    API endpoints:
      - POST /api/workspace/git/unstage
    """
    _ensure_repo(app_server)
    name = _seed_file(app_server, "integ-git-unstage-B.txt")
    app_server.api_request(
        "POST",
        f"{_GIT}/stage",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    resp = app_server.api_request(
        "POST",
        f"{_GIT}/unstage",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json()["unstaged"] == [name]
    status = _status(app_server)
    staged = {c["path"] for c in status["changes"] if c["staged"]}
    assert name not in staged, status


@pytest.mark.integration
@pytest.mark.p0
def test_stage_commit_roundtrip(app_server) -> None:
    """Seed -> stage -> commit produces a commit visible in the log.

    Test flow:
      1. Seed a unique file, stage it.
      2. POST /commit {message} -> 200 {committed:True}.
      3. GET /log; the commit message is present.
      4. GET /status; the file is no longer listed as a change.

    API endpoints:
      - POST /api/workspace/git/stage
      - POST /api/workspace/git/commit
      - GET  /api/workspace/git/log
    """
    _ensure_repo(app_server)
    name = _seed_file(app_server, "integ-git-commit-B.txt", "commit me\n")
    app_server.api_request(
        "POST",
        f"{_GIT}/stage",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    msg = "integ-git: commit B roundtrip"
    resp = app_server.api_request(
        "POST",
        f"{_GIT}/commit",
        json={"message": msg},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json()["committed"] is True

    log_resp = app_server.api_request(
        "GET",
        f"{_GIT}/log",
        timeout=_HTTP_TIMEOUT,
    )
    assert log_resp.status_code == 200, app_server.logs_tail()
    messages = [c["message"] for c in log_resp.json()]
    assert msg in messages, messages
    # committed file no longer a pending change
    assert name not in _paths_in_status(_status(app_server))


# ================================================================== #
# C — diff (happy path, P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_diff_untracked_file_shows_content(app_server) -> None:
    """GET /diff?untracked=true returns the new file's content.

    Test flow:
      1. Seed a unique untracked file with known content.
      2. GET /diff?path=<file>&untracked=true -> 200; diff contains
         the seeded content.

    API endpoints:
      - GET /api/workspace/git/diff
    """
    _ensure_repo(app_server)
    marker = "integ-diff-marker-untracked\n"
    name = _seed_file(app_server, "integ-git-diff-C.txt", marker)
    resp = app_server.api_request(
        "GET",
        f"{_GIT}/diff",
        params={"path": name, "untracked": "true"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert marker.strip() in resp.json()["diff"], resp.json()


@pytest.mark.integration
@pytest.mark.p1
def test_diff_staged_shows_content(app_server) -> None:
    """GET /diff?staged=true returns staged content.

    Test flow:
      1. Seed + stage a unique file with known content.
      2. GET /diff?staged=true -> 200; diff contains the content.

    API endpoints:
      - GET /api/workspace/git/diff
    """
    _ensure_repo(app_server)
    marker = "integ-diff-marker-staged\n"
    name = _seed_file(app_server, "integ-git-diffstaged-C.txt", marker)
    app_server.api_request(
        "POST",
        f"{_GIT}/stage",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    resp = app_server.api_request(
        "GET",
        f"{_GIT}/diff",
        params={"staged": "true"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert marker.strip() in resp.json()["diff"], resp.json()


# ================================================================== #
# D — log / commit-diff (happy path, P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_commit_diff_by_hash(app_server) -> None:
    """GET /commit-diff returns the patch for a known commit.

    Test flow:
      1. Seed + stage + commit a unique file.
      2. GET /log; take the newest commit hash.
      3. GET /commit-diff?commit_hash=<hash> -> 200; diff mentions the
         file and the returned hash echoes the request.

    API endpoints:
      - GET /api/workspace/git/log
      - GET /api/workspace/git/commit-diff
    """
    _ensure_repo(app_server)
    name = _seed_file(app_server, "integ-git-cdiff-D.txt", "patch body\n")
    app_server.api_request(
        "POST",
        f"{_GIT}/stage",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    app_server.api_request(
        "POST",
        f"{_GIT}/commit",
        json={"message": "integ-git: cdiff D"},
        timeout=_HTTP_TIMEOUT,
    )
    log = app_server.api_request(
        "GET",
        f"{_GIT}/log",
        timeout=_HTTP_TIMEOUT,
    ).json()
    assert log, "log empty after commit"
    commit_hash = log[0]["hash"]

    resp = app_server.api_request(
        "GET",
        f"{_GIT}/commit-diff",
        params={"commit_hash": commit_hash},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body["hash"] == commit_hash
    assert name in body["diff"], body


# ================================================================== #
# E — branches / checkout (happy path, P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_branches_lists_current(app_server) -> None:
    """GET /branches returns a list with exactly one current branch.

    Test flow:
      1. Ensure repo.
      2. GET /branches -> 200; a list where one entry has current=True.

    API endpoints:
      - GET /api/workspace/git/branches
    """
    _ensure_repo(app_server)
    resp = app_server.api_request(
        "GET",
        f"{_GIT}/branches",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    branches = resp.json()
    assert isinstance(branches, list) and branches, branches
    current = [b for b in branches if b["current"]]
    assert len(current) == 1, branches


@pytest.mark.integration
@pytest.mark.p1
def test_checkout_creates_new_branch(app_server) -> None:
    """POST /checkout with create=True creates and switches branch.

    Test flow:
      1. Ensure repo.
      2. POST /checkout {branch, create:True} -> 200 {branch}.
      3. GET /branches; the new branch exists and is current.

    API endpoints:
      - POST /api/workspace/git/checkout
      - GET  /api/workspace/git/branches
    """
    _ensure_repo(app_server)
    branch = "integ-git-feature-E"
    resp = app_server.api_request(
        "POST",
        f"{_GIT}/checkout",
        json={"branch": branch, "create": True},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json()["branch"] == branch
    branches = app_server.api_request(
        "GET",
        f"{_GIT}/branches",
        timeout=_HTTP_TIMEOUT,
    ).json()
    current = [b["name"] for b in branches if b["current"]]
    assert current == [branch], branches


# ================================================================== #
# F — error branches (400) — contract supplements
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p2
def test_commit_empty_message_returns_400(app_server) -> None:
    """POST /commit with a blank message -> 400.

    API endpoints:
      - POST /api/workspace/git/commit
    """
    _ensure_repo(app_server)
    resp = app_server.api_request(
        "POST",
        f"{_GIT}/commit",
        json={"message": "   "},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "empty" in resp.json()["detail"].lower()


@pytest.mark.integration
@pytest.mark.p2
def test_checkout_nonexistent_branch_returns_400(app_server) -> None:
    """POST /checkout to a missing branch (create=False) -> 400.

    API endpoints:
      - POST /api/workspace/git/checkout
    """
    _ensure_repo(app_server)
    resp = app_server.api_request(
        "POST",
        f"{_GIT}/checkout",
        json={"branch": "integ-git-does-not-exist-F", "create": False},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_diff_path_traversal_returns_400(app_server) -> None:
    """GET /diff with a traversal path -> 400 path traversal.

    API endpoints:
      - GET /api/workspace/git/diff
    """
    _ensure_repo(app_server)
    resp = app_server.api_request(
        "GET",
        f"{_GIT}/diff",
        params={"path": "../../etc/passwd"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "traversal" in resp.json()["detail"].lower()


@pytest.mark.integration
@pytest.mark.p2
def test_commit_diff_bad_hash_returns_400(app_server) -> None:
    """GET /commit-diff with an unknown hash -> 400.

    API endpoints:
      - GET /api/workspace/git/commit-diff
    """
    _ensure_repo(app_server)
    resp = app_server.api_request(
        "GET",
        f"{_GIT}/commit-diff",
        params={"commit_hash": "deadbeefdeadbeef"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


# ================================================================== #
# F — discard / revert (scoped to this test's own files)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_discard_removes_untracked_file(app_server) -> None:
    """POST /discard on an explicit path removes that untracked file.

    Test purpose:
      - Cover discard_changes' ``git clean -fd`` arm. The request names
        one file this test created, so nothing else in the shared
        working tree is touched.

    Test flow:
      1. Seed a uniquely named untracked file and see it in /status.
      2. POST /discard with only that path.
      3. Assert the file is gone from disk and from /status.

    API endpoints:
      - GET  /api/workspace/git/status
      - POST /api/workspace/git/discard
    """
    _ensure_repo(app_server)
    name = _seed_file(app_server, "integ-git-discard-untracked.txt")
    assert name in _paths_in_status(_status(app_server))

    resp = app_server.api_request(
        "POST",
        f"{_GIT}/discard",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    assert not (
        _workspace_dir(app_server) / name
    ).exists(), "discard left the untracked file on disk"
    assert name not in _paths_in_status(_status(app_server))


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.xfail(
    strict=False,
    reason=(
        "Product bug Aone #84580657: this test seeds its fixture through "
        "POST /commit, which omits the -c user.email/user.name identity "
        "injection that init-commit and revert use, so on hosts without a "
        "global git identity (CI runners, Docker) it returns 400 "
        "'Author identity unknown'. Remove this marker once the upstream "
        "fix lands."
    ),
)
def test_discard_restores_tracked_modification(app_server) -> None:
    """POST /discard on a tracked file restores its committed content.

    Test purpose:
      - Cover discard_changes' ``git restore`` arm, which is a different
        code path from cleaning an untracked file.

    Test flow:
      1. Seed, stage and commit a file with known content.
      2. Modify it on disk and confirm /status reports the change.
      3. POST /discard for that path and assert the committed content is
         back.

    API endpoints:
      - POST /api/workspace/git/stage
      - POST /api/workspace/git/commit
      - POST /api/workspace/git/discard
    """
    _ensure_repo(app_server)
    name = _seed_file(
        app_server,
        "integ-git-discard-tracked.txt",
        content="committed content\n",
    )
    staged = app_server.api_request(
        "POST",
        f"{_GIT}/stage",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    assert staged.status_code == 200, staged.text
    committed = app_server.api_request(
        "POST",
        f"{_GIT}/commit",
        json={"message": "integ: seed discard-tracked fixture"},
        timeout=_HTTP_TIMEOUT,
    )
    assert committed.status_code == 200, committed.text

    target = _workspace_dir(app_server) / name
    target.write_text("locally modified\n", encoding="utf-8")
    assert name in _paths_in_status(_status(app_server))

    resp = app_server.api_request(
        "POST",
        f"{_GIT}/discard",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    assert (
        target.read_text(encoding="utf-8") == "committed content\n"
    ), "discard did not restore the committed content"


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.xfail(
    strict=False,
    reason=(
        "Product bug Aone #84580657: this test seeds its fixture through "
        "POST /commit, which omits the -c user.email/user.name identity "
        "injection that init-commit and revert use, so on hosts without a "
        "global git identity (CI runners, Docker) it returns 400 "
        "'Author identity unknown'. Remove this marker once the upstream "
        "fix lands."
    ),
)
def test_revert_commit_undoes_its_change(app_server) -> None:
    """POST /revert creates a commit that undoes the named commit.

    Test purpose:
      - Cover revert_commit including its explicit identity injection
        (``-c user.email`` / ``-c user.name``), which is what lets the
        revert commit succeed in an environment with no global git
        identity.

    Test flow:
      1. Commit a new file and capture the commit hash from /log.
      2. POST /revert with that hash.
      3. Assert the file is gone, i.e. the revert really applied.

    API endpoints:
      - POST /api/workspace/git/stage
      - POST /api/workspace/git/commit
      - GET  /api/workspace/git/log
      - POST /api/workspace/git/revert
    """
    _ensure_repo(app_server)
    name = _seed_file(
        app_server,
        "integ-git-revert-target.txt",
        content="added by the commit under test\n",
    )
    app_server.api_request(
        "POST",
        f"{_GIT}/stage",
        json={"paths": [name]},
        timeout=_HTTP_TIMEOUT,
    )
    committed = app_server.api_request(
        "POST",
        f"{_GIT}/commit",
        json={"message": "integ: add revert target"},
        timeout=_HTTP_TIMEOUT,
    )
    assert committed.status_code == 200, committed.text
    assert (_workspace_dir(app_server) / name).exists()

    log_resp = app_server.api_request(
        "GET",
        f"{_GIT}/log",
        params={"limit": 5},
        timeout=_HTTP_TIMEOUT,
    )
    assert log_resp.status_code == 200, log_resp.text
    entries = log_resp.json()
    assert entries, "log returned no commits after a successful commit"
    commit_hash = entries[0]["hash"]

    resp = app_server.api_request(
        "POST",
        f"{_GIT}/revert",
        json={"commit_hash": commit_hash},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reverted"] == commit_hash, resp.json()
    assert not (
        _workspace_dir(app_server) / name
    ).exists(), "revert did not undo the committed file addition"


@pytest.mark.integration
@pytest.mark.p2
def test_revert_bad_hash_returns_400(app_server) -> None:
    """POST /revert with an unknown hash is a 400.

    Test purpose:
      - Cover revert_commit's non-zero-exit branch, which surfaces git's
        stderr rather than raising.

    API endpoints:
      - POST /api/workspace/git/revert
    """
    _ensure_repo(app_server)
    resp = app_server.api_request(
        "POST",
        f"{_GIT}/revert",
        json={"commit_hash": "0000000000000000000000000000000000000000"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
