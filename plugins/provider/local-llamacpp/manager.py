# -*- coding: utf-8 -*-
"""Facade for local llama.cpp and model download management."""

# The manager owns both internal components.
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .io_helpers import run_io

from .model_types import LocalModelConfig
from .llamacpp import LlamaCppBackend, LlamaCppServerSetupResult
from .model_manager import LocalModelInfo as RecommendedLocalModelInfo
from .model_manager import ModelManager, DownloadSource

logger = logging.getLogger(__name__)


class _StoredConfig(BaseModel):
    max_context_length: int = Field(default=65536, ge=32768)
    port: int | None = Field(default=None, ge=1, le=65535)


class LocalModelManager:  # pylint: disable=too-many-public-methods
    """Single entry point for local runtime downloads and server control."""

    DEFAULT_LLAMA_CPP_BASE_URL = (
        # Mirror of "https://github.com/ggml-org/llama.cpp/releases/download"
        "https://download.qwenpaw.agentscope.io/files/models/llama_cpp"
    )
    DEFAULT_LLAMA_CPP_RELEASE_TAG = "b8744"
    CONFIG_FILE_NAME = "config.json"

    async def start(self, data_dir: Path) -> None:
        def initialize():
            self._model_manager = ModelManager(
                data_dir=data_dir,
            )
            self._llamacpp_backend = LlamaCppBackend(
                data_dir=data_dir,
            )
            self._config_path = data_dir / self.CONFIG_FILE_NAME
            self._config = self._load_config()

        self._server_lifecycle_lock = asyncio.Lock()
        await run_io(initialize)

    async def close(self) -> None:
        import atexit

        model_manager = getattr(self, "_model_manager", None)
        if model_manager is not None:
            await run_io(model_manager._download_controller.close)
        backend = getattr(self, "_llamacpp_backend", None)
        if backend is not None:
            await run_io(backend._download_controller.close)
            await backend.shutdown_server()
            atexit.unregister(backend._shutdown_server_at_exit)

    def _load_config(self) -> _StoredConfig:
        """Load persisted local runtime settings from disk."""
        if not self._config_path.exists():
            return _StoredConfig()

        try:
            with open(self._config_path, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
            return _StoredConfig.model_validate(payload)
        except (OSError, ValueError, ValidationError) as exc:
            logger.warning(
                "Failed to load local model config from %s: %s",
                self._config_path,
                exc,
            )
            return _StoredConfig()

    @staticmethod
    def _write_config_file(
        config_path,
        payload: dict[str, Any],
    ) -> None:
        """Write local runtime settings to disk in a worker thread."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as file_obj:
            json.dump(
                payload,
                file_obj,
                ensure_ascii=False,
                indent=2,
            )
        try:
            config_path.chmod(0o600)
        except OSError:
            pass

    async def _save_config(self) -> None:
        """Persist local runtime settings to disk without blocking the loop."""
        await asyncio.to_thread(
            self._write_config_file,
            self._config_path,
            self._config.model_dump(),
        )

    def get_config(self) -> LocalModelConfig:
        """Return the current local runtime settings."""
        return LocalModelConfig(**self._config.model_dump())

    async def set_max_context_length(self, max_context_length: int) -> None:
        """Persist the max context length for future llama.cpp startups."""
        async with self._server_lifecycle_lock:
            self._config.max_context_length = max_context_length
            await self._save_config()

    async def set_port(self, port: int | None) -> None:
        """Persist the llama.cpp server port for future startups."""
        async with self._server_lifecycle_lock:
            self._config.port = port
            await self._save_config()

    def check_installation(self) -> tuple[bool, str]:
        """Return whether llama.cpp is already installed locally."""
        return self._llamacpp_backend.check_llamacpp_installation()

    def check_installability(self) -> tuple[bool, str]:
        """Return whether the current environment can install llama.cpp."""
        return self._llamacpp_backend.check_llamacpp_installability()

    async def start_runtime_download(self) -> bool:
        """Start the llama.cpp binary download task.

        Returns whether a running llama.cpp server was stopped first.
        """
        async with self._server_lifecycle_lock:
            server_was_running = bool(
                self._llamacpp_backend.get_server_status().get("running"),
            )
            if server_was_running:
                await self._llamacpp_backend.shutdown_server()

            self._llamacpp_backend.download(
                self.DEFAULT_LLAMA_CPP_BASE_URL,
                self.DEFAULT_LLAMA_CPP_RELEASE_TAG,
            )
            return server_was_running

    async def has_update(self) -> bool:
        """Return whether a llama.cpp update is available for download."""
        return await self._llamacpp_backend.has_update(
            self.DEFAULT_LLAMA_CPP_RELEASE_TAG,
        )

    async def server_ready(
        self,
        timeout: float = 120.0,
    ) -> bool:
        """Return whether the llama.cpp server is ready."""
        return await self._llamacpp_backend.server_ready(timeout=timeout)

    def get_runtime_download_progress(self) -> dict[str, Any]:
        """Return the current llama.cpp download progress."""
        return self._llamacpp_backend.get_download_progress()

    def get_server_status(self) -> dict[str, Any]:
        """Return the current llama.cpp server status."""
        return self._llamacpp_backend.get_server_status()

    def is_server_transitioning(self) -> bool:
        """Return whether the llama.cpp server is starting or stopping."""
        return self._llamacpp_backend.is_server_transitioning()

    def cancel_runtime_download(self) -> None:
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
        model_id: str,
        source: DownloadSource | None = None,
    ) -> None:
        """Start downloading the requested model."""
        self._model_manager.download_model(model_id, source=source)

    def get_model_download_progress(self) -> dict[str, Any]:
        """Return the current model download progress."""
        return self._model_manager.get_download_progress()

    def cancel_model_download(self) -> None:
        """Cancel the current model download task."""
        self._model_manager.cancel_download()

    def remove_downloaded_model(self, model_id: str) -> None:
        """Delete a downloaded local model by repo id or directory name."""
        self._model_manager.remove_downloaded_model(model_id)

    async def ensure_server(
        self,
        model_id: str,
    ) -> LlamaCppServerSetupResult:
        """Start the llama.cpp server for the specified model."""
        async with self._server_lifecycle_lock:
            return await self._llamacpp_backend.setup_server(
                model_path=self._model_manager.get_model_dir(model_id),
                model_name=model_id,
                max_context_length=self._config.max_context_length,
                port=self._config.port,
            )

    async def stop_server(self) -> None:
        """Stop the current llama.cpp server if it is running."""
        async with self._server_lifecycle_lock:
            await self._llamacpp_backend.shutdown_server()
