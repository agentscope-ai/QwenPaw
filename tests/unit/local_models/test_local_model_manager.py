# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from qwenpaw.local_models import manager as local_model_manager_module
from qwenpaw.local_models.llamacpp import LlamaCppServerSetupResult
from qwenpaw.local_models.manager import (
    DownloadSource,
    LocalModelManager,
)
from qwenpaw.local_models.llamacpp import LlamaCppBackend
from qwenpaw.local_models.model_manager import ModelManager
from qwenpaw.providers.provider import ModelInfo


class _FakeLlamaCppBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []
        self.server_running = False

    def check_llamacpp_installability(self) -> tuple[bool, str]:
        self.calls.append(("installability", None))
        return True, ""

    def check_llamacpp_installation(self) -> tuple[bool, str]:
        self.calls.append(("check", None))
        return True, ""

    def get_server_status(self) -> dict[str, object]:
        self.calls.append(("server_status", None))
        return {
            "running": self.server_running,
            "port": 8080 if self.server_running else None,
            "model_name": "demo" if self.server_running else None,
            "pid": 123 if self.server_running else None,
        }

    def download(self, base_url: str, tag: str) -> None:
        self.calls.append(("download", (base_url, tag)))

    def get_download_progress(self) -> dict[str, object]:
        self.calls.append(("progress", None))
        return {"status": "downloading"}

    def cancel_download(self) -> None:
        self.calls.append(("cancel", None))

    async def server_ready(self, timeout: float = 120.0) -> bool:
        self.calls.append(("server_ready", timeout))
        return True

    async def setup_server(
        self,
        model_path: Path,
        model_name: str,
        max_context_length: int | None = None,
        port: int | None = None,
    ) -> LlamaCppServerSetupResult:
        self.calls.append(
            (
                "setup",
                tuple(
                    value
                    for value in (
                        model_path,
                        model_name,
                        max_context_length,
                        port,
                    )
                    if value is not None
                ),
            ),
        )
        return LlamaCppServerSetupResult(
            port=8080,
            model_info=ModelInfo(
                id=model_name,
                name=model_name,
                supports_multimodal=False,
                supports_image=False,
                supports_video=False,
                probe_source="documentation",
            ),
        )

    async def shutdown_server(self) -> None:
        self.calls.append(("shutdown", None))
        self.server_running = False


class _FakeModelManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []

    def get_recommended_models(self) -> list[str]:
        self.calls.append(("recommended", None))
        return ["demo-model"]

    def is_downloaded(self, model_name: str) -> bool:
        self.calls.append(("is_downloaded", model_name))
        return model_name == "downloaded-model"

    def list_downloaded_models(self) -> list[str]:
        self.calls.append(("list_downloaded", None))
        return ["downloaded-model"]

    def get_model_dir(self, model_name: str) -> Path:
        return Path(f"/fake/path/{model_name}")

    def download_model(
        self,
        model_name: str,
        source: DownloadSource | None = None,
    ) -> None:
        self.calls.append(("download_model", (model_name, source)))

    def get_download_progress(self) -> dict[str, object]:
        self.calls.append(("progress", None))
        return {"status": "pending"}

    def cancel_download(self) -> None:
        self.calls.append(("cancel", None))

    def remove_downloaded_model(self, model_name: str) -> None:
        self.calls.append(("remove", model_name))


@pytest.mark.asyncio
async def test_local_model_manager_forwards_sync_calls() -> None:
    fake_model_manager = _FakeModelManager()
    fake_llamacpp_backend = _FakeLlamaCppBackend()
    manager = LocalModelManager(
        model_manager=cast(ModelManager, fake_model_manager),
        llamacpp_backend=cast(LlamaCppBackend, fake_llamacpp_backend),
    )

    assert manager.check_llamacpp_installability() == (True, "")
    assert manager.check_llamacpp_installation() == (True, "")
    server_stopped = await manager.start_llamacpp_download()
    assert manager.get_llamacpp_download_progress() == {
        "status": "downloading",
    }
    manager.cancel_llamacpp_download()
    assert server_stopped is False

    assert manager.get_recommended_models() == ["demo-model"]
    assert manager.is_model_downloaded("downloaded-model") is True
    assert manager.list_downloaded_models() == ["downloaded-model"]
    manager.start_model_download(
        "demo-model",
        source=DownloadSource.MODELSCOPE,
    )
    assert manager.get_model_download_progress() == {"status": "pending"}
    manager.cancel_model_download()
    manager.remove_downloaded_model("downloaded-model")

    assert fake_llamacpp_backend.calls == [
        ("installability", None),
        ("check", None),
        ("server_status", None),
        (
            "download",
            (
                LocalModelManager.DEFAULT_LLAMA_CPP_BASE_URL,
                LocalModelManager.DEFAULT_LLAMA_CPP_RELEASE_TAG,
            ),
        ),
        ("progress", None),
        ("cancel", None),
    ]
    assert fake_model_manager.calls == [
        ("recommended", None),
        ("is_downloaded", "downloaded-model"),
        ("list_downloaded", None),
        ("download_model", ("demo-model", DownloadSource.MODELSCOPE)),
        ("progress", None),
        ("cancel", None),
        ("remove", "downloaded-model"),
    ]


@pytest.mark.asyncio
async def test_local_model_manager_forwards_async_server_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_model_manager_module,
        "DEFAULT_LOCAL_PROVIDER_DIR",
        tmp_path,
    )
    fake_llamacpp_backend = _FakeLlamaCppBackend()
    manager = LocalModelManager(
        model_manager=cast(ModelManager, _FakeModelManager()),
        llamacpp_backend=cast(LlamaCppBackend, fake_llamacpp_backend),
    )
    await manager.set_max_context_length(131072)
    await manager.set_port(43110)

    ready = await manager.check_llamacpp_server_ready(timeout=7.5)
    setup_result = await manager.setup_server("demo")
    await manager.shutdown_server()

    assert ready is True
    assert setup_result.port == 8080
    assert setup_result.model_info == ModelInfo(
        id="demo",
        name="demo",
        supports_multimodal=False,
        supports_image=False,
        supports_video=False,
        probe_source="documentation",
    )
    assert fake_llamacpp_backend.calls == [
        ("server_ready", 7.5),
        ("setup", (Path("/fake/path/demo"), "demo", 131072, 43110)),
        ("shutdown", None),
    ]


@pytest.mark.asyncio
async def test_set_max_context_length_persists_local_model_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_model_manager_module,
        "DEFAULT_LOCAL_PROVIDER_DIR",
        tmp_path,
    )
    manager = LocalModelManager(
        model_manager=cast(ModelManager, _FakeModelManager()),
        llamacpp_backend=cast(LlamaCppBackend, _FakeLlamaCppBackend()),
    )

    await manager.set_max_context_length(131072)

    assert manager.get_config().max_context_length == 131072
    config_path = tmp_path / LocalModelManager.CONFIG_FILE_NAME
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "max_context_length": 131072,
        "port": None,
    }


@pytest.mark.asyncio
async def test_set_port_persists_local_model_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_model_manager_module,
        "DEFAULT_LOCAL_PROVIDER_DIR",
        tmp_path,
    )
    manager = LocalModelManager(
        model_manager=cast(ModelManager, _FakeModelManager()),
        llamacpp_backend=cast(LlamaCppBackend, _FakeLlamaCppBackend()),
    )

    await manager.set_port(43110)

    assert manager.get_config().port == 43110
    config_path = tmp_path / LocalModelManager.CONFIG_FILE_NAME
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "max_context_length": 65536,
        "port": 43110,
    }


@pytest.mark.asyncio
async def test_start_llamacpp_download_stops_running_server_first() -> None:
    fake_llamacpp_backend = _FakeLlamaCppBackend()
    fake_llamacpp_backend.server_running = True
    manager = LocalModelManager(
        model_manager=cast(ModelManager, _FakeModelManager()),
        llamacpp_backend=cast(LlamaCppBackend, fake_llamacpp_backend),
    )

    server_stopped = await manager.start_llamacpp_download()

    assert server_stopped is True
    assert fake_llamacpp_backend.calls == [
        ("server_status", None),
        ("shutdown", None),
        (
            "download",
            (
                LocalModelManager.DEFAULT_LLAMA_CPP_BASE_URL,
                LocalModelManager.DEFAULT_LLAMA_CPP_RELEASE_TAG,
            ),
        ),
    ]
