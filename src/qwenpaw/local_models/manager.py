# -*- coding: utf-8 -*-
"""Facade for local inference engines and model download management."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..constant import DEFAULT_LOCAL_PROVIDER_DIR
from ..providers.provider import ModelInfo

from .llamacpp import LlamaCppBackend
from .mlx import MlxBackend
from .model_manager import LocalModelInfo as RecommendedLocalModelInfo
from .model_manager import ModelManager, DownloadSource
from .runtime_release import RELEASE

logger = logging.getLogger(__name__)

LocalEngineId = Literal["llamacpp", "mlx"]
LOCAL_ENGINE_IDS: tuple[str, ...] = ("llamacpp", "mlx")
DEFAULT_LOCAL_ENGINE: LocalEngineId = "llamacpp"


class LocalModelConfig(BaseModel):
    """Persistent local runtime settings shared by all local engines."""

    max_context_length: int = Field(
        default=65536,
        description="Maximum context length passed to llama.cpp on startup.",
        ge=32768,
    )
    port: int | None = Field(
        default=None,
        description=(
            "Optional fixed port for local engine startup. Null means auto."
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
    engine: LocalEngineId = Field(
        default=DEFAULT_LOCAL_ENGINE,
        description="Last local engine used for model serving.",
    )


class LocalServerSetupResult(BaseModel):
    """Runtime information for a started local engine server."""

    port: int
    model_info: ModelInfo
    engine: str = DEFAULT_LOCAL_ENGINE
    stopped_engine: str | None = None


def _accepts_keyword(method: Any, keyword: str) -> bool:
    """Return whether *method* accepts *keyword* (for plugin compatibility)."""
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False
    return keyword in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def normalize_engine(engine: str | None) -> str:
    """Validate an engine id, defaulting to llama.cpp for legacy clients."""
    value = (engine or DEFAULT_LOCAL_ENGINE).strip().lower()
    if value not in LOCAL_ENGINE_IDS:
        raise ValueError(f"Unsupported local engine: {engine}")
    return value


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
        mlx_backend: MlxBackend | None = None,
    ) -> None:
        self._model_manager = model_manager or ModelManager()
        self._llamacpp_backend = llamacpp_backend or LlamaCppBackend()
        self._mlx_backend = mlx_backend or MlxBackend()
        self._backends: dict[str, Any] = {
            "llamacpp": self._llamacpp_backend,
            "mlx": self._mlx_backend,
        }
        self._server_lifecycle_lock = asyncio.Lock()
        self._config_path = DEFAULT_LOCAL_PROVIDER_DIR / self.CONFIG_FILE_NAME
        self._config = self._load_config()

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
        """Persist the max context length for future engine startups."""
        async with self._server_lifecycle_lock:
            self._config.max_context_length = max_context_length
            await self._save_config()

    async def set_port(self, port: int | None) -> None:
        """Persist the local engine server port for future startups."""
        async with self._server_lifecycle_lock:
            self._config.port = port
            await self._save_config()

    async def set_gpu_acceleration(self, enabled: bool) -> None:
        """Persist whether llama.cpp should offload layers to the GPU."""
        async with self._server_lifecycle_lock:
            self._config.gpu_acceleration = bool(enabled)
            await self._save_config()

    # -----------------------------
    # Engine metadata
    # -----------------------------
    @staticmethod
    def list_engines() -> list[str]:
        """Return the supported local engine ids."""
        return list(LOCAL_ENGINE_IDS)

    def get_backend(self, engine: str | None = None) -> Any:
        """Return the backend for *engine*."""
        return self._backends[normalize_engine(engine)]

    def check_installation(
        self,
        engine: str | None = None,
    ) -> tuple[bool, str]:
        """Return whether the selected engine runtime is installed."""
        backend = self.get_backend(engine)
        check = getattr(backend, "check_installation", None)
        if check is None:
            check = getattr(backend, "check_llamacpp_installation")
        return check()

    def check_installability(
        self,
        engine: str | None = None,
    ) -> tuple[bool, str]:
        """Return whether this machine can install the selected engine."""
        backend = self.get_backend(engine)
        check = getattr(backend, "check_installability", None)
        if check is None:
            check = getattr(backend, "check_llamacpp_installability")
        return check()

    def get_engine_download_progress(
        self,
        engine: str | None = None,
    ) -> dict[str, Any]:
        """Return the selected engine's runtime install progress."""
        return self.get_backend(engine).get_download_progress()

    def get_engine_server_status(
        self,
        engine: str | None = None,
    ) -> dict[str, Any]:
        """Return the selected engine's server status."""
        return self.get_backend(engine).get_server_status()

    def is_engine_transitioning(self, engine: str | None = None) -> bool:
        """Return whether the selected engine is starting or stopping."""
        backend = self.get_backend(engine)
        check = getattr(backend, "is_server_transitioning", None)
        return bool(check()) if check is not None else False

    def is_model_serving(
        self,
        model_id: str,
        engine: str | None = None,
    ) -> bool:
        """Return whether the selected engine is serving *model_id*."""
        served = self.get_engine_server_status(engine).get("model_name")
        if not served:
            return False
        if served == model_id:
            return True
        try:
            return (
                Path(served).resolve()
                == self._model_manager.get_model_dir(model_id).resolve()
            )
        except (OSError, ValueError):
            return False

    def cancel_engine_download(self, engine: str | None = None) -> None:
        """Cancel the selected engine's runtime install."""
        self.get_backend(engine).cancel_download()

    async def check_server_ready(
        self,
        engine: str | None = None,
        timeout: float = 120.0,
    ) -> bool:
        """Return whether the selected engine server is responding."""
        return await self.get_backend(engine).server_ready(timeout=timeout)

    async def get_engine_version(
        self,
        engine: str | None = None,
    ) -> str | None:
        """Return the installed runtime version, when available."""
        backend = self.get_backend(engine)
        installed, _ = self.check_installation(engine)
        if not installed:
            return None
        get_version = getattr(backend, "get_version", None)
        if get_version is None:
            return None
        try:
            return await get_version()
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to read %s version: %s", engine, exc)
            return None

    async def get_engine_accelerator(
        self,
        engine: str | None = None,
    ) -> dict[str, str | None]:
        """Return the accelerator backing the selected engine."""
        backend = self.get_backend(engine)
        get_info = getattr(backend, "get_accelerator_info", None)
        if get_info is None:
            return {"accelerator": None, "device_name": None}
        try:
            return await get_info()
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to read %s accelerator: %s", engine, exc)
            return {"accelerator": None, "device_name": None}

    async def get_engine_status(
        self,
        engine: str | None = None,
    ) -> dict[str, Any]:
        """Return install, runtime, and accelerator state for one engine."""
        engine_id = normalize_engine(engine)
        backend = self._backends[engine_id]
        installable, install_message = self.check_installability(engine_id)
        installed, install_state_message = self.check_installation(engine_id)
        state = backend.get_server_status()
        accelerator = await self.get_engine_accelerator(engine_id)
        return {
            "id": engine_id,
            "name": "MLX" if engine_id == "mlx" else "llama.cpp",
            "installable": installable,
            "installed": installed,
            "running": bool(state["running"]),
            "available": bool(state["running"]),
            "port": state["port"],
            "model_name": state["model_name"],
            "message": (
                install_message
                if not installable
                else install_state_message or None
            ),
            "accelerator": accelerator["accelerator"],
            "device_name": accelerator["device_name"],
            "version": await self.get_engine_version(engine_id),
        }

    async def has_engine_update(self, engine: str | None = None) -> bool:
        """Return whether a newer runtime is available for the engine."""
        engine_id = normalize_engine(engine)
        backend = self._backends[engine_id]
        if engine_id == "mlx":
            # The MLX runtime is pinned; updates ship with QwenPaw releases.
            return False
        return await backend.has_update(self.DEFAULT_LLAMA_CPP_RELEASE_TAG)

    async def start_engine_download(self, engine: str | None = None) -> bool:
        """Install the engine runtime; return whether a server was stopped."""
        engine_id = normalize_engine(engine)
        backend = self._backends[engine_id]
        async with self._server_lifecycle_lock:
            server_was_running = bool(
                backend.get_server_status().get("running"),
            )
            if server_was_running:
                await backend.shutdown_server()

            if engine_id == "llamacpp":
                backend.download(
                    self.DEFAULT_LLAMA_CPP_BASE_URL,
                    self.DEFAULT_LLAMA_CPP_RELEASE_TAG,
                )
            else:
                backend.start_download()
            return server_was_running

    # -----------------------------
    # llama.cpp compatibility API
    # -----------------------------
    def check_llamacpp_installation(self) -> tuple[bool, str]:
        """Return whether llama.cpp is already installed locally."""
        return self.check_installation("llamacpp")

    def check_llamacpp_installability(self) -> tuple[bool, str]:
        """Return whether the current environment can install llama.cpp."""
        return self.check_installability("llamacpp")

    async def start_llamacpp_download(self) -> bool:
        """Start the llama.cpp binary download task."""
        return await self.start_engine_download("llamacpp")

    async def has_update(self) -> bool:
        """Return whether a llama.cpp update is available for download."""
        return await self.has_engine_update("llamacpp")

    async def check_llamacpp_server_ready(
        self,
        timeout: float = 120.0,
    ) -> bool:
        """Return whether the llama.cpp server is ready."""
        return await self._llamacpp_backend.server_ready(timeout=timeout)

    def get_llamacpp_download_progress(self) -> dict[str, Any]:
        """Return the current llama.cpp download progress."""
        return self.get_engine_download_progress("llamacpp")

    def get_llamacpp_server_status(self) -> dict[str, Any]:
        """Return the current llama.cpp server status."""
        return self.get_engine_server_status("llamacpp")

    def is_llamacpp_server_transitioning(self) -> bool:
        """Return whether the llama.cpp server is starting or stopping."""
        return self.is_engine_transitioning("llamacpp")

    def cancel_llamacpp_download(self) -> None:
        """Cancel the current llama.cpp download task."""
        self.cancel_engine_download("llamacpp")

    # -----------------------------
    # Models
    # -----------------------------
    def get_recommended_models(
        self,
        engine: str | None = None,
    ) -> list[RecommendedLocalModelInfo]:
        """Return recommended local models for the current machine."""
        engine_id = normalize_engine(engine)
        method = self._model_manager.get_recommended_models
        if _accepts_keyword(method, "engine"):
            return method(engine=engine_id)
        return method()

    def is_model_downloaded(
        self,
        model_name: str,
        engine: str | None = None,
    ) -> bool:
        """Return whether the requested model is already downloaded."""
        engine_id = normalize_engine(engine)
        method = self._model_manager.is_downloaded
        if _accepts_keyword(method, "engine"):
            return method(model_name, engine=engine_id)
        return method(model_name)

    def list_downloaded_models(
        self,
        engine: str | None = None,
    ) -> list[RecommendedLocalModelInfo]:
        """Return downloaded local models for the selected engine."""
        engine_id = normalize_engine(engine)
        method = self._model_manager.list_downloaded_models
        if _accepts_keyword(method, "engine"):
            return method(engine=engine_id)
        return method()

    def start_model_download(
        self,
        model_id: str,
        source: DownloadSource | None = None,
        engine: str | None = None,
    ) -> None:
        """Start downloading the requested model."""
        engine_id = normalize_engine(engine)
        method = self._model_manager.download_model
        if _accepts_keyword(method, "engine"):
            method(model_id, source=source, engine=engine_id)
        else:
            method(model_id, source=source)

    def get_model_download_progress(self) -> dict[str, Any]:
        """Return the current model download progress."""
        return self._model_manager.get_download_progress()

    def cancel_model_download(self) -> None:
        """Cancel the current model download task."""
        self._model_manager.cancel_download()

    def remove_downloaded_model(
        self,
        model_id: str,
        engine: str | None = None,
    ) -> None:
        """Delete a downloaded local model by repo id or directory name."""
        engine_id = normalize_engine(engine)
        method = self._model_manager.remove_downloaded_model
        if _accepts_keyword(method, "engine"):
            method(model_id, engine=engine_id)
        else:
            method(model_id)

    # -----------------------------
    # Server lifecycle
    # -----------------------------
    async def setup_server(
        self,
        model_id: str,
        engine: str | None = None,
    ) -> LocalServerSetupResult:
        """Start the selected engine for the specified model."""
        engine_id = normalize_engine(engine)
        backend = self._backends[engine_id]
        if not self.is_model_downloaded(model_id, engine=engine_id):
            raise FileNotFoundError(
                f"Local model is not downloaded: {model_id}",
            )
        async with self._server_lifecycle_lock:
            stopped_engine: str | None = None
            for other_id, other_backend in self._backends.items():
                if other_id == engine_id:
                    continue
                if other_backend.get_server_status().get("running"):
                    await other_backend.shutdown_server()
                    stopped_engine = other_id

            previous_engine = self._config.engine
            try:
                setup_kwargs: dict[str, Any] = {
                    "model_path": self._model_manager.get_model_dir(model_id),
                    "model_name": model_id,
                    "max_context_length": self._config.max_context_length,
                    "port": self._config.port,
                }
                if engine_id == "llamacpp" and _accepts_keyword(
                    backend.setup_server,
                    "gpu_acceleration",
                ):
                    setup_kwargs[
                        "gpu_acceleration"
                    ] = self._config.gpu_acceleration
                result = await backend.setup_server(**setup_kwargs)
            except Exception:
                self._config.engine = previous_engine
                raise

            self._config.engine = engine_id
            await self._save_config()
            return LocalServerSetupResult(
                port=result.port,
                model_info=result.model_info,
                engine=engine_id,
                stopped_engine=stopped_engine,
            )

    async def shutdown_server(self, engine: str | None = None) -> None:
        """Stop the selected engine, or every engine when *engine* is None."""
        async with self._server_lifecycle_lock:
            if engine is not None:
                await self._backends[
                    normalize_engine(engine)
                ].shutdown_server()
                return
            for backend in self._backends.values():
                await backend.shutdown_server()

    def shutdown_server_sync(self) -> None:
        """Best-effort synchronous shutdown for process teardown paths."""
        for backend in self._backends.values():
            backend.shutdown_server_sync()
            shutdown_install = getattr(backend, "shutdown_install_sync", None)
            if callable(shutdown_install):
                shutdown_install()

    @staticmethod
    def get_instance() -> LocalModelManager:
        """Return the singleton LocalModelManager instance."""
        if LocalModelManager._instance is None:
            LocalModelManager._instance = LocalModelManager()
        return LocalModelManager._instance
