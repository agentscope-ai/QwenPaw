# -*- coding: utf-8 -*-
# pylint: disable=protected-access

from __future__ import annotations

import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qwenpaw.plugins import SDKError

from llamacpp.download_manager import (
    DownloadTaskResult,
    DownloadTaskStatus,
)
from llamacpp.llamacpp import LlamaCppBackend
from llamacpp.model_manager import ModelManager, DownloadSource

from llamacpp.workers import ModelDownloads


def test_two_downloaders_cannot_publish_to_the_same_model(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "huggingface_hub.py").write_text(
        "from pathlib import Path\n"
        "def snapshot_download(repo_id, local_dir):\n"
        "    Path(local_dir, 'model.gguf').write_bytes(b'GGUF')\n"
        "    return local_dir\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    first = ModelManager(data_dir=Path("."))
    second = ModelManager(data_dir=tmp_path)
    for owner in (first, second):
        monkeypatch.setattr(owner, "_estimate_download_size", lambda **kw: 4)
        monkeypatch.setattr(
            owner,
            "_check_gguf_exists",
            lambda **kw: (True, ""),
        )

    publishing, release = Event(), Event()
    finalize = first._finalize_download_result

    def pause_before_publication(*args, **kwargs):
        publishing.set()
        assert release.wait(10)
        return finalize(*args, **kwargs)

    monkeypatch.setattr(
        first,
        "_finalize_download_result",
        pause_before_publication,
    )
    repo = "test/model"
    try:
        first.start_download(repo, DownloadSource.HUGGINGFACE)
        monitor = first._download_controller._task.monitor_thread
        assert publishing.wait(10)
        with pytest.raises(RuntimeError, match="already in progress"):
            second.start_download(repo, DownloadSource.HUGGINGFACE)
        second.cancel_download()
        release.set()
        monitor.join(10)
        assert first.get_download_progress()["status"] == "completed"
        second.start_download(repo, DownloadSource.HUGGINGFACE)
        second._download_controller._task.monitor_thread.join(10)
        assert second.get_download_progress()["status"] == "completed"
        final = first.get_model_dir(repo)
        assert list(final.iterdir()) == [final / "model.gguf"]
    finally:
        release.set()
        first._download_controller.close()
        second._download_controller.close()


class _FakeController:
    def __init__(self) -> None:
        self.started_spec = None
        self.cancel_called = False
        self.active = False
        self.snapshot_value = {
            "status": "idle",
            "model_name": None,
            "downloaded_bytes": 0,
            "total_bytes": None,
            "speed_bytes_per_sec": 0.0,
            "source": None,
            "error": None,
            "local_path": None,
        }

    def start(self, spec) -> None:
        self.started_spec = spec
        self.active = True

    def cancel(self) -> None:
        self.cancel_called = True
        self.active = False

    def snapshot(self) -> dict:
        return self.snapshot_value

    def is_active(self) -> bool:
        return self.active


def test_start_download_uses_reachable_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = ModelManager()
    controller = _FakeController()
    downloader.__dict__["_download_controller"] = controller
    downloader.__dict__["_download_tmp_dir"] = tmp_path / "tmp"
    target_dir = tmp_path / "resolved-model-dir"

    monkeypatch.setattr(
        downloader,
        "get_model_dir",
        lambda repo_id: target_dir,
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
        lambda **kwargs: (True, ""),
    )

    downloader.start_download("Qwen/Qwen2-0.5B-Instruct-GGUF")

    assert controller.started_spec is not None
    assert controller.started_spec.task.payload["repo_id"] == (
        "Qwen/Qwen2-0.5B-Instruct-GGUF"
    )
    assert (
        controller.started_spec.model_name == "Qwen/Qwen2-0.5B-Instruct-GGUF"
    )
    assert controller.started_spec.source == "modelscope"
    assert controller.started_spec.total_bytes == 100
    assert controller.started_spec.task.payload == {
        "repo_id": "Qwen/Qwen2-0.5B-Instruct-GGUF",
        "source": "modelscope",
        "staging_dir": str(
            (tmp_path / "tmp").joinpath(
                Path(
                    controller.started_spec.task.payload["staging_dir"],
                ).name,
            ),
        ),
    }
    progress = controller.started_spec.task.probe_progress()
    assert progress is not None
    assert (
        Path(controller.started_spec.task.payload["staging_dir"]).parent
        == tmp_path / "tmp"
    )
    assert progress.total_bytes == 100
    assert progress.model_name == "Qwen/Qwen2-0.5B-Instruct-GGUF"
    assert progress.source == "modelscope"


def test_download_model_is_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = ModelManager()
    calls: list[tuple[str, DownloadSource | None]] = []

    monkeypatch.setattr(
        downloader,
        "start_download",
        lambda model_id, source=None: calls.append((model_id, source)),
    )

    downloader.download_model(
        "Qwen/Qwen2-0.5B-Instruct-GGUF",
        source=DownloadSource.HUGGINGFACE,
    )

    assert calls == [
        (
            "Qwen/Qwen2-0.5B-Instruct-GGUF",
            DownloadSource.HUGGINGFACE,
        ),
    ]


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


@pytest.mark.parametrize("source", list(DownloadSource))
def test_download_model_rejects_repo_without_gguf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: DownloadSource,
) -> None:
    downloader = ModelManager()
    controller = _FakeController()
    downloader.__dict__["_download_controller"] = controller
    downloader.__dict__["_download_tmp_dir"] = tmp_path / "tmp"
    previous = controller.snapshot().copy()
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
            "Repository demo/no-gguf does not contain any .gguf files.",
        ),
    )
    with pytest.raises(ValueError, match="does not contain any .gguf files"):
        downloader.start_download("demo/no-gguf", source=source)

    assert controller.started_spec is None
    assert controller.snapshot() == previous


def test_cancel_download_delegates_to_controller() -> None:
    downloader = ModelManager()
    controller = _FakeController()
    downloader.__dict__["_download_controller"] = controller

    downloader.cancel_download()

    assert controller.cancel_called is True


@pytest.mark.parametrize(
    "source",
    [DownloadSource.HUGGINGFACE, DownloadSource.MODELSCOPE],
)
def test_start_download_uses_explicit_source_without_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: DownloadSource,
) -> None:
    downloader = ModelManager()
    controller = _FakeController()
    downloader.__dict__["_download_controller"] = controller
    downloader.__dict__["_download_tmp_dir"] = tmp_path / "tmp"
    target_dir = tmp_path / "resolved-model-dir"

    monkeypatch.setattr(
        downloader,
        "get_model_dir",
        lambda repo_id: target_dir,
    )

    def _unexpected_probe() -> DownloadSource:
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

    downloader.start_download(
        "Qwen/Qwen2-0.5B-Instruct-GGUF",
        source=source,
    )

    assert controller.started_spec is not None
    assert controller.started_spec.task.payload["repo_id"] == (
        "Qwen/Qwen2-0.5B-Instruct-GGUF"
    )
    assert controller.started_spec.source == source.value


def test_finalize_download_result_promotes_staging_dir(
    tmp_path: Path,
) -> None:
    downloader = ModelManager()
    staging_dir = tmp_path / "staging"
    final_dir = tmp_path / "final"
    staging_dir.mkdir()
    (staging_dir / "model.gguf").write_bytes(b"123")

    result, downloaded_bytes = downloader._finalize_download_result(
        DownloadTaskResult(
            status=DownloadTaskStatus.COMPLETED,
            local_path=str(staging_dir),
        ),
        staging_dir=staging_dir,
        final_dir=final_dir,
    )

    assert result.status == DownloadTaskStatus.COMPLETED
    assert result.local_path == str(final_dir)
    assert downloaded_bytes == 3
    assert not staging_dir.exists()
    assert (final_dir / "model.gguf").exists()


def test_get_model_dir_preserves_repo_id_path() -> None:
    downloader = ModelManager()

    model_dir = downloader.get_model_dir("Qwen/Qwen3-0.6B-GGUF")

    assert model_dir.parts[-2:] == ("Qwen", "Qwen3-0.6B-GGUF")


@pytest.mark.parametrize(
    ("repo_id", "model_type", "name"),
    [
        ("Qwen/Qwen3-0.6B-GGUF", "chat", "Qwen/Qwen3-0.6B-GGUF"),
        ("custom-model", "chat", "custom-model"),
        ("agentscope-ai/Piccolo-27B", "decision", "Piccolo-27B"),
        ("agentscope-ai/Piccolo-4B-Q8_0", "decision", "Piccolo-4B-Q8_0"),
        ("agentscope-ai/Piccolo-4B-BF16", "decision", "Piccolo-4B-BF16"),
        ("agentscope-ai/Piccolo-9B-BF16", "decision", "Piccolo-9B-BF16"),
        ("agentscope-ai/Piccolo-27B-BF16", "decision", "Piccolo-27B-BF16"),
        ("agentscope-ai/Piccolo-27B-Q4_K_M", "decision", "Piccolo-27B-Q4_K_M"),
    ],
)
def test_list_and_remove_downloaded_models_with_repo_id_layout(
    tmp_path: Path,
    repo_id: str,
    model_type: str,
    name: str,
) -> None:
    downloader = ModelManager()
    downloader.__dict__["_model_dir"] = tmp_path / "models"

    repo_dir = downloader.get_model_dir(repo_id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "model.gguf").write_bytes(b"123")
    (repo_dir / "README.md").write_text("demo", encoding="utf-8")
    owner_readme = repo_dir.parent / "README.md"
    owner_readme.touch()

    models = downloader.list_downloaded_models()

    assert len(models) == 1
    assert models[0].id == repo_id
    assert models[0].name == name
    assert models[0].model_type == model_type

    downloader.remove_downloaded_model(repo_id)

    assert not repo_dir.exists()
    assert owner_readme.is_file()


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


def test_list_and_remove_legacy_model_with_nested_weights(
    tmp_path: Path,
) -> None:
    manager = ModelManager(data_dir=tmp_path)
    weights = manager.get_model_dir("my-model/weights")
    weights.mkdir(parents=True)
    (weights / "a.gguf").touch()
    readme = weights.parent / "README.md"
    readme.touch()

    assert [model.id for model in manager.list_downloaded_models()] == [
        "my-model",
    ]
    manager.remove_downloaded_model("my-model")
    assert manager.list_downloaded_models() == []
    assert readme.is_file()


def test_delete_rejects_non_model_directories(tmp_path: Path) -> None:
    manager = ModelManager(data_dir=tmp_path)
    repo = manager.get_model_dir("owner/model")
    repo.mkdir(parents=True)
    weights = repo / "model.gguf"
    weights.touch()
    (repo.parent / "README.md").touch()
    notes = manager.get_model_dir("notes")
    notes.mkdir()
    (notes / "keep.txt").touch()

    for model_id in ("", "owner", "notes"):
        with pytest.raises(
            ValueError,
            match="Downloaded local model not found",
        ):
            manager.remove_downloaded_model(model_id)
    assert weights.is_file()
    assert (repo.parent / "README.md").is_file()
    assert (notes / "keep.txt").is_file()

    for running_model_id in ("owner/model/model.gguf", "owner"):
        with pytest.raises(
            SDKError,
            match="Cannot delete a model while it is running",
        ):
            manager.remove_downloaded_model("owner/model", running_model_id)
    assert weights.is_file()


def test_delete_rejects_symlink_to_directory_outside_models(
    tmp_path: Path,
) -> None:
    manager = ModelManager(data_dir=tmp_path)
    outside = tmp_path / "external"
    outside.mkdir()
    weights = outside / "model.gguf"
    weights.touch()
    alias = manager.get_model_dir("linked-model")
    alias.parent.mkdir()
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks are unavailable")

    assert [m.id for m in manager.list_downloaded_models()] == ["linked-model"]
    backend = LlamaCppBackend(data_dir=tmp_path)
    assert backend._resolve_model_file(alias) == (weights, None)
    with pytest.raises(ValueError, match="Downloaded local model not found"):
        manager.remove_downloaded_model("linked-model")
    assert weights.is_file()
    assert alias.is_symlink()


def test_delete_preserves_a_separate_model_in_a_child_directory(
    tmp_path: Path,
) -> None:
    manager = ModelManager(data_dir=tmp_path)
    child = manager.get_model_dir("owner/model")
    child.mkdir(parents=True)
    parent_weights = child.parent / "standalone.gguf"
    child_weights = child / "model.gguf"
    parent_weights.touch()
    child_weights.touch()
    projection = child.parent / "vision" / "mmproj.gguf"
    projection.parent.mkdir()
    projection.touch()

    assert {model.id for model in manager.list_downloaded_models()} == {
        "owner",
        "owner/model",
    }
    with pytest.raises(SDKError, match="contains another model"):
        manager.remove_downloaded_model("owner")
    assert parent_weights.is_file()
    assert child_weights.is_file()

    manager.remove_downloaded_model("owner/model")
    assert not child.exists()
    assert parent_weights.is_file()
    manager.remove_downloaded_model("owner")
    assert not projection.exists()


def test_download_worker_reports_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    queue_messages: list[dict[str, object | dict[str, object]]] = []

    class _Queue:
        def put(self, item):
            queue_messages.append(item)

    monkeypatch.setattr(
        ModelDownloads,
        "_download_to_directory",
        staticmethod(lambda **kwargs: str(tmp_path / "downloaded")),
    )

    getattr(ModelDownloads, "_download_worker")(
        {
            "repo_id": "AgentScope/demo",
            "source": "modelscope",
            "staging_dir": str(tmp_path / "staging"),
        },
        _Queue(),
    )

    assert len(queue_messages) == 1
    assert queue_messages[0]["type"] == "result"
    payload = queue_messages[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["status"] == "completed"


def test_download_from_modelscope_redirects_broken_standard_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _BrokenStream:
        encoding = "utf-8"

        def write(self, _text: str) -> int:
            raise OSError(22, "Invalid argument")

        def flush(self) -> None:
            raise OSError(22, "Invalid argument")

    captured: dict[str, object] = {}

    def download_repo(repo_id: str, repo_type: str, local_dir: Path) -> Path:
        assert repo_type == "model"
        captured["model_id"] = repo_id
        captured["local_dir"] = local_dir
        captured["stdout"] = sys.stdout
        captured["stderr"] = sys.stderr
        sys.stderr.write("")
        sys.stderr.flush()
        return local_dir

    api = SimpleNamespace(
        resolve_endpoint_for_read=MagicMock(side_effect=OSError),
        download_repo=download_repo,
    )
    monkeypatch.setattr(sys, "stdout", _BrokenStream())
    monkeypatch.setattr(sys, "stderr", _BrokenStream())
    monkeypatch.setitem(
        sys.modules,
        "modelscope_hub",
        SimpleNamespace(HubApi=lambda: api, HubError=LookupError),
    )

    result = ModelDownloads._download_from_modelscope(
        repo_id="AgentScope/demo",
        local_dir=tmp_path / "download",
    )

    assert result == str(tmp_path / "download")
    assert captured["model_id"] == "AgentScope/demo"
    assert captured["local_dir"] == tmp_path / "download"
    assert captured["stdout"] is not sys.stdout
    assert captured["stderr"] is not sys.stderr
