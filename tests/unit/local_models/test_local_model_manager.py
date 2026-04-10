# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

import pytest

from copaw.local_models.manager import LocalModelManager, DownloadSource


class _FakeLlamaCppBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []

    def check_llamacpp_installation(self) -> bool:
        self.calls.append(("check", None))
        return True

    def download(self) -> None:
        self.calls.append(("download", None))

    def get_download_progress(self) -> dict[str, object]:
        self.calls.append(("progress", None))
        return {"status": "downloading"}

    def cancel_download(self) -> None:
        self.calls.append(("cancel", None))

    async def server_ready(self, timeout: float = 120.0) -> bool:
        self.calls.append(("server_ready", timeout))
        return True

    async def setup_server(self, model_path: Path, model_name: str) -> int:
        self.calls.append(("setup", (model_path, model_name)))
        return 8080

    async def shutdown_server(self) -> None:
        self.calls.append(("shutdown", None))


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


def test_local_model_manager_forwards_sync_calls() -> None:
    fake_model_manager = _FakeModelManager()
    fake_llamacpp_backend = _FakeLlamaCppBackend()
    manager = LocalModelManager(
        model_manager=fake_model_manager,
        llamacpp_backend=fake_llamacpp_backend,
    )

    assert manager.check_llamacpp_installation() is True
    manager.start_llamacpp_download()
    assert manager.get_llamacpp_download_progress() == {
        "status": "downloading",
    }
    manager.cancel_llamacpp_download()

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
        ("check", None),
        ("download", None),
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
async def test_local_model_manager_forwards_async_server_calls() -> None:
    fake_llamacpp_backend = _FakeLlamaCppBackend()
    manager = LocalModelManager(
        model_manager=_FakeModelManager(),
        llamacpp_backend=fake_llamacpp_backend,
    )

    ready = await manager.check_llamacpp_server_ready(timeout=7.5)
    port = await manager.setup_server("demo")
    await manager.shutdown_server()

    assert ready is True
    assert port == 8080
    assert fake_llamacpp_backend.calls == [
        ("server_ready", 7.5),
        ("setup", (Path("/fake/path/demo"), "demo")),
        ("shutdown", None),
    ]
