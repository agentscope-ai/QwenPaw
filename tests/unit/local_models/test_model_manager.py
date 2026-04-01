# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from copaw.local_models.download_manager import (
    DownloadProgressTracker,
    DownloadTaskStatus,
)
from copaw.local_models.model_manager import ModelManager, DownloadSource


class _FakeProcess:
    def __init__(self) -> None:
        self._alive = True
        self.terminated = False
        self.killed = False
        self.closed = False

    def is_alive(self) -> bool:
        return self._alive

    def terminate(self) -> None:
        self.terminated = True
        self._alive = False

    def kill(self) -> None:
        self.killed = True
        self._alive = False

    def join(self, timeout=None) -> None:
        del timeout

    def close(self) -> None:
        self.closed = True


class _FakeQueue:
    def __init__(self) -> None:
        self.closed = False
        self.joined = False

    def close(self) -> None:
        self.closed = True

    def join_thread(self) -> None:
        self.joined = True


class _FakeThread:
    def __init__(self) -> None:
        self.join_calls: list[object] = []

    def join(self, timeout=None) -> None:
        self.join_calls.append(timeout)


def test_download_model_uses_reachable_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    downloader = ModelManager()
    captured = {}
    target_dir = tmp_path / "resolved-model-dir"
    download_tmp_dir = tmp_path / "tmp"

    downloader.__dict__["_download_tmp_dir"] = download_tmp_dir

    monkeypatch.setattr(
        downloader,
        "get_model_dir",
        lambda repo_id: target_dir,
    )

    monkeypatch.setattr(
        downloader,
        "_resolve_download_source",
        lambda: captured.setdefault("source", DownloadSource.MODELSCOPE),
    )
    monkeypatch.setattr(
        downloader,
        "_estimate_download_size",
        lambda **kwargs: 100,
    )
    monkeypatch.setattr(
        downloader,
        "_check_gguf_exists",
        lambda **kwargs: (True, ""),
    )

    class _FakeQueue:
        pass

    class _FakeContext:
        def Queue(self):
            return _FakeQueue()

        def Process(self, **kwargs):
            captured["process_kwargs"] = kwargs

            class _Process:
                def start(self):
                    captured["started"] = True

                def is_alive(self):
                    return True

            return _Process()

    downloader.__dict__["_context"] = _FakeContext()

    class _FakeThread:
        def __init__(self, **kwargs):
            captured["thread_kwargs"] = kwargs

        def start(self):
            captured["thread_started"] = True

    monkeypatch.setattr(
        "copaw.local_models.model_manager.threading.Thread",
        _FakeThread,
    )

    downloader.download_model("Qwen/Qwen2-0.5B-Instruct-GGUF")

    assert captured["source"] == DownloadSource.MODELSCOPE
    assert captured["started"] is True
    assert downloader.get_download_progress()["source"] == "modelscope"
    assert downloader.__dict__["_final_dir"] == target_dir.resolve()
    assert downloader.__dict__["_staging_dir"].parent == download_tmp_dir


def test_get_download_progress_returns_idle_by_default() -> None:
    downloader = ModelManager()

    assert downloader.get_download_progress() == {
        "status": "idle",
        "model_name": None,
        "downloaded_bytes": 0,
        "total_bytes": None,
        "speed_bytes_per_sec": 0.0,
        "source": None,
        "error": None,
        "local_path": None,
    }


def test_download_model_rejects_repo_without_gguf(
    monkeypatch,
    tmp_path: Path,
) -> None:
    downloader = ModelManager()

    monkeypatch.setattr(
        downloader,
        "get_model_dir",
        lambda repo_id: tmp_path / repo_id,
    )
    monkeypatch.setattr(
        downloader,
        "_resolve_download_source",
        lambda: DownloadSource.MODELSCOPE,
    )
    monkeypatch.setattr(
        downloader,
        "_estimate_download_size",
        lambda **kwargs: 100,
    )
    monkeypatch.setattr(
        downloader,
        "_check_gguf_exists",
        lambda **kwargs: (
            False,
            (
                "Repository demo/no-gguf does not contain any .gguf "
                "files on ModelScope."
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="does not contain any .gguf files",
    ):
        downloader.download_model("demo/no-gguf")

    assert downloader.get_download_progress()["status"] == "idle"
    assert downloader.__dict__["_process"] is None


def test_cancel_download_stops_active_process(tmp_path: Path) -> None:
    downloader = ModelManager()
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    (staging_dir / "partial.gguf").write_bytes(b"123")
    fake_process = _FakeProcess()
    fake_queue = _FakeQueue()
    fake_thread = _FakeThread()
    progress = DownloadProgressTracker()
    progress.reset(
        status=DownloadTaskStatus.DOWNLOADING,
        total_bytes=10,
        source="huggingface",
    )
    progress.update_downloaded(3)

    downloader.__dict__["_process"] = fake_process
    downloader.__dict__["_queue"] = fake_queue
    downloader.__dict__["_monitor_thread"] = fake_thread
    downloader.__dict__["_staging_dir"] = staging_dir
    downloader.__dict__["_final_dir"] = tmp_path / "final"
    downloader.__dict__["_progress"] = progress
    downloader.__dict__["_resolved_source"] = DownloadSource.HUGGINGFACE

    downloader.cancel_download()

    progress_snapshot = downloader.get_download_progress()
    assert fake_process.terminated is True
    assert fake_process.closed is True
    assert fake_queue.closed is True
    assert fake_queue.joined is True
    assert fake_thread.join_calls == [2]
    assert not staging_dir.exists()
    assert progress_snapshot["status"] == "cancelled"
    assert progress_snapshot["speed_bytes_per_sec"] == 0.0
    assert downloader.__dict__["_process"] is None
    assert downloader.__dict__["_queue"] is None
    assert downloader.__dict__["_monitor_thread"] is None
    assert downloader.__dict__["_staging_dir"] is None
    assert downloader.__dict__["_final_dir"] is None
    assert downloader.__dict__["_resolved_source"] is None


def test_download_model_uses_explicit_source_without_probe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    downloader = ModelManager()
    captured = {}
    target_dir = tmp_path / "resolved-model-dir"
    download_tmp_dir = tmp_path / "tmp"

    downloader.__dict__["_download_tmp_dir"] = download_tmp_dir

    monkeypatch.setattr(
        downloader,
        "get_model_dir",
        lambda repo_id: target_dir,
    )

    def _unexpected_probe():
        raise AssertionError("source probing should be skipped")

    monkeypatch.setattr(
        downloader,
        "_resolve_download_source",
        _unexpected_probe,
    )
    monkeypatch.setattr(
        downloader,
        "_estimate_download_size",
        lambda **kwargs: 100,
    )
    monkeypatch.setattr(
        downloader,
        "_check_gguf_exists",
        lambda **kwargs: (True, ""),
    )

    class _FakeQueue:
        pass

    class _FakeContext:
        def Queue(self):
            return _FakeQueue()

        def Process(self, **kwargs):
            captured["process_kwargs"] = kwargs

            class _Process:
                def start(self):
                    captured["started"] = True

                def is_alive(self):
                    return True

            return _Process()

    downloader.__dict__["_context"] = _FakeContext()

    class _FakeThread:
        def __init__(self, **kwargs):
            captured["thread_kwargs"] = kwargs

        def start(self):
            captured["thread_started"] = True

    monkeypatch.setattr(
        "copaw.local_models.model_manager.threading.Thread",
        _FakeThread,
    )

    downloader.download_model(
        "Qwen/Qwen2-0.5B-Instruct-GGUF",
        source=DownloadSource.HUGGINGFACE,
    )

    assert captured["started"] is True
    assert downloader.get_download_progress()["source"] == "huggingface"
    assert downloader.__dict__["_staging_dir"].parent == download_tmp_dir


def test_get_model_dir_preserves_repo_id_path() -> None:
    downloader = ModelManager()

    model_dir = downloader.get_model_dir("Qwen/Qwen3-0.6B-GGUF")

    assert model_dir.parts[-2:] == ("Qwen", "Qwen3-0.6B-GGUF")


def test_list_and_remove_downloaded_models_with_repo_id_layout(
    tmp_path: Path,
) -> None:
    downloader = ModelManager()
    downloader.__dict__["_model_dir"] = tmp_path / "models"

    repo_dir = downloader.get_model_dir("Qwen/Qwen3-0.6B-GGUF")
    repo_dir.mkdir(parents=True)
    (repo_dir / "model.gguf").write_bytes(b"123")
    (repo_dir / "README.md").write_text("demo", encoding="utf-8")

    models = downloader.list_downloaded_models()

    assert len(models) == 1
    assert models[0].id == "Qwen/Qwen3-0.6B-GGUF"
    assert models[0].name == "Qwen/Qwen3-0.6B-GGUF"

    downloader.remove_downloaded_model("Qwen/Qwen3-0.6B-GGUF")

    assert not repo_dir.exists()
    assert not (tmp_path / "models" / "Qwen").exists()


def test_list_downloaded_models_ignores_temporary_download_dirs(
    tmp_path: Path,
) -> None:
    downloader = ModelManager()
    downloader.__dict__["_model_dir"] = tmp_path / "models"

    completed_dir = downloader.get_model_dir("Qwen/Qwen3-0.6B-GGUF")
    completed_dir.mkdir(parents=True)
    (completed_dir / "model.gguf").write_bytes(b"123")

    staging_dir = (
        completed_dir.parent / ".Qwen3-0.6B-GGUF.1234abcd.downloading"
    )
    staging_dir.mkdir(parents=True)
    (staging_dir / "partial.gguf").write_bytes(b"12")

    models = downloader.list_downloaded_models()

    assert [model.id for model in models] == ["Qwen/Qwen3-0.6B-GGUF"]
