# -*- coding: utf-8 -*-
"""Endpoint-level tests for project directory import, upload, and browse.

Complements the helper-focused tests in ``test_project_directory.py`` by
exercising the router endpoints: GET default project, POST /create,
POST /import-local (build-artifact exclusion + sensitive-entry
filtering + home boundary), POST /upload-zip (zip-slip guard), GET
/browse-dirs, and POST /clone (SSE progress stream).
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import project_directory as pd
from qwenpaw.app.routers.project_directory import router as pd_router


@pytest.fixture
def workspace_dirs(tmp_path):
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    return workspace_dir


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def client(workspace_dirs, monkeypatch):
    async def get_workspace(_request):
        return SimpleNamespace(
            agent_id="pd-test",
            workspace_dir=workspace_dirs,
        )

    monkeypatch.setattr(pd, "get_agent_for_request", get_workspace)
    monkeypatch.setattr(
        pd,
        "get_agent_project_dir",
        lambda _workspace: workspace_dirs,
    )

    app = FastAPI()
    app.include_router(pd_router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def mock_save_project_dir(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    def _save(agent_id, project_dir):
        calls.append((agent_id, project_dir))

    monkeypatch.setattr(pd, "_save_project_dir", _save)
    return calls


def _sse_events(response) -> list[dict]:
    events = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


# ---------------------------------------------------------------------------
# GET /workspace/project-directory
# ---------------------------------------------------------------------------


class TestGetProject:
    def test_returns_workspace_default(self, client, workspace_dirs):
        response = client.get("/api/workspace/project-directory")
        assert response.status_code == 200
        body = response.json()
        assert body["path"] == str(workspace_dirs)
        assert body["is_workspace_default"] is True
        assert body["workspace_dir"] == str(workspace_dirs)
        assert body["exists"] is True

    def test_custom_project_dir_flagged(self, client, workspace_dirs):
        custom = workspace_dirs / "coding_projects" / "demo"
        custom.mkdir(parents=True)
        with patch.object(
            pd,
            "get_agent_project_dir",
            lambda _workspace: custom,
        ):
            response = client.get("/api/workspace/project-directory")
        body = response.json()
        assert body["path"] == str(custom)
        assert body["is_workspace_default"] is False
        assert body["name"] == "demo"


# ---------------------------------------------------------------------------
# POST /workspace/project-directory/create
# ---------------------------------------------------------------------------


class TestCreateProject:
    def test_empty_name_returns_400(self, client):
        response = client.post(
            "/api/workspace/project-directory/create",
            json={"name": "   "},
        )
        assert response.status_code == 400

    def test_creates_dir_and_sets_active(
        self,
        client,
        workspace_dirs,
        mock_save_project_dir,
        monkeypatch,
    ):
        async def fake_run(cmd, cwd=None, check=False, timeout=None):
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(pd, "run_command_async", fake_run)
        response = client.post(
            "/api/workspace/project-directory/create",
            json={"name": "fresh"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "fresh"
        created = Path(body["path"])
        assert created.is_dir()
        assert created == (workspace_dirs / "coding_projects" / "fresh")
        assert mock_save_project_dir == [("pd-test", str(created))]

    def test_traversal_name_returns_400(self, client):
        response = client.post(
            "/api/workspace/project-directory/create",
            json={"name": "../escape"},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /workspace/project-directory/import-local
# ---------------------------------------------------------------------------


def _build_source(home: Path) -> Path:
    source = home / "projects" / "demo"
    (source / "src").mkdir(parents=True)
    (source / "src" / "app.py").write_text("x", encoding="utf-8")
    (source / "README.md").write_text("hi", encoding="utf-8")
    # Build artifacts that must not be copied.
    (source / "node_modules").mkdir()
    (source / "node_modules" / "dep.js").write_text("x", encoding="utf-8")
    (source / "__pycache__").mkdir()
    # Sensitive entries that must not be copied.
    (source / ".env").write_text("SECRET=x", encoding="utf-8")
    (source / ".ssh").mkdir()
    (source / ".ssh" / "id_rsa").write_text("key", encoding="utf-8")
    return source


class TestImportLocal:
    def test_missing_path_returns_400(self, client, fake_home):
        response = client.post(
            "/api/workspace/project-directory/import-local",
            json={"path": str(fake_home / "nope")},
        )
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"]

    def test_file_source_returns_400(self, client, fake_home):
        afile = fake_home / "file.txt"
        afile.write_text("x", encoding="utf-8")
        response = client.post(
            "/api/workspace/project-directory/import-local",
            json={"path": str(afile)},
        )
        assert response.status_code == 400
        assert "Not a directory" in response.json()["detail"]

    def test_source_outside_home_returns_403(
        self,
        client,
        fake_home,
        tmp_path,
    ):
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        response = client.post(
            "/api/workspace/project-directory/import-local",
            json={"path": str(outside)},
        )
        assert response.status_code == 403
        assert "home directory" in response.json()["detail"]

    def test_home_itself_returns_403(self, client, fake_home):
        response = client.post(
            "/api/workspace/project-directory/import-local",
            json={"path": str(fake_home)},
        )
        assert response.status_code == 403
        assert "entire home directory" in response.json()["detail"]

    def test_sensitive_source_component_returns_403(self, client, fake_home):
        sensitive = fake_home / ".ssh"
        sensitive.mkdir()
        response = client.post(
            "/api/workspace/project-directory/import-local",
            json={"path": str(sensitive)},
        )
        assert response.status_code == 403

    def test_copies_without_artifacts_or_sensitive_entries(
        self,
        client,
        fake_home,
        workspace_dirs,
        mock_save_project_dir,
    ):
        source = _build_source(fake_home)
        response = client.post(
            "/api/workspace/project-directory/import-local",
            json={"path": str(source), "name": "imported"},
        )
        assert response.status_code == 200
        body = response.json()
        dest = Path(body["path"])
        assert dest == workspace_dirs / "coding_projects" / "imported"
        assert (dest / "README.md").exists()
        assert (dest / "src" / "app.py").exists()
        # Build artifacts excluded.
        assert not (dest / "node_modules").exists()
        assert not (dest / "__pycache__").exists()
        # Sensitive entries excluded and reported.
        assert not (dest / ".env").exists()
        assert not (dest / ".ssh").exists()
        assert ".env" in body["excluded"]
        assert ".ssh" in body["excluded"]
        assert mock_save_project_dir == [("pd-test", str(dest))]

    def test_default_name_is_source_basename(
        self,
        client,
        fake_home,
        workspace_dirs,
        mock_save_project_dir,
    ):
        source = _build_source(fake_home)
        response = client.post(
            "/api/workspace/project-directory/import-local",
            json={"path": str(source)},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "demo"


# ---------------------------------------------------------------------------
# POST /workspace/project-directory/upload-zip
# ---------------------------------------------------------------------------


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


class TestUploadZip:
    def test_extracts_and_activates(
        self,
        client,
        workspace_dirs,
        mock_save_project_dir,
        monkeypatch,
    ):
        async def fake_resolve_branch(cwd):
            return "main", False

        monkeypatch.setattr(
            "qwenpaw.app.routers.git._resolve_branch",
            fake_resolve_branch,
        )
        data = _zip_bytes({"README.md": "hi", "src/app.py": "x"})
        response = client.post(
            "/api/workspace/project-directory/upload-zip?name=zipped",
            files={
                "file": ("proj.zip", data, "application/zip"),
            },
        )
        assert response.status_code == 200
        body = response.json()
        dest = Path(body["path"])
        assert dest == workspace_dirs / "coding_projects" / "zipped"
        assert (dest / "README.md").read_text(encoding="utf-8") == "hi"
        assert (dest / "src" / "app.py").exists()
        assert mock_save_project_dir == [("pd-test", str(dest))]

    def test_zip_slip_member_returns_400(self, client):
        data = _zip_bytes({"../escape.txt": "evil"})
        response = client.post(
            "/api/workspace/project-directory/upload-zip?name=slip",
            files={"file": ("proj.zip", data, "application/zip")},
        )
        assert response.status_code == 400
        assert "Zip slip" in response.json()["detail"]

    def test_absolute_member_returns_400(self, client):
        # The guard is ``Path(member).is_absolute()``, and on Windows a
        # leading slash is *not* absolute (no drive), so "/etc/passwd"
        # there falls through to the zip-slip check instead.  Use a
        # drive-qualified member on Windows so this test exercises the
        # absolute-path branch on every runner rather than silently
        # turning into a duplicate of the zip-slip test above.
        member = (
            "C:/Windows/evil.txt" if sys.platform == "win32" else "/etc/passwd"
        )
        data = _zip_bytes({member: "evil"})
        response = client.post(
            "/api/workspace/project-directory/upload-zip?name=abs",
            files={"file": ("proj.zip", data, "application/zip")},
        )
        assert response.status_code == 400
        assert "Absolute path" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /workspace/project-directory/browse-dirs
# ---------------------------------------------------------------------------


class TestBrowseDirs:
    def test_lists_only_directories(self, client, tmp_path):
        target = tmp_path / "browse"
        target.mkdir()
        (target / "sub1").mkdir()
        (target / "sub2").mkdir()
        (target / "file.txt").write_text("x", encoding="utf-8")
        response = client.get(
            "/api/workspace/project-directory/browse-dirs",
            params={"path": str(target)},
        )
        assert response.status_code == 200
        body = response.json()
        names = {entry["name"] for entry in body["dirs"]}
        assert names == {"sub1", "sub2"}
        assert body["current"] == str(target.resolve())
        assert body["parent"] == str(target.resolve().parent)

    def test_hidden_dirs_filtered_by_default(self, client, tmp_path):
        target = tmp_path / "browse2"
        target.mkdir()
        (target / ".hidden").mkdir()
        (target / "visible").mkdir()
        response = client.get(
            "/api/workspace/project-directory/browse-dirs",
            params={"path": str(target)},
        )
        names = {entry["name"] for entry in response.json()["dirs"]}
        assert names == {"visible"}

    def test_show_hidden_includes_dot_dirs(self, client, tmp_path):
        target = tmp_path / "browse3"
        target.mkdir()
        (target / ".hidden").mkdir()
        response = client.get(
            "/api/workspace/project-directory/browse-dirs",
            params={"path": str(target), "show_hidden": True},
        )
        names = {entry["name"] for entry in response.json()["dirs"]}
        assert names == {".hidden"}

    def test_missing_path_returns_400(self, client, tmp_path):
        response = client.get(
            "/api/workspace/project-directory/browse-dirs",
            params={"path": str(tmp_path / "nope")},
        )
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"]

    def test_file_path_returns_400(self, client, tmp_path):
        afile = tmp_path / "plain.txt"
        afile.write_text("x", encoding="utf-8")
        response = client.get(
            "/api/workspace/project-directory/browse-dirs",
            params={"path": str(afile)},
        )
        assert response.status_code == 400
        assert "Not a directory" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /workspace/project-directory/clone (SSE)
# ---------------------------------------------------------------------------


class _FakeStdout:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)

    async def read(self, size):
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class _FakeProc:
    def __init__(self, chunks: list[bytes], returncode: int):
        self.stdout = _FakeStdout(chunks)
        self._rc = returncode

    async def wait(self):
        return self._rc


class TestCloneProject:
    def test_empty_url_returns_400(self, client):
        response = client.post(
            "/api/workspace/project-directory/clone",
            json={"url": "   "},
        )
        assert response.status_code == 400

    def test_unnameable_url_returns_400(self, client):
        # The last URL segment is ".git" alone: stripping the suffix
        # leaves an empty repo name.
        response = client.post(
            "/api/workspace/project-directory/clone",
            json={"url": "https://git.example.com/.git"},
        )
        assert response.status_code == 400
        assert "Cannot derive repo name" in response.json()["detail"]

    def test_successful_clone_streams_done(
        self,
        client,
        workspace_dirs,
        mock_save_project_dir,
        monkeypatch,
    ):
        async def fake_start(cmd, stdout=None, stderr=None):
            assert cmd[:2] == ["git", "clone"]
            return _FakeProc([b"Cloning into...\r\nDone.\n"], 0)

        monkeypatch.setattr(pd, "start_command_async", fake_start)
        response = client.post(
            "/api/workspace/project-directory/clone",
            json={"url": "https://github.com/org/repo.git"},
        )
        assert response.status_code == 200
        events = _sse_events(response)
        kinds = [event["type"] for event in events]
        assert "log" in kinds
        assert kinds[-1] == "done"
        done = events[-1]
        assert done["name"] == "repo"
        assert done["path"] == str(
            workspace_dirs / "coding_projects" / "repo",
        )
        assert mock_save_project_dir == [("pd-test", done["path"])]

    def test_failed_clone_streams_error(
        self,
        client,
        mock_save_project_dir,
        monkeypatch,
    ):
        async def fake_start(cmd, stdout=None, stderr=None):
            return _FakeProc([b"fatal: repo not found\n"], 128)

        monkeypatch.setattr(pd, "start_command_async", fake_start)
        response = client.post(
            "/api/workspace/project-directory/clone",
            json={"url": "https://github.com/org/missing"},
        )
        events = _sse_events(response)
        assert events[-1]["type"] == "error"
        assert "exited with code 128" in events[-1]["detail"]
        assert mock_save_project_dir == []

    def test_explicit_name_overrides_url_basename(
        self,
        client,
        workspace_dirs,
        mock_save_project_dir,
        monkeypatch,
    ):
        async def fake_start(cmd, stdout=None, stderr=None):
            return _FakeProc([b"ok\n"], 0)

        monkeypatch.setattr(pd, "start_command_async", fake_start)
        response = client.post(
            "/api/workspace/project-directory/clone",
            json={
                "url": "https://github.com/org/repo.git",
                "name": "custom-name",
            },
        )
        events = _sse_events(response)
        assert events[-1]["type"] == "done"
        assert events[-1]["name"] == "custom-name"
