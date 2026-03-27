# -*- coding: utf-8 -*-
"""Facade for local llama.cpp and model download management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .llamacpp import LlamaCppBackend
from .schema import DownloadSource
from .model_manager import LocalModelInfo as RecommendedLocalModelInfo
from .model_manager import ModelManager


class LocalModelManager:
    """Single entry point for local runtime downloads and server control."""

    DEFAULT_LLAMA_CPP_BASE_URL = (
        "https://github.com/ggml-org/llama.cpp/releases/download"
    )
    DEFAULT_LLAMA_CPP_RELEASE_TAG = "b8513"

    def __init__(
        self,
        *,
        model_manager: ModelManager | None = None,
        llamacpp_backend: LlamaCppBackend | None = None,
        llama_cpp_base_url: str = DEFAULT_LLAMA_CPP_BASE_URL,
        llama_cpp_release_tag: str = DEFAULT_LLAMA_CPP_RELEASE_TAG,
    ) -> None:
        self._model_manager = model_manager or ModelManager()
        self._llamacpp_backend = llamacpp_backend or LlamaCppBackend(
            base_url=llama_cpp_base_url,
            release_tag=llama_cpp_release_tag,
        )

    def check_llamacpp_installation(self) -> bool:
        """Return whether llama.cpp is already installed locally."""
        return self._llamacpp_backend.check_llamacpp_installation()

    def start_llamacpp_download(self) -> None:
        """Start the llama.cpp binary download task."""
        self._llamacpp_backend.download()

    async def check_llamacpp_server_ready(self) -> bool:
        """Return whether the llama.cpp server is ready."""
        return await self._llamacpp_backend.server_ready()

    def get_llamacpp_download_progress(self) -> dict[str, Any]:
        """Return the current llama.cpp download progress."""
        return self._llamacpp_backend.get_download_progress()

    def get_llamacpp_server_status(self) -> dict[str, Any]:
        """Return the current llama.cpp server status."""
        return self._llamacpp_backend.get_server_status()

    def cancel_llamacpp_download(self) -> None:
        """Cancel the current llama.cpp download task."""
        self._llamacpp_backend.cancel_download()

    def get_recommended_models(
        self,
    ) -> list[RecommendedLocalModelInfo]:
        """Return recommended local models for the current machine."""
        return self._model_manager.get_recommended_models()

    def is_model_downloaded(self, model_name: str) -> bool:
        """Return whether the requested model is already downloaded."""
        return self._model_manager.is_downloaded(model_name)

    def list_downloaded_models(self) -> list[RecommendedLocalModelInfo]:
        """Return all downloaded local model repositories."""
        return self._model_manager.list_downloaded_models()

    def start_model_download(
        self,
        model_name: str,
        source: DownloadSource | None = None,
    ) -> None:
        """Start downloading the requested model."""
        self._model_manager.download_model(model_name, source=source)

    def get_model_download_progress(self) -> dict[str, Any]:
        """Return the current model download progress."""
        return self._model_manager.get_download_progress()

    def cancel_model_download(self) -> None:
        """Cancel the current model download task."""
        self._model_manager.cancel_download()

    def remove_downloaded_model(self, model_name: str) -> None:
        """Delete a downloaded local model by repo id or directory name."""
        self._model_manager.remove_downloaded_model(model_name)

    async def setup_server(self, model_path: Path, model_name: str) -> int:
        """Start the llama.cpp server for the specified model."""
        return await self._llamacpp_backend.setup_server(
            model_path=model_path,
            model_name=model_name,
        )

    async def shutdown_server(self) -> None:
        """Stop the current llama.cpp server if it is running."""
        await self._llamacpp_backend.shutdown_server()

    def force_shutdown_server(self) -> None:
        """Best-effort synchronous shutdown for process teardown paths."""
        self._llamacpp_backend.force_shutdown_server()
