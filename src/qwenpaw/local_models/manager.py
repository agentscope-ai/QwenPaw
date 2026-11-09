# -*- coding: utf-8 -*-
"""Facade for local llama.cpp and model download management."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..constant import DEFAULT_LOCAL_PROVIDER_DIR

from .llamacpp import LlamaCppBackend, LlamaCppServerSetupResult
from .model_manager import LocalModelInfo as RecommendedLocalModelInfo
from .model_manager import ModelManager, DownloadSource
from .runtime_release import RELEASE

logger = logging.getLogger(__name__)


class LocalModelConfig(BaseModel):
    """Persistent local runtime settings for embedded llama.cpp."""

    max_context_length: int = Field(
        default=65536,
        description="Maximum context length passed to llama.cpp on startup.",
        ge=32768,
    )
    port: int | None = Field(
        default=None,
        description=(
            "Optional fixed port for llama.cpp startup. Null means auto."
        ),
        ge=1,
        le=65535,
    )
    gpu_acceleration: bool = Field(
        default=True,
        description=(
            "Whether llama.cpp may offload layers to the GPU. Disable to "
            "force CPU inference."
        ),
    )
    auto_update: bool = Field(
        default=False,
        description=(
            "Automatically install newer local engine runtimes when idle."
        ),
    )


class LocalModelManager:  # pylint: disable=too-many-public-methods
    """Single entry point for local runtime downloads and server control."""

    _instance: LocalModelManager | None = None

    DEFAULT_LLAMA_CPP_BASE_URL = RELEASE["base_url"]
    DEFAULT_LLAMA_CPP_RELEASE_TAG = RELEASE["release"]
    CONFIG_FILE_NAME = "config.json"

    def __init__(
        self,
        *,
        model_manager: ModelManager | None = None,
        llamacpp_backend: LlamaCppBackend | None = None,
    ) -> None:
        self._model_manager = model_manager or ModelManager()
        self._llamacpp_backend = llamacpp_backend or LlamaCppBackend()
        self._server_lifecycle_lock = asyncio.Lock()
        self._config_path = DEFAULT_LOCAL_PROVIDER_DIR / self.CONFIG_FILE_NAME
        self._config = self._load_config()
        self._auto_update_task: asyncio.Task[None] | None = None

    def _load_config(self) -> LocalModelConfig:
        """Load persisted local runtime settings from disk."""
        if not self._config_path.exists():
            return LocalModelConfig()

        try:
            with open(self._config_path, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
            return LocalModelConfig.model_validate(payload)
        except (OSError, ValueError, ValidationError) as exc:
            logger.warning(
                "Failed to load local model config from %s: %s",
                self._config_path,
                exc,
            )
            return LocalModelConfig()

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
        """Return a defensive copy of the current local runtime settings."""
        return self._config.model_copy(deep=True)

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

    async def set_gpu_acceleration(self, enabled: bool) -> None:
        """Persist whether llama.cpp should offload layers to the GPU."""
        async with self._server_lifecycle_lock:
            self._config.gpu_acceleration = bool(enabled)
            await self._save_config()

    async def set_auto_update(self, enabled: bool) -> None:
        """Persist whether local engine runtimes should update automatically."""
        async with self._server_lifecycle_lock:
            self._config.auto_update = bool(enabled)
            await self._save_config()

    def check_llamacpp_installation(self) -> tuple[bool, str]:
        """Return whether llama.cpp is already installed locally."""
        return self._llamacpp_backend.check_llamacpp_installation()

    def check_llamacpp_installability(self) -> tuple[bool, str]:
        """Return whether the current environment can install llama.cpp."""
        return self._llamacpp_backend.check_llamacpp_installability()

    async def start_llamacpp_download(self) -> bool:
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

    async def auto_update_llamacpp(self) -> str:
        """Start a llama.cpp update only when it is safe to do so."""
        if not self._config.auto_update:
            return "disabled"
        if not self.check_llamacpp_installation()[0]:
            return "not-installed"
        if self._llamacpp_backend.get_server_status().get("running"):
            return "deferred"
        if self._llamacpp_backend.is_download_active():
            return "downloading"
        if not await self.has_update():
            return "up-to-date"
        await self.start_llamacpp_download()
        return "started"

    async def run_auto_update_once(self) -> dict[str, str]:
        """Check every installed engine once and install safe updates."""
        return {"llamacpp": await self.auto_update_llamacpp()}

    def start_auto_update(
        self,
        *,
        interval_seconds: float = 3600,
        initial_delay: float = 30,
    ) -> None:
        """Start the background auto-update loop when it is not running."""
        task = self._auto_update_task
        if task is not None and not task.done():
            return
        self._auto_update_task = asyncio.create_task(
            self._auto_update_loop(
                interval_seconds=interval_seconds,
                initial_delay=initial_delay,
            ),
            name="qwenpaw-local-runtime-auto-update",
        )

    async def stop_auto_update(self) -> None:
        """Stop the background auto-update loop."""
        task = self._auto_update_task
        self._auto_update_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _auto_update_loop(
        self,
        *,
        interval_seconds: float,
        initial_delay: float,
    ) -> None:
        """Periodically check for runtime updates without blocking startup."""
        try:
            await asyncio.sleep(max(0, initial_delay))
            while True:
                try:
                    await self.run_auto_update_once()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        "Local runtime auto-update check failed: %s",
                        exc,
                    )
                await asyncio.sleep(max(60, interval_seconds))
        except asyncio.CancelledError:
            raise

    async def check_llamacpp_server_ready(
        self,
        timeout: float = 120.0,
    ) -> bool:
        """Return whether the llama.cpp server is ready."""
        return await self._llamacpp_backend.server_ready(timeout=timeout)

    async def get_llamacpp_accelerator(self) -> dict[str, str | None]:
        """Return the accelerator backing the llama.cpp runtime."""
        try:
            return await self._llamacpp_backend.get_accelerator_info()
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to read llama.cpp accelerator: %s", exc)
            return {"accelerator": None, "device_name": None}

    async def get_llamacpp_version(self) -> str | None:
        """Return the installed llama.cpp runtime version, when available."""
        installed, _ = self.check_llamacpp_installation()
        if not installed:
            return None
        try:
            return await self._llamacpp_backend.get_version()
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to read llama.cpp version: %s", exc)
            return None

    def get_llamacpp_download_progress(self) -> dict[str, Any]:
        """Return the current llama.cpp download progress."""
        return self._llamacpp_backend.get_download_progress()

    def get_llamacpp_server_status(self) -> dict[str, Any]:
        """Return the current llama.cpp server status."""
        return self._llamacpp_backend.get_server_status()

    def is_llamacpp_server_transitioning(self) -> bool:
        """Return whether the llama.cpp server is starting or stopping."""
        return self._llamacpp_backend.is_server_transitioning()

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

    async def setup_server(
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
                gpu_acceleration=self._config.gpu_acceleration,
            )

    async def shutdown_server(self) -> None:
        """Stop the current llama.cpp server if it is running."""
        async with self._server_lifecycle_lock:
            await self._llamacpp_backend.shutdown_server()

    def shutdown_server_sync(self) -> None:
        """Best-effort synchronous shutdown for process teardown paths."""
        self._llamacpp_backend.shutdown_server_sync()

    @staticmethod
    def get_instance() -> LocalModelManager:
        """Return the singleton LocalModelManager instance."""
        # This is a simple module-level singleton pattern. In a more complex
        # application, you might want to use a dependency injection framework.
        if LocalModelManager._instance is None:
            LocalModelManager._instance = LocalModelManager()
        return LocalModelManager._instance
