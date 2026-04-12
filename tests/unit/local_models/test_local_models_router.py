# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.routers.local_models import router
from copaw.local_models import DownloadSource, LocalModelInfo


class _FakeLocalModelManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.installable = True
        self.installed = True
        self.transitioning = False
        self.recommended_models: list[LocalModelInfo] = []
        self.downloaded_models: list[LocalModelInfo] = []
        self.server_state = {
            "running": False,
            "port": None,
            "model_name": None,
        }
        self.server_ready_result = True
        self.server_ready_error: Exception | None = None
        self.start_model_download_error: Exception | None = None

    def get_recommended_models(self) -> list[LocalModelInfo]:
        self.calls.append(("get_recommended_models", None))
        return self.recommended_models

    def list_downloaded_models(self) -> list[LocalModelInfo]:
        self.calls.append(("list_downloaded_models", None))
        return self.downloaded_models

    def check_llamacpp_installability(self) -> tuple[bool, str]:
        self.calls.append(("check_llamacpp_installability", None))
        return self.installable, ""

    def check_llamacpp_installation(self) -> tuple[bool, str]:
        self.calls.append(("check_llamacpp_installation", None))
        return self.installed, ""

    def get_llamacpp_server_status(self) -> dict[str, object]:
        self.calls.append(("get_llamacpp_server_status", None))
        return self.server_state

    def is_llamacpp_server_transitioning(self) -> bool:
        self.calls.append(("is_llamacpp_server_transitioning", None))
        return self.transitioning

    async def check_llamacpp_server_ready(
        self,
        timeout: float = 120.0,
    ) -> bool:
        self.calls.append(("check_llamacpp_server_ready", timeout))
        if self.server_ready_error is not None:
            raise self.server_ready_error
        return self.server_ready_result

    def start_model_download(
        self,
        model_id: str,
        source: DownloadSource | None = None,
    ) -> None:
        self.calls.append(("start_model_download", (model_id, source)))
        if self.start_model_download_error is not None:
            raise self.start_model_download_error


def _build_test_client(manager: _FakeLocalModelManager) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.local_model_manager = manager
    app.state.provider_manager = object()
    return TestClient(app)


def test_start_local_model_download_forwards_source() -> None:
    manager = _FakeLocalModelManager()
    client = _build_test_client(manager)

    response = client.post(
        "/local-models/models/download",
        json={
            "model_name": "AgentScope/CoPaw-flash-4B-Q4_K_M",
            "source": "modelscope",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "message": "Local model download started: "
        "AgentScope/CoPaw-flash-4B-Q4_K_M",
    }
    assert manager.calls == [
        (
            "start_model_download",
            (
                "AgentScope/CoPaw-flash-4B-Q4_K_M",
                DownloadSource.MODELSCOPE,
            ),
        ),
    ]


def test_list_local_returns_union_deduplicated_by_id() -> None:
    manager = _FakeLocalModelManager()
    manager.recommended_models = [
        LocalModelInfo(
            id="AgentScope/CoPaw-flash-4B-Q4_K_M",
            name="CoPaw-flash-4B-Q4_K_M",
            size_bytes=3066384736,
            downloaded=True,
        ),
    ]
    manager.downloaded_models = [
        LocalModelInfo(
            id="AgentScope/CoPaw-flash-4B-Q4_K_M",
            name="duplicate-local-entry",
            size_bytes=1,
            downloaded=True,
        ),
        LocalModelInfo(
            id="custom/local-model",
            name="custom/local-model",
            size_bytes=2048,
            downloaded=True,
        ),
    ]
    client = _build_test_client(manager)

    response = client.get("/local-models/models")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "AgentScope/CoPaw-flash-4B-Q4_K_M",
            "name": "CoPaw-flash-4B-Q4_K_M",
            "supports_multimodal": None,
            "supports_image": None,
            "supports_video": None,
            "probe_source": None,
            "size_bytes": 3066384736,
            "downloaded": True,
            "source": "auto",
        },
        {
            "id": "custom/local-model",
            "name": "custom/local-model",
            "supports_multimodal": None,
            "supports_image": None,
            "supports_video": None,
            "probe_source": None,
            "size_bytes": 2048,
            "downloaded": True,
            "source": "auto",
        },
    ]
    assert manager.calls == [
        ("get_recommended_models", None),
        ("list_downloaded_models", None),
    ]


def test_start_local_model_download_rejects_invalid_source() -> None:
    manager = _FakeLocalModelManager()
    client = _build_test_client(manager)

    response = client.post(
        "/local-models/models/download",
        json={
            "model_name": "AgentScope/CoPaw-flash-4B-Q4_K_M",
            "source": "unknown-source",
        },
    )

    assert response.status_code == 422
    assert manager.calls == []


def test_start_local_model_download_returns_missing_gguf_error() -> None:
    manager = _FakeLocalModelManager()
    manager.start_model_download_error = ValueError(
        (
            "Repository demo/no-gguf does not contain any .gguf files "
            "on ModelScope."
        ),
    )
    client = _build_test_client(manager)

    response = client.post(
        "/local-models/models/download",
        json={
            "model_name": "demo/no-gguf",
            "source": "modelscope",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "Repository demo/no-gguf does not contain any .gguf files "
            "on ModelScope."
        ),
    }


def test_server_available_returns_starting_during_transition() -> None:
    manager = _FakeLocalModelManager()
    manager.transitioning = True
    manager.server_state = {
        "running": True,
        "port": 8080,
        "model_name": "demo-model",
    }
    client = _build_test_client(manager)

    response = client.get("/local-models/server")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "installable": True,
        "installed": True,
        "port": 8080,
        "model_name": "demo-model",
        "message": "llama.cpp server is starting",
    }


def test_server_available_handles_temporary_ready_check_failure() -> None:
    manager = _FakeLocalModelManager()
    manager.server_state = {
        "running": True,
        "port": 8080,
        "model_name": "demo-model",
    }
    manager.server_ready_error = ValueError("transient failure")
    client = _build_test_client(manager)

    response = client.get("/local-models/server")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "installable": True,
        "installed": True,
        "port": 8080,
        "model_name": "demo-model",
        "message": "llama.cpp server status is temporarily unavailable",
    }


def test_server_available_uses_short_ready_timeout() -> None:
    manager = _FakeLocalModelManager()
    manager.server_state = {
        "running": True,
        "port": 8080,
        "model_name": "demo-model",
    }
    client = _build_test_client(manager)

    response = client.get("/local-models/server")

    assert response.status_code == 200
    assert manager.calls == [
        ("check_llamacpp_installability", None),
        ("check_llamacpp_installation", None),
        ("get_llamacpp_server_status", None),
        ("is_llamacpp_server_transitioning", None),
        ("check_llamacpp_server_ready", 3.0),
    ]
