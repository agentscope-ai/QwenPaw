# -*- coding: utf-8 -*-
"""Unit tests for workspace router file-reading and upload helpers.

Covers the endpoints and helpers the existing workspace test files do
not exercise: ``GET /workspace/code-files`` (ETag short-circuit, size
cap), ``GET /workspace/binary-files`` (MIME gating, size cap),
``GET /workspace/html-file-uri`` (HTML-only resolution), the recursive
``_list_all_files`` walker with skip pruning, the merge-style zip
extractor, and ``POST /workspace/transcribe`` guards.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import workspace as workspace_router


@pytest.fixture(name="ws_client")
def fixture_ws_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    project_dir = tmp_path / "project"
    workspace_dir = tmp_path / "workspace"
    project_dir.mkdir()
    workspace_dir.mkdir()

    async def get_workspace(_request):
        return SimpleNamespace(
            agent_id="ws-test",
            workspace_dir=workspace_dir,
        )

    async def get_project_dir(_request, _workspace):
        return project_dir

    monkeypatch.setattr(
        workspace_router,
        "get_agent_for_request",
        get_workspace,
    )
    monkeypatch.setattr(
        workspace_router,
        "get_project_dir_for_request",
        get_project_dir,
    )
    monkeypatch.setattr(
        workspace_router,
        "get_agent_project_dir",
        lambda _workspace: project_dir,
    )
    app = FastAPI()
    app.state.project_dir = project_dir
    app.state.workspace_dir = workspace_dir
    app.include_router(workspace_router.router, prefix="/api")
    return TestClient(app)


def _project(ws_client: TestClient) -> Path:
    return ws_client.app.state.project_dir


def _workspace(ws_client: TestClient) -> Path:
    return ws_client.app.state.workspace_dir


# ---------------------------------------------------------------------------
# GET /workspace/code-files/{path}
# ---------------------------------------------------------------------------


class TestReadCodeFile:
    def test_reads_text_with_etag(self, ws_client):
        (_project(ws_client) / "app.py").write_text(
            "print('ok')",
            encoding="utf-8",
        )
        response = ws_client.get("/api/workspace/code-files/app.py")
        assert response.status_code == 200
        body = response.json()
        assert body["path"] == "app.py"
        assert body["content"] == "print('ok')"
        assert response.headers["ETag"].startswith('W/"')

    def test_matching_etag_short_circuits_to_304(self, ws_client):
        (_project(ws_client) / "app.py").write_text("x", encoding="utf-8")
        first = ws_client.get("/api/workspace/code-files/app.py")
        etag = first.headers["ETag"]
        second = ws_client.get(
            "/api/workspace/code-files/app.py",
            headers={"if-none-match": etag},
        )
        assert second.status_code == 304
        assert second.headers["ETag"] == etag

    def test_changed_file_ignores_stale_etag(self, ws_client):
        target = _project(ws_client) / "app.py"
        target.write_text("v1", encoding="utf-8")
        stale = ws_client.get("/api/workspace/code-files/app.py").headers[
            "ETag"
        ]
        target.write_text("v2 content", encoding="utf-8")
        response = ws_client.get(
            "/api/workspace/code-files/app.py",
            headers={"if-none-match": stale},
        )
        assert response.status_code == 200
        assert response.json()["content"] == "v2 content"

    def test_missing_file_returns_404(self, ws_client):
        response = ws_client.get("/api/workspace/code-files/ghost.py")
        assert response.status_code == 404

    def test_directory_returns_404(self, ws_client):
        (_project(ws_client) / "subdir").mkdir()
        response = ws_client.get("/api/workspace/code-files/subdir")
        assert response.status_code == 404

    def test_oversized_file_returns_413(self, ws_client):
        big = _project(ws_client) / "big.log"
        with open(big, "wb") as fh:
            fh.seek(workspace_router._CODE_FILE_MAX_BYTES)
            fh.write(b"x")  # sparse file, one byte past the cap
        response = ws_client.get("/api/workspace/code-files/big.log")
        assert response.status_code == 413

    def test_invalid_utf8_is_replaced_not_raised(self, ws_client):
        (_project(ws_client) / "raw.txt").write_bytes(b"ok\xff\xfe")
        response = ws_client.get("/api/workspace/code-files/raw.txt")
        assert response.status_code == 200
        assert "\ufffd" in response.json()["content"]


# ---------------------------------------------------------------------------
# GET /workspace/binary-files/{path}
# ---------------------------------------------------------------------------


class TestReadBinaryFile:
    def test_streams_png_with_content_type(self, ws_client):
        (_project(ws_client) / "logo.png").write_bytes(
            b"\x89PNG fake image",
        )
        response = ws_client.get("/api/workspace/binary-files/logo.png")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == b"\x89PNG fake image"

    def test_pdf_gets_application_pdf(self, ws_client):
        (_project(ws_client) / "doc.pdf").write_bytes(b"%PDF-1.4")
        response = ws_client.get("/api/workspace/binary-files/doc.pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

    def test_unsupported_extension_returns_415(self, ws_client):
        (_project(ws_client) / "app.exe").write_bytes(b"MZ")
        response = ws_client.get("/api/workspace/binary-files/app.exe")
        assert response.status_code == 415

    def test_missing_file_returns_404(self, ws_client):
        response = ws_client.get("/api/workspace/binary-files/ghost.png")
        assert response.status_code == 404

    def test_oversized_file_returns_413(self, ws_client):
        big = _project(ws_client) / "big.png"
        with open(big, "wb") as fh:
            fh.seek(workspace_router._BINARY_FILE_MAX_BYTES)
            fh.write(b"x")  # sparse file, one byte past the cap
        response = ws_client.get("/api/workspace/binary-files/big.png")
        assert response.status_code == 413


# ---------------------------------------------------------------------------
# GET /workspace/html-file-uri
# ---------------------------------------------------------------------------


class TestResolveHtmlFileUri:
    def test_html_file_resolves_to_uri(self, ws_client):
        (_project(ws_client) / "page.html").write_text(
            "<html></html>",
            encoding="utf-8",
        )
        response = ws_client.get(
            "/api/workspace/html-file-uri",
            params={"path": "page.html"},
        )
        assert response.status_code == 200
        uri = response.json()["uri"]
        assert uri.startswith("file://")
        assert uri.endswith("page.html")

    def test_htm_extension_accepted(self, ws_client):
        (_project(ws_client) / "legacy.htm").write_text(
            "<b>",
            encoding="utf-8",
        )
        response = ws_client.get(
            "/api/workspace/html-file-uri",
            params={"path": "legacy.htm"},
        )
        assert response.status_code == 200

    def test_non_html_path_returns_400(self, ws_client):
        (_project(ws_client) / "style.css").write_text("a{}", encoding="utf-8")
        response = ws_client.get(
            "/api/workspace/html-file-uri",
            params={"path": "style.css"},
        )
        assert response.status_code == 400
        assert "HTML" in response.json()["detail"]

    def test_missing_file_returns_404(self, ws_client):
        response = ws_client.get(
            "/api/workspace/html-file-uri",
            params={"path": "ghost.html"},
        )
        assert response.status_code == 404

    def test_invalid_root_returns_400(self, ws_client):
        response = ws_client.get(
            "/api/workspace/html-file-uri",
            params={"path": "page.html", "root": "somewhere"},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# _list_all_files
# ---------------------------------------------------------------------------


class TestListAllFiles:
    def test_lists_files_recursively_with_posix_paths(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("x", encoding="utf-8")
        (tmp_path / "README.md").write_text("hi", encoding="utf-8")
        files = workspace_router._list_all_files(tmp_path)
        names = {item["path"] for item in files}
        assert names == {"README.md", "src/app.py"}
        for item in files:
            assert "\\" not in item["path"]
            assert item["size"] >= 0
            assert item["modified_time"]

    def test_hidden_and_vendor_dirs_pruned(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "lib.js").write_text(
            "x",
            encoding="utf-8",
        )
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".hidden_file").write_text("x", encoding="utf-8")
        (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
        files = workspace_router._list_all_files(tmp_path)
        names = {item["path"] for item in files}
        assert names == {"keep.txt"}

    def test_missing_root_returns_empty(self, tmp_path):
        assert workspace_router._list_all_files(tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# _extract_and_merge_zip
# ---------------------------------------------------------------------------


def _zip_with_entries(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


class TestExtractAndMergeZip:
    def test_single_top_level_dir_is_unwrapped(self, tmp_path):
        data = _zip_with_entries(
            {
                "bundle/SKILL.md": "# skill",
                "bundle/scripts/run.sh": "echo hi",
            },
        )
        workspace_router._extract_and_merge_zip(data, tmp_path / "ws")
        assert (tmp_path / "ws" / "SKILL.md").read_text(encoding="utf-8") == (
            "# skill"
        )
        assert (tmp_path / "ws" / "scripts" / "run.sh").exists()

    def test_multiple_top_level_entries_extracted_as_is(self, tmp_path):
        data = _zip_with_entries(
            {"a.txt": "A", "b/c.txt": "C"},
        )
        workspace_router._extract_and_merge_zip(data, tmp_path / "ws")
        assert (tmp_path / "ws" / "a.txt").read_text(encoding="utf-8") == "A"
        assert (tmp_path / "ws" / "b" / "c.txt").read_text(
            encoding="utf-8",
        ) == "C"

    def test_existing_file_replaced_and_dir_merged(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "old.txt").write_text("old", encoding="utf-8")
        (workspace / "scripts").mkdir()
        (workspace / "scripts" / "keep.sh").write_text(
            "keep",
            encoding="utf-8",
        )
        data = _zip_with_entries(
            {
                "old.txt": "new",
                "scripts/added.sh": "added",
            },
        )
        workspace_router._extract_and_merge_zip(data, workspace)
        assert (workspace / "old.txt").read_text(encoding="utf-8") == "new"
        assert (workspace / "scripts" / "keep.sh").exists()
        assert (workspace / "scripts" / "added.sh").exists()

    def test_no_temp_dir_left_behind(self, tmp_path, monkeypatch):
        import tempfile as _tempfile

        created: list[str] = []
        original_mkdtemp = _tempfile.mkdtemp

        def tracking_mkdtemp(*args, **kwargs):
            result = original_mkdtemp(*args, **kwargs)
            created.append(result)
            return result

        monkeypatch.setattr(_tempfile, "mkdtemp", tracking_mkdtemp)
        data = _zip_with_entries({"a.txt": "A"})
        workspace_router._extract_and_merge_zip(data, tmp_path / "ws")
        assert created
        assert not any(Path(entry).exists() for entry in created)


# ---------------------------------------------------------------------------
# POST /workspace/transcribe
# ---------------------------------------------------------------------------


class TestTranscribeAudio:
    def _disabled_config(self):
        config = SimpleNamespace(
            agents=SimpleNamespace(transcription_provider_type="disabled"),
        )
        return config

    def _enabled_config(self):
        config = SimpleNamespace(
            agents=SimpleNamespace(
                transcription_provider_type="whisper_api",
            ),
        )
        return config

    def test_disabled_provider_returns_400(self, ws_client, monkeypatch):
        monkeypatch.setattr(
            workspace_router,
            "load_config",
            self._disabled_config,
        )
        response = ws_client.post(
            "/api/workspace/transcribe",
            files={"file": ("voice.wav", b"RIFF fake", "audio/wav")},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "TRANSCRIPTION_DISABLED"

    def test_unsupported_extension_returns_400(self, ws_client, monkeypatch):
        monkeypatch.setattr(
            workspace_router,
            "load_config",
            self._enabled_config,
        )
        response = ws_client.post(
            "/api/workspace/transcribe",
            files={"file": ("notes.txt", b"text", "text/plain")},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "UNSUPPORTED_FILE_TYPE"

    def test_successful_transcription(self, ws_client, monkeypatch):
        monkeypatch.setattr(
            workspace_router,
            "load_config",
            self._enabled_config,
        )

        async def fake_transcribe(path):
            assert path.endswith(".wav")
            return "hello world"

        monkeypatch.setattr(
            "qwenpaw.agents.utils.audio_transcription.transcribe_audio",
            fake_transcribe,
        )
        response = ws_client.post(
            "/api/workspace/transcribe",
            files={"file": ("voice.wav", b"RIFF fake", "audio/wav")},
        )
        assert response.status_code == 200
        assert response.json() == {"text": "hello world"}

    def test_provider_failure_returns_500(self, ws_client, monkeypatch):
        monkeypatch.setattr(
            workspace_router,
            "load_config",
            self._enabled_config,
        )

        async def failing_transcribe(path):
            return None

        monkeypatch.setattr(
            "qwenpaw.agents.utils.audio_transcription.transcribe_audio",
            failing_transcribe,
        )
        response = ws_client.post(
            "/api/workspace/transcribe",
            files={"file": ("voice.mp3", b"ID3 fake", "audio/mpeg")},
        )
        assert response.status_code == 500

    def test_missing_filename_defaults_to_webm(self, monkeypatch):
        """Filename fallback is exercised directly (API rejects no-file)."""
        from fastapi import UploadFile

        captured: list[str] = []

        async def fake_transcribe(path):
            captured.append(path)
            return "ok"

        monkeypatch.setattr(
            "qwenpaw.agents.utils.audio_transcription.transcribe_audio",
            fake_transcribe,
        )
        monkeypatch.setattr(
            workspace_router,
            "load_config",
            self._enabled_config,
        )
        upload = UploadFile(filename=None, file=io.BytesIO(b"data"))
        import asyncio as _asyncio

        outcome = _asyncio.run(
            workspace_router.post_transcribe_audio(file=upload),
        )
        assert outcome == {"text": "ok"}
        assert captured[0].endswith(".webm")
