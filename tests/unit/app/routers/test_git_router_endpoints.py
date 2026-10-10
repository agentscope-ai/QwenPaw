# -*- coding: utf-8 -*-
"""Endpoint tests for the workspace git router using real temp repos.

Covers status (with auto-init), branches, checkout, diff (staged /
unstaged / untracked --no-index), stage/unstage, commit (including the
empty-message guard), discard (restore + clean semantics), commit-diff,
revert, and log against real temporary git repositories.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import git as git_module
from qwenpaw.app.routers.git import router as git_router


def _git_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _make_repo(path: Path) -> Path:
    """Initialise a git repo with identity and one commit."""
    path.mkdir(parents=True, exist_ok=True)
    _git_cli(path, "init", "-b", "main")
    _git_cli(path, "config", "user.email", "test@example.com")
    _git_cli(path, "config", "user.name", "Test")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git_cli(path, "add", ".")
    _git_cli(path, "commit", "-m", "seed commit")
    return path


@pytest.fixture
def repo_client(tmp_path, monkeypatch):
    """TestClient bound to a real temp git repo."""
    project = _make_repo(tmp_path / "project")

    async def fake_agent(_request):
        from types import SimpleNamespace

        return SimpleNamespace(agent_id="git-test", workspace_dir=project)

    async def fake_project_dir(_request, _workspace):
        return project

    monkeypatch.setattr(git_module, "get_agent_for_request", fake_agent)
    monkeypatch.setattr(
        git_module,
        "get_project_dir_for_request",
        fake_project_dir,
    )
    app = FastAPI()
    app.include_router(git_router, prefix="/api")
    return TestClient(app), project


class TestGitStatus:
    def test_clean_repo_reports_branch(self, repo_client):
        client, _project = repo_client
        response = client.get("/api/workspace/git/status")
        assert response.status_code == 200
        body = response.json()
        assert body["branch"] == "main"
        assert body["changes"] == []

    def test_modified_file_reported(self, repo_client):
        client, project = repo_client
        (project / "seed.txt").write_text("changed\n", encoding="utf-8")
        body = client.get("/api/workspace/git/status").json()
        names = {change["path"] for change in body["changes"]}
        assert "seed.txt" in names

    def test_untracked_directory_collapsed(self, repo_client):
        client, project = repo_client
        nested = project / "newdir" / "inner"
        nested.mkdir(parents=True)
        (nested / "file.txt").write_text("x", encoding="utf-8")
        body = client.get("/api/workspace/git/status").json()
        names = {change["path"] for change in body["changes"]}
        # git reports untracked dirs as "newdir/"; the router strips the
        # trailing slash, collapsing the whole dir into one entry.
        assert "newdir" in names


class TestListBranches:
    def test_lists_current_branch(self, repo_client):
        client, _project = repo_client
        response = client.get("/api/workspace/git/branches")
        assert response.status_code == 200
        branches = response.json()
        main = next(b for b in branches if b["name"] == "main")
        assert main["current"] is True
        assert main["remote"] is False

    def test_created_branch_listed(self, repo_client):
        client, project = repo_client
        _git_cli(project, "branch", "feature")
        names = [
            b["name"] for b in client.get("/api/workspace/git/branches").json()
        ]
        assert "feature" in names


class TestCheckout:
    def test_checkout_existing_branch(self, repo_client):
        client, project = repo_client
        _git_cli(project, "branch", "feature")
        response = client.post(
            "/api/workspace/git/checkout",
            json={"branch": "feature"},
        )
        assert response.status_code == 200
        assert response.json() == {"branch": "feature"}
        _r = _git_cli(project, "rev-parse", "--abbrev-ref", "HEAD")
        rc, out = _r.returncode, _r.stdout
        assert rc == 0
        assert out.strip() == "feature"

    def test_checkout_create_branch(self, repo_client):
        client, project = repo_client
        response = client.post(
            "/api/workspace/git/checkout",
            json={"branch": "brand-new", "create": True},
        )
        assert response.status_code == 200
        _r = _git_cli(project, "rev-parse", "--abbrev-ref", "HEAD")
        out = _r.stdout
        assert out.strip() == "brand-new"

    def test_checkout_missing_branch_returns_400(self, repo_client):
        client, _ = repo_client
        response = client.post(
            "/api/workspace/git/checkout",
            json={"branch": "ghost"},
        )
        assert response.status_code == 400


class TestDiff:
    def test_unstaged_diff(self, repo_client):
        client, project = repo_client
        (project / "seed.txt").write_text("modified\n", encoding="utf-8")
        response = client.get("/api/workspace/git/diff")
        assert response.status_code == 200
        assert "modified" in response.json()["diff"]

    def test_staged_diff(self, repo_client):
        client, project = repo_client
        (project / "seed.txt").write_text("staged change\n", encoding="utf-8")
        _git_cli(project, "add", "seed.txt")
        response = client.get(
            "/api/workspace/git/diff",
            params={"staged": True},
        )
        assert "staged change" in response.json()["diff"]

    def test_path_scoped_diff(self, repo_client):
        client, project = repo_client
        (project / "seed.txt").write_text("a\n", encoding="utf-8")
        (project / "other.txt").write_text("b\n", encoding="utf-8")
        _git_cli(project, "add", "other.txt")
        response = client.get(
            "/api/workspace/git/diff",
            params={"path": "other.txt", "staged": True},
        )
        assert response.status_code == 200

    def test_untracked_diff_uses_no_index(self, repo_client):
        client, project = repo_client
        (project / "fresh.txt").write_text("brand new\n", encoding="utf-8")
        response = client.get(
            "/api/workspace/git/diff",
            params={"path": "fresh.txt", "untracked": True},
        )
        assert response.status_code == 200
        assert "brand new" in response.json()["diff"]


class TestStageUnstage:
    def test_stage_specific_file(self, repo_client):
        client, project = repo_client
        (project / "new.txt").write_text("x", encoding="utf-8")
        response = client.post(
            "/api/workspace/git/stage",
            json={"paths": ["new.txt"]},
        )
        assert response.status_code == 200
        assert response.json() == {"staged": ["new.txt"]}
        _r = _git_cli(project, "diff", "--cached", "--name-only")
        out = _r.stdout
        assert "new.txt" in out

    def test_stage_all_when_empty_paths(self, repo_client):
        client, project = repo_client
        (project / "one.txt").write_text("1", encoding="utf-8")
        (project / "two.txt").write_text("2", encoding="utf-8")
        response = client.post("/api/workspace/git/stage", json={"paths": []})
        assert response.status_code == 200
        _r = _git_cli(project, "diff", "--cached", "--name-only")
        out = _r.stdout
        assert "one.txt" in out
        assert "two.txt" in out

    def test_unstage(self, repo_client):
        client, project = repo_client
        (project / "new.txt").write_text("x", encoding="utf-8")
        _git_cli(project, "add", "new.txt")
        response = client.post(
            "/api/workspace/git/unstage",
            json={"paths": ["new.txt"]},
        )
        assert response.status_code == 200
        _r = _git_cli(project, "diff", "--cached", "--name-only")
        out = _r.stdout
        assert out.strip() == ""

    def test_stage_nonexistent_returns_400(self, repo_client):
        client, _ = repo_client
        response = client.post(
            "/api/workspace/git/stage",
            json={"paths": ["nope/missing.txt"]},
        )
        assert response.status_code == 400


class TestCommit:
    def test_commit_staged_changes(self, repo_client):
        client, project = repo_client
        (project / "new.txt").write_text("x", encoding="utf-8")
        client.post("/api/workspace/git/stage", json={"paths": ["new.txt"]})
        response = client.post(
            "/api/workspace/git/commit",
            json={"message": "add new.txt"},
        )
        assert response.status_code == 200
        assert response.json()["committed"] is True
        _r = _git_cli(project, "log", "-1", "--format=%s")
        out = _r.stdout
        assert out.strip() == "add new.txt"

    def test_empty_message_returns_400(self, repo_client):
        client, _ = repo_client
        response = client.post(
            "/api/workspace/git/commit",
            json={"message": "   "},
        )
        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"]

    def test_commit_without_staged_returns_400(self, repo_client):
        client, _ = repo_client
        response = client.post(
            "/api/workspace/git/commit",
            json={"message": "nothing staged"},
        )
        assert response.status_code == 400


class TestDiscard:
    def test_discard_modified_tracked_file(self, repo_client):
        client, project = repo_client
        (project / "seed.txt").write_text("oops\n", encoding="utf-8")
        response = client.post(
            "/api/workspace/git/discard",
            json={"paths": []},
        )
        assert response.status_code == 200
        assert (project / "seed.txt").read_text(encoding="utf-8") == "seed\n"

    def test_discard_untracked_file(self, repo_client):
        client, project = repo_client
        stray = project / "stray.txt"
        stray.write_text("junk", encoding="utf-8")
        response = client.post(
            "/api/workspace/git/discard",
            json={"paths": []},
        )
        assert response.status_code == 200
        assert not stray.exists()

    def test_discard_specific_path(self, repo_client):
        client, project = repo_client
        (project / "seed.txt").write_text("oops\n", encoding="utf-8")
        response = client.post(
            "/api/workspace/git/discard",
            json={"paths": ["seed.txt"]},
        )
        assert response.status_code == 200
        assert (project / "seed.txt").read_text(encoding="utf-8") == "seed\n"


class TestCommitDiffAndRevert:
    def test_commit_diff_shows_patch(self, repo_client):
        client, project = repo_client
        _r = _git_cli(project, "rev-parse", "HEAD")
        out = _r.stdout
        head = out.strip()
        response = client.get(
            "/api/workspace/git/commit-diff",
            params={"commit_hash": head},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["hash"] == head
        assert "seed.txt" in body["diff"]

    def test_commit_diff_bad_hash_returns_400(self, repo_client):
        client, _ = repo_client
        response = client.get(
            "/api/workspace/git/commit-diff",
            params={"commit_hash": "deadbeef"},
        )
        assert response.status_code == 400

    def test_revert_creates_reversing_commit(self, repo_client):
        client, project = repo_client
        (project / "add.txt").write_text("added\n", encoding="utf-8")
        _git_cli(project, "add", "add.txt")
        _git_cli(project, "commit", "-m", "add file")
        _r = _git_cli(project, "rev-parse", "HEAD")
        out = _r.stdout
        head = out.strip()
        response = client.post(
            "/api/workspace/git/revert",
            json={"commit_hash": head},
        )
        assert response.status_code == 200
        assert response.json()["reverted"] == head
        assert not (project / "add.txt").exists()

    def test_revert_bad_hash_returns_400(self, repo_client):
        client, _ = repo_client
        response = client.post(
            "/api/workspace/git/revert",
            json={"commit_hash": "deadbeef"},
        )
        assert response.status_code == 400


class TestLog:
    def test_log_lists_commits_newest_first(self, repo_client):
        client, project = repo_client
        (project / "a.txt").write_text("a", encoding="utf-8")
        _git_cli(project, "add", "a.txt")
        _git_cli(project, "commit", "-m", "second commit")
        response = client.get("/api/workspace/git/log")
        assert response.status_code == 200
        entries = response.json()
        assert len(entries) >= 2
        assert entries[0]["message"] == "second commit"
        assert entries[-1]["message"] == "seed commit"

    def test_log_limit_respected(self, repo_client):
        client, project = repo_client
        (project / "a.txt").write_text("a", encoding="utf-8")
        _git_cli(project, "add", "a.txt")
        _git_cli(project, "commit", "-m", "second")
        response = client.get("/api/workspace/git/log", params={"limit": 1})
        assert len(response.json()) == 1
