# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the managed MLX inference engine."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import qwenpaw.local_models.mlx as mlx_module
from qwenpaw.local_models.mlx import MLX_LM_VERSION, MlxBackend


def _write_mlx_model(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "model.safetensors").write_bytes(b"weights")
    return path


def test_installability_requires_apple_silicon(monkeypatch, tmp_path):
    backend = MlxBackend()
    monkeypatch.setattr(mlx_module.system_info, "get_os_name", lambda: "linux")
    assert backend.check_installability()[0] is False

    monkeypatch.setattr(mlx_module.system_info, "get_os_name", lambda: "macos")
    monkeypatch.setattr(
        mlx_module.system_info,
        "get_architecture",
        lambda: "x64",
    )
    assert backend.check_installability()[0] is False


def test_installation_requires_matching_marker(monkeypatch, tmp_path):
    backend = MlxBackend()
    backend.target_dir = tmp_path / "mlx"
    backend.venv_dir = backend.target_dir / "venv"
    backend.venv_dir.mkdir(parents=True)
    (backend.venv_dir / "bin").mkdir()
    (backend.venv_dir / "bin" / "python").write_text("", encoding="utf-8")
    assert backend.check_installation()[0] is False

    (backend.venv_dir / ".qwenpaw-mlx-lm-version").write_text(
        MLX_LM_VERSION,
        encoding="utf-8",
    )
    assert backend.check_installation() == (True, "")

    (backend.venv_dir / ".qwenpaw-mlx-lm-version").write_text(
        "99.0.0",
        encoding="utf-8",
    )
    assert backend.check_installation() == (True, "")


def test_resolve_model_dir_rejects_gguf_only_directory(tmp_path):
    path = tmp_path / "gguf-model"
    path.mkdir()
    (path / "model.gguf").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="config.json"):
        MlxBackend._resolve_model_dir(path)


def test_build_model_info_uses_absolute_path_as_served_id(tmp_path):
    model_dir = _write_mlx_model(tmp_path / "model")
    resolved = MlxBackend._resolve_model_dir(model_dir)
    info = MlxBackend._build_model_info(
        model_name="mlx-community/demo",
        model_path=resolved,
    )
    assert info.id == str(resolved)
    assert info.name == "mlx-community/demo"
    assert info.model_type == "chat"


def test_check_installation_recovers_interrupted_swap(tmp_path):
    backend = MlxBackend()
    backend.target_dir = tmp_path / "mlx"
    backend.venv_dir = backend.target_dir / "venv"
    backup = backend.target_dir / "venv.backup-test"
    (backup / "bin").mkdir(parents=True)
    (backup / "bin" / "python").write_text("", encoding="utf-8")
    (backup / ".qwenpaw-mlx-lm-version").write_text(
        MLX_LM_VERSION,
        encoding="utf-8",
    )

    assert backend.check_installation() == (True, "")
    assert backend.venv_dir.exists()
    assert not backup.exists()


@pytest.mark.asyncio
async def test_has_update_compares_installed_and_latest(
    monkeypatch,
    tmp_path,
) -> None:
    backend = MlxBackend()
    backend.target_dir = tmp_path / "mlx"
    backend.venv_dir = backend.target_dir / "venv"
    backend.venv_dir.mkdir(parents=True)
    (backend.venv_dir / "bin").mkdir()
    (backend.venv_dir / "bin" / "python").write_text("", encoding="utf-8")
    (backend.venv_dir / ".qwenpaw-mlx-lm-version").write_text(
        MLX_LM_VERSION,
        encoding="utf-8",
    )

    async def fake_latest() -> str:
        return "99.0.0"

    monkeypatch.setattr(backend, "get_latest_version", fake_latest)
    assert await backend.has_update() is True


@pytest.mark.asyncio
async def test_setup_server_builds_mlx_lm_command(monkeypatch, tmp_path):
    backend = MlxBackend()
    backend.target_dir = tmp_path / "mlx"
    backend.venv_dir = backend.target_dir / "venv"
    backend.log_dir = backend.target_dir / "logs"
    backend.venv_dir.mkdir(parents=True)
    (backend.venv_dir / "bin").mkdir()
    (backend.venv_dir / "bin" / "python").write_text("", encoding="utf-8")
    (backend.venv_dir / ".qwenpaw-mlx-lm-version").write_text(
        MLX_LM_VERSION,
        encoding="utf-8",
    )
    model_dir = _write_mlx_model(tmp_path / "models" / "demo")
    commands: list[list[str]] = []

    async def fake_start(command, **_kwargs):
        commands.append(list(command))
        return SimpleNamespace(pid=123, returncode=None, stdout=None)

    async def fake_ready(timeout=180.0):
        return True

    monkeypatch.setattr(mlx_module, "start_command_async", fake_start)
    monkeypatch.setattr(backend, "server_ready", fake_ready)
    monkeypatch.setattr(backend, "_resolve_server_port", lambda port: 4567)

    result = await backend.setup_server(
        model_dir,
        "mlx-community/demo",
        port=None,
    )

    assert result.port == 4567
    assert result.model_info.id == str(model_dir.resolve())
    command = commands[0]
    assert command[1:3] == ["-m", "mlx_lm"]
    assert command[command.index("server") + 1] == "--model"
    assert command[command.index("--model") + 1] == str(model_dir.resolve())
    assert command[command.index("--port") + 1] == "4567"
