# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Engine selection and status aggregation for QwenPaw Local."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from qwenpaw.local_models.manager import (
    LocalModelManager,
    normalize_engine,
)
from qwenpaw.local_models.model_manager import ModelManager
from qwenpaw.providers.provider import ModelInfo


class _FakeBackend:
    def __init__(self, engine: str, *, installable: bool = True) -> None:
        self.engine = engine
        self.installable = installable
        self.installed = True
        self.running = False
        self.served_name = "demo"
        self.shutdown_calls = 0
        self.update_available = False
        self.latest_version = "0.32.3"
        self.download_active = False

    def check_installation(self):
        return self.installed, ""

    def check_installability(self):
        return self.installable, "" if self.installable else "unsupported"

    def get_server_status(self):
        return {
            "running": self.running,
            "port": 5000 if self.running else None,
            "model_name": self.served_name if self.running else None,
            "pid": 1 if self.running else None,
        }

    def get_download_progress(self):
        return {"status": "idle"}

    def is_server_transitioning(self):
        return False

    def cancel_download(self):
        pass

    async def get_version(self):
        return "1.0"

    async def get_accelerator_info(self):
        return {
            "accelerator": "metal" if self.engine == "mlx" else "cuda",
            "device_name": "Test GPU",
        }

    async def has_update(self, _tag=None):
        return self.update_available

    async def get_latest_version(self):
        return self.latest_version

    def is_download_active(self):
        return self.download_active

    def download(self, _base_url, _tag):
        pass

    def start_download(self, version=None):
        pass

    async def server_ready(self, timeout: float = 120.0):
        return True

    async def setup_server(self, **kwargs):
        self.running = True
        return type(
            "Result",
            (),
            {
                "port": 5001,
                "model_info": ModelInfo(id="demo", name="demo"),
            },
        )()

    async def shutdown_server(self):
        self.shutdown_calls += 1
        self.running = False


class _FakeModelManager:
    def __init__(self) -> None:
        self.downloaded = True

    def get_recommended_models(self, engine="llamacpp"):
        return []

    def is_downloaded(self, model_name, engine="llamacpp"):
        return self.downloaded

    def list_downloaded_models(self, engine=None):
        return []

    def get_model_dir(self, model_id):
        return Path("/tmp") / model_id

    def download_model(self, model_id, source=None, engine="llamacpp"):
        pass

    def get_download_progress(self):
        return {"status": "idle"}

    def cancel_download(self):
        pass

    def remove_downloaded_model(self, model_id, engine=None):
        pass


def _manager(
    tmp_path: Path,
) -> tuple[LocalModelManager, _FakeBackend, _FakeBackend]:
    llama = _FakeBackend("llamacpp")
    mlx = _FakeBackend("mlx")
    manager = LocalModelManager(
        model_manager=_FakeModelManager(),
        llamacpp_backend=llama,
        mlx_backend=mlx,
    )
    manager._config_path = tmp_path / "config.json"
    return manager, llama, mlx


def test_normalize_engine_defaults_and_rejects_unknown():
    assert normalize_engine(None) == "llamacpp"
    assert normalize_engine("mlx") == "mlx"
    with pytest.raises(ValueError):
        normalize_engine("cuda")


@pytest.mark.asyncio
async def test_missing_target_runtime_does_not_stop_the_other_engine(tmp_path):
    manager, llama, mlx = _manager(tmp_path)
    llama.running = True
    mlx.installed = False

    with pytest.raises(RuntimeError, match="not installed"):
        await manager.setup_server("demo", engine="mlx")

    assert llama.shutdown_calls == 0
    assert llama.running is True


@pytest.mark.asyncio
async def test_auto_update_runs_both_engines_when_idle(tmp_path):
    manager, llama, mlx = _manager(tmp_path)
    await manager.set_auto_update(True)
    llama.update_available = True
    mlx.update_available = True

    statuses = await manager.run_auto_update_once()

    assert statuses == {"llamacpp": "started", "mlx": "started"}


@pytest.mark.asyncio
async def test_auto_update_defers_running_engine(tmp_path):
    manager, llama, _mlx = _manager(tmp_path)
    await manager.set_auto_update(True)
    llama.running = True
    llama.update_available = True

    assert await manager.auto_update_engine("llamacpp") == "deferred"


@pytest.mark.asyncio
async def test_missing_model_does_not_stop_the_other_engine(tmp_path):
    manager, llama, _mlx = _manager(tmp_path)
    llama.running = True
    manager._model_manager.downloaded = False

    with pytest.raises(FileNotFoundError):
        await manager.setup_server("missing/model", engine="mlx")

    assert llama.shutdown_calls == 0
    assert llama.running is True


@pytest.mark.asyncio
async def test_missing_target_runtime_does_not_stop_the_other_engine(tmp_path):
    manager, llama, mlx = _manager(tmp_path)
    llama.running = True
    mlx.installed = False

    with pytest.raises(RuntimeError, match="not installed"):
        await manager.setup_server("demo", engine="mlx")

    assert llama.shutdown_calls == 0
    assert llama.running is True


@pytest.mark.asyncio
async def test_starting_mlx_stops_llama_and_persists_engine(tmp_path):
    manager, llama, mlx = _manager(tmp_path)
    llama.running = True

    result = await manager.setup_server("demo/model", engine="mlx")

    assert result.engine == "mlx"
    assert result.stopped_engine == "llamacpp"
    assert llama.shutdown_calls == 1
    assert manager.get_config().engine == "mlx"
    assert (
        json.loads((tmp_path / "config.json").read_text())["engine"] == "mlx"
    )


@pytest.mark.asyncio
async def test_engine_status_reports_accelerator_and_installability(tmp_path):
    manager, _llama, mlx = _manager(tmp_path)
    mlx.installable = False

    status = await manager.get_engine_status("mlx")

    assert status["id"] == "mlx"
    assert status["installable"] is False
    assert status["message"] == "unsupported"
    assert status["accelerator"] == "metal"
    assert status["device_name"] == "Test GPU"


def test_is_model_serving_matches_mlx_absolute_path(tmp_path):
    manager, _llama, mlx = _manager(tmp_path)
    mlx.running = True
    model_id = "mlx-community/demo"
    mlx.served_name = str(manager._model_manager.get_model_dir(model_id))

    assert manager.is_model_serving(model_id, "mlx") is True
    assert manager.is_model_serving("mlx-community/other", "mlx") is False


def test_mlx_catalog_uses_mlx_format_and_4bit_models(monkeypatch):
    model_manager = ModelManager()
    monkeypatch.setattr(
        model_manager,
        "_detect_available_memory_gb",
        lambda: 128.0,
    )
    models = model_manager.get_recommended_models(engine="mlx")

    assert models
    assert all(model.format == "mlx" for model in models)
    assert all("-4bit" in model.id for model in models)
    assert any("30B-A3B" in model.id for model in models)
