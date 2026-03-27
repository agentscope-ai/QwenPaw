# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from copaw.local_models.model_manager import ModelManager
from copaw.local_models.schema import DownloadSource


class _FakeProcess:
    def __init__(self) -> None:
        self._alive = True
        self.terminated = False
        self.killed = False

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


def test_download_model_uses_reachable_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    downloader = ModelManager()
    captured = {}
    target_dir = tmp_path / "resolved-model-dir"

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


def test_get_download_progress_returns_idle_by_default() -> None:
    downloader = ModelManager()

    assert downloader.get_download_progress() == {
        "status": "idle",
        "downloaded_bytes": 0,
        "total_bytes": None,
        "speed_bytes_per_sec": 0.0,
        "source": None,
        "error": None,
        "local_path": None,
    }


def test_cancel_download_stops_active_process(tmp_path: Path) -> None:
    downloader = ModelManager()
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    (staging_dir / "partial.gguf").write_bytes(b"123")
    fake_process = _FakeProcess()

    downloader.__dict__["_process"] = fake_process
    downloader.__dict__["_staging_dir"] = staging_dir
    downloader.__dict__["_progress"] = {
        "status": "downloading",
        "downloaded_bytes": 3,
        "total_bytes": 10,
        "speed_bytes_per_sec": 1.0,
        "source": "huggingface",
        "error": None,
        "local_path": None,
    }

    downloader.cancel_download()

    progress = downloader.get_download_progress()
    assert fake_process.terminated is True
    assert not staging_dir.exists()
    assert progress["status"] == "cancelled"
    assert progress["speed_bytes_per_sec"] == 0.0
