# -*- coding: utf-8 -*-
# pylint: disable=protected-access

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import cast
from types import SimpleNamespace
import asyncio

import pytest

from llamacpp.llamacpp import LlamaCppServerSetupResult
from llamacpp.manager import (
    DownloadSource,
    LocalModelManager,
)
from llamacpp.llamacpp import LlamaCppBackend
from llamacpp.model_manager import ModelManager
from llamacpp.model_types import LocalModelInfo as ModelInfo
import llamacpp.manager as manager_module
from llamacpp.io_helpers import (
    DOWNLOAD_CLOSE_SECONDS,
    SERVER_CLOSE_SECONDS,
    PROVIDER_CLOSE_SECONDS,
)


@pytest.mark.parametrize("failed", ["model", "runtime", "server"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_close_attempts_all_children_and_can_retry(
    monkeypatch,
    failed,
    error_type,
):
    calls = []
    failing = {failed}
    unregistered = []

    def stop(name):
        calls.append(name)
        if name in failing:
            raise error_type(name + " still running")

    async def stop_server():
        stop("server")

    backend = SimpleNamespace(
        _download_controller=SimpleNamespace(close=lambda: stop("runtime")),
        shutdown_server=stop_server,
        _shutdown_server_at_exit=object(),
    )
    manager = LocalModelManager()
    manager._model_manager = SimpleNamespace(
        _download_controller=SimpleNamespace(close=lambda: stop("model")),
    )
    manager._llamacpp_backend = backend
    monkeypatch.setattr("atexit.unregister", unregistered.append)
    with pytest.raises(error_type) as caught:
        await manager.close()
    if error_type is RuntimeError:
        assert failed + " still running" in str(caught.value)
    assert set(calls) == {"model", "runtime", "server"}
    assert bool(unregistered) == (failed != "server")
    failing.clear()
    await manager.close()
    assert all(
        calls.count(name) == 2 for name in {"model", "runtime", "server"}
    )


async def test_close_starts_independent_children_before_waiting(monkeypatch):
    entered = set()
    release = asyncio.Event()

    async def stop(name):
        entered.add(name)
        if len(entered) == 3:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=1)

    async def run_async(operation):
        await operation()

    monkeypatch.setattr(manager_module, "run_io", run_async)
    monkeypatch.setattr("atexit.unregister", lambda _: None)
    manager = LocalModelManager()
    manager._model_manager = SimpleNamespace(
        _download_controller=SimpleNamespace(close=lambda: stop("model")),
    )
    manager._llamacpp_backend = SimpleNamespace(
        _download_controller=SimpleNamespace(close=lambda: stop("runtime")),
        shutdown_server=lambda: stop("server"),
        _shutdown_server_at_exit=object(),
    )
    await manager.close()
    assert PROVIDER_CLOSE_SECONDS > max(
        DOWNLOAD_CLOSE_SECONDS,
        SERVER_CLOSE_SECONDS,
    )
    assert (
        PROVIDER_CLOSE_SECONDS
        < DOWNLOAD_CLOSE_SECONDS * 2 + SERVER_CLOSE_SECONDS
    )


async def test_close_cancellation_waits_for_owned_blocking_io(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    server_stopped = asyncio.Event()

    def stop_download():
        entered.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test download cleanup was not released")
        finished.set()

    async def stop_server():
        server_stopped.set()

    monkeypatch.setattr("atexit.unregister", lambda _: None)
    manager = LocalModelManager()
    manager._model_manager = SimpleNamespace(
        _download_controller=SimpleNamespace(close=stop_download),
    )
    manager._llamacpp_backend = SimpleNamespace(
        _download_controller=SimpleNamespace(close=lambda: None),
        shutdown_server=stop_server,
        _shutdown_server_at_exit=object(),
    )
    closing = asyncio.create_task(manager.close())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await asyncio.wait_for(server_stopped.wait(), timeout=5)
        closing.cancel()
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert finished.is_set()
        await manager.close()
    finally:
        release.set()
        await asyncio.gather(closing, return_exceptions=True)


def make_manager(*, model_manager, llamacpp_backend, data_dir):
    manager = LocalModelManager()
    manager._model_manager = model_manager
    manager._llamacpp_backend = llamacpp_backend
    manager._server_lifecycle_lock = asyncio.Lock()
    manager._config_path = data_dir / manager.CONFIG_FILE_NAME
    manager._config = manager._load_config()
    return manager


async def test_lazy_initialization_loads_config_off_event_loop(
    monkeypatch,
    tmp_path,
):
    (tmp_path / "config.json").write_text(
        json.dumps({"max_context_length": 131072, "port": 43110}),
        encoding="utf-8",
    )
    caller = threading.get_ident()
    threads = []
    original = ModelManager.__init__

    def initialize(self, **kwargs):
        threads.append(threading.get_ident())
        original(self, **kwargs)

    monkeypatch.setattr(ModelManager, "__init__", initialize)
    monkeypatch.setattr(LlamaCppBackend, "_resolve_os_name", lambda _: "linux")
    monkeypatch.setattr(LlamaCppBackend, "_resolve_arch", lambda _: "x64")
    monkeypatch.setattr(
        LlamaCppBackend,
        "_resolve_cuda_version",
        lambda _: None,
    )
    manager = LocalModelManager()
    try:
        await manager.start(tmp_path)
        assert threads and all(thread != caller for thread in threads)
        assert manager.get_config().max_context_length == 131072
        assert manager.get_config().port == 43110
        assert (
            manager._model_manager.get_model_dir("A") == tmp_path / "models/A"
        )
        assert manager._llamacpp_backend.target_dir == tmp_path / "bin"
    finally:
        await manager.close()


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
async def test_local_model_manager_forwards_sync_calls(tmp_path) -> None:
    fake_model_manager = _FakeModelManager()
    fake_llamacpp_backend = _FakeLlamaCppBackend()
    manager = make_manager(
        data_dir=tmp_path,
        model_manager=cast(ModelManager, fake_model_manager),
        llamacpp_backend=cast(LlamaCppBackend, fake_llamacpp_backend),
    )

    assert manager.check_installability() == (True, "")
    assert manager.check_installation() == (True, "")
    server_stopped = await manager.start_runtime_download()
    assert manager.get_runtime_download_progress() == {
        "status": "downloading",
    }
    manager.cancel_runtime_download()
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
) -> None:
    fake_llamacpp_backend = _FakeLlamaCppBackend()
    manager = make_manager(
        data_dir=tmp_path,
        model_manager=cast(ModelManager, _FakeModelManager()),
        llamacpp_backend=cast(LlamaCppBackend, fake_llamacpp_backend),
    )
    await manager.set_max_context_length(131072)
    await manager.set_port(43110)

    ready = await manager.server_ready(timeout=7.5)
    setup_result = await manager.ensure_server("demo")
    await manager.stop_server()

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
) -> None:
    manager = make_manager(
        data_dir=tmp_path,
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
) -> None:
    manager = make_manager(
        data_dir=tmp_path,
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
async def test_start_llamacpp_download_stops_running_server_first(
    tmp_path,
) -> None:
    fake_llamacpp_backend = _FakeLlamaCppBackend()
    fake_llamacpp_backend.server_running = True
    manager = make_manager(
        data_dir=tmp_path,
        model_manager=cast(ModelManager, _FakeModelManager()),
        llamacpp_backend=cast(LlamaCppBackend, fake_llamacpp_backend),
    )

    server_stopped = await manager.start_runtime_download()

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
