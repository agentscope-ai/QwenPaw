# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from copaw.local_models import manager
from copaw.local_models.schema import BackendType, DownloadSource


@pytest.fixture(autouse=True)
def _isolate_models_dir(monkeypatch, tmp_path: Path) -> Path:
    models_dir = tmp_path / "models"
    monkeypatch.setattr(manager, "MODELS_DIR", models_dir)
    monkeypatch.setattr(manager, "MANIFEST_PATH", models_dir / "manifest.json")
    return models_dir


def _install_fake_modelscope(
    monkeypatch,
    *,
    hub_files: list[str] | None = None,
    file_download_impl=None,
    snapshot_download_impl=None,
) -> None:
    modelscope_mod = types.ModuleType("modelscope")
    hub_mod = types.ModuleType("modelscope.hub")
    api_mod = types.ModuleType("modelscope.hub.api")
    file_download_mod = types.ModuleType("modelscope.hub.file_download")
    snapshot_download_mod = types.ModuleType(
        "modelscope.hub.snapshot_download",
    )

    class HubApi:
        def get_model_files(self, repo_id: str):
            _ = repo_id
            return [{"Path": f} for f in (hub_files or [])]

    def _default_file_download(
        model_id: str,
        file_path: str,
        local_dir: str,
    ) -> str:
        _ = model_id
        target = Path(local_dir) / file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"GGUF")
        return str(target)

    def _default_snapshot_download(model_id: str, local_dir: str) -> str:
        _ = model_id
        target_dir = Path(local_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "config.json").write_text("{}", encoding="utf-8")
        (target_dir / "model.safetensors").write_bytes(b"ST")
        return str(target_dir)

    api_mod.HubApi = HubApi
    file_download_mod.model_file_download = (
        file_download_impl or _default_file_download
    )
    snapshot_download_mod.snapshot_download = (
        snapshot_download_impl or _default_snapshot_download
    )

    modelscope_mod.snapshot_download = snapshot_download_mod.snapshot_download

    monkeypatch.setitem(sys.modules, "modelscope", modelscope_mod)
    monkeypatch.setitem(sys.modules, "modelscope.hub", hub_mod)
    monkeypatch.setitem(sys.modules, "modelscope.hub.api", api_mod)
    monkeypatch.setitem(
        sys.modules,
        "modelscope.hub.file_download",
        file_download_mod,
    )
    monkeypatch.setitem(
        sys.modules,
        "modelscope.hub.snapshot_download",
        snapshot_download_mod,
    )


def test_modelscope_mlx_downloads_full_repo(
    monkeypatch,
) -> None:
    calls = {"file": 0, "snapshot": 0}

    def _never_file_download(*_, **__):
        calls["file"] += 1
        raise AssertionError("MLX path should not use model_file_download")

    def _snapshot_download(model_id: str, local_dir: str) -> str:
        _ = model_id
        calls["snapshot"] += 1
        target_dir = Path(local_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "config.json").write_text("{}", encoding="utf-8")
        (target_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
        (target_dir / "model-00001-of-00001.safetensors").write_bytes(b"ST")
        return str(target_dir)

    _install_fake_modelscope(
        monkeypatch,
        file_download_impl=_never_file_download,
        snapshot_download_impl=_snapshot_download,
    )

    repo_id = "mlx-community/Qwen3.5-0.8B-4bit-OptiQ"
    info = manager.LocalModelManager.download_model_sync(
        repo_id=repo_id,
        filename=None,
        backend=BackendType.MLX,
        source=DownloadSource.MODELSCOPE,
    )

    local_path = Path(info.local_path)
    assert local_path.is_dir()
    assert (local_path / "config.json").is_file()
    assert calls["snapshot"] == 1
    assert calls["file"] == 0
    assert info.id == repo_id
    assert info.backend == BackendType.MLX
    assert info.source == DownloadSource.MODELSCOPE


def test_modelscope_mlx_missing_config_raises(
    monkeypatch,
) -> None:
    def _snapshot_download_missing_config(
        model_id: str,
        local_dir: str,
    ) -> str:
        _ = model_id
        target_dir = Path(local_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "model.safetensors").write_bytes(b"ST")
        return str(target_dir)

    _install_fake_modelscope(
        monkeypatch,
        snapshot_download_impl=_snapshot_download_missing_config,
    )

    repo_id = "mlx-community/missing-config"
    with pytest.raises(RuntimeError, match="missing files"):
        manager.LocalModelManager.download_model_sync(
            repo_id=repo_id,
            filename=None,
            backend=BackendType.MLX,
            source=DownloadSource.MODELSCOPE,
        )

    assert manager.get_local_model(repo_id) is None


def test_modelscope_llamacpp_still_uses_single_file_download(
    monkeypatch,
) -> None:
    calls = {"file": 0, "snapshot": 0}

    def _file_download(model_id: str, file_path: str, local_dir: str) -> str:
        _ = model_id
        calls["file"] += 1
        target = Path(local_dir) / file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"GGUF")
        return str(target)

    def _snapshot_download(model_id: str, local_dir: str) -> str:
        _ = model_id
        _ = local_dir
        calls["snapshot"] += 1
        raise AssertionError("llamacpp path should not use snapshot_download")

    _install_fake_modelscope(
        monkeypatch,
        hub_files=[
            "model.Q8_0.gguf",
            "model.Q4_K_M.gguf",
        ],
        file_download_impl=_file_download,
        snapshot_download_impl=_snapshot_download,
    )

    info = manager.LocalModelManager.download_model_sync(
        repo_id="Qwen/Qwen3-4B-GGUF",
        filename=None,
        backend=BackendType.LLAMACPP,
        source=DownloadSource.MODELSCOPE,
    )

    local_path = Path(info.local_path)
    assert local_path.is_file()
    assert info.filename == "model.Q4_K_M.gguf"
    assert calls["file"] == 1
    assert calls["snapshot"] == 0
