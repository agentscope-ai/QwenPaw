# -*- coding: utf-8 -*-
"""Class-based local model downloader."""

from __future__ import annotations

import contextlib
import fnmatch
import importlib
import logging
import multiprocessing as mp
import os
import shutil
import uuid
from pathlib import Path
from queue import Empty
from typing import Any, Literal, Optional
from enum import Enum

import traceback
import httpx
from pydantic import Field

from .download_manager import (
    DownloadProgressTracker,
    DownloadProgressUpdate,
    ProcessDownloadTask,
    DownloadTaskResult,
    DownloadTaskStatus,
    ProcessDownloadController,
    ProcessDownloadTaskSpec,
)
from ..utils import system_info
from ..utils.stdio import ensure_standard_streams
from ..providers.provider import ModelInfo
from ..constant import DEFAULT_LOCAL_PROVIDER_DIR

logger = logging.getLogger(__name__)
PICCOLO_REPO_IDS = {
    f"{owner}/Piccolo-{size}B{suffix}"
    for owner in ("agentscope-ai", "AgentScope")
    for size in (4, 9, 27)
    for suffix in ("", "-BF16", "-Q8_0", "-Q4_K_M")
}
PICCOLO_DOWNLOAD_PATTERNS = [
    "*.gguf",
    "LICENSE",
    "README.md",
    "decision-inference.json",
]


class DownloadSource(str, Enum):
    HUGGINGFACE = "huggingface"
    MODELSCOPE = "modelscope"
    # First try Hugging Face, then fall back to ModelScope if unreachable
    AUTO = "auto"


def repository_for_source(repo_id: str, source: DownloadSource) -> str:
    """Resolve the official mirror while leaving third-party IDs intact."""
    owner, separator, name = repo_id.partition("/")
    if (
        separator
        and owner in {"agentscope-ai", "AgentScope"}
        and name.startswith(("Piccolo-", "QwenPaw-Flash-"))
        and source != DownloadSource.AUTO
    ):
        owner = (
            "AgentScope"
            if source == DownloadSource.MODELSCOPE
            else "agentscope-ai"
        )
        return f"{owner}/{name}"
    return repo_id


class LocalModelInfo(ModelInfo):
    """Metadata for a local model"""

    size_bytes: int = Field(
        ...,
        description="Model size in bytes, if known",
    )
    downloaded: bool = Field(
        default=False,
        description="Whether the model is fully downloaded and ready to use",
    )
    source: DownloadSource = Field(
        default=DownloadSource.AUTO,
        description="Preferred source to download the model from",
    )
    format: Literal["gguf", "mlx"] = Field(
        default="gguf",
        description="Model file format expected by the local engine",
    )
    local_path: str | None = Field(
        default=None,
        description="Absolute path to the downloaded model directory",
    )


class ModelManager:
    """A manager for downloading local models with progress tracking."""

    def __init__(
        self,
    ) -> None:
        self._context = mp.get_context("spawn")
        self._model_dir = DEFAULT_LOCAL_PROVIDER_DIR / "models"
        self._download_tmp_dir = DEFAULT_LOCAL_PROVIDER_DIR / "tmp"
        self._progress = DownloadProgressTracker()
        self._download_controller = ProcessDownloadController(
            context=self._context,
            progress=self._progress,
        )

    def get_recommended_models(
        self,
        engine: str = "llamacpp",
    ) -> list[LocalModelInfo]:
        """Recommend model names from the current machine capacity."""
        if engine == "mlx":
            return self._recommended_mlx_models()
        return self._recommended_llamacpp_models()

    def _recommended_llamacpp_models(self) -> list[LocalModelInfo]:
        """Recommend GGUF models for the llama.cpp engine."""
        memory_gb = self._detect_available_memory_gb()

        if memory_gb < 4:
            return []

        if memory_gb <= 8:
            models = [
                LocalModelInfo(
                    id="agentscope-ai/QwenPaw-Flash-2B-Q4_K_M",
                    name="QwenPaw-Flash-2B-Q4_K_M",
                    size_bytes=1560460768,
                    source=DownloadSource.HUGGINGFACE,
                ),
                LocalModelInfo(
                    id="agentscope-ai/QwenPaw-Flash-2B-Q8_0",
                    name="QwenPaw-Flash-2B-Q8_0",
                    size_bytes=2552356320,
                    source=DownloadSource.HUGGINGFACE,
                ),
            ]
        elif memory_gb <= 16:
            models = [
                LocalModelInfo(
                    id="agentscope-ai/QwenPaw-Flash-4B-Q4_K_M",
                    name="QwenPaw-Flash-4B-Q4_K_M",
                    size_bytes=3066384736,
                    source=DownloadSource.HUGGINGFACE,
                ),
                LocalModelInfo(
                    id="agentscope-ai/QwenPaw-Flash-4B-Q8_0",
                    name="QwenPaw-Flash-4B-Q8_0",
                    size_bytes=5157833056,
                    source=DownloadSource.HUGGINGFACE,
                ),
            ]
        else:
            models = [
                LocalModelInfo(
                    id="agentscope-ai/QwenPaw-Flash-9B-Q4_K_M",
                    name="QwenPaw-Flash-9B-Q4_K_M",
                    size_bytes=5476080128,
                    source=DownloadSource.HUGGINGFACE,
                ),
                LocalModelInfo(
                    id="agentscope-ai/QwenPaw-Flash-9B-Q8_0",
                    name="QwenPaw-Flash-9B-Q8_0",
                    size_bytes=10590617600,
                    source=DownloadSource.HUGGINGFACE,
                ),
            ]

        # Q4 may require a reduced context on smaller machines.
        if memory_gb >= 24:
            models.extend(
                [
                    LocalModelInfo(
                        id="agentscope-ai/QwenPaw-Flash-27B-Q4_K_M",
                        name="QwenPaw-Flash-27B-Q4_K_M",
                        size_bytes=16547398880,
                        source=DownloadSource.HUGGINGFACE,
                    ),
                    LocalModelInfo(
                        id="agentscope-ai/QwenPaw-Flash-35B-A3B-Q4_K_M",
                        name="QwenPaw-Flash-35B-A3B-Q4_K_M",
                        size_bytes=21166757824,
                        source=DownloadSource.HUGGINGFACE,
                    ),
                ],
            )
        if memory_gb >= 48:
            models.extend(
                [
                    LocalModelInfo(
                        id="agentscope-ai/QwenPaw-Flash-27B-Q8_0",
                        name="QwenPaw-Flash-27B-Q8_0",
                        size_bytes=28595762400,
                        source=DownloadSource.HUGGINGFACE,
                    ),
                    LocalModelInfo(
                        id="agentscope-ai/QwenPaw-Flash-35B-A3B-Q8_0",
                        name="QwenPaw-Flash-35B-A3B-Q8_0",
                        size_bytes=36903139264,
                        source=DownloadSource.HUGGINGFACE,
                    ),
                ],
            )

        for size, minimum_memory, weight_bytes in (
            (4, 16, 4482403872),
            (9, 24, 9527502656),
            (27, 48, 28595764992),
        ):
            if memory_gb >= minimum_memory:
                models.append(
                    LocalModelInfo(
                        id=f"agentscope-ai/Piccolo-{size}B-Q8_0",
                        name=f"Piccolo-{size}B-Q8_0",
                        model_type="decision",
                        size_bytes=weight_bytes,
                        source=DownloadSource.HUGGINGFACE,
                    ),
                )

        # Leave room for full-prompt attention and runtime buffers.
        for size, minimum_memory, weight_bytes in (
            (4, 24, 8424394496),
            (9, 32, 17920698400),
            (27, 80, 53808284096),
        ):
            if memory_gb >= minimum_memory:
                models.append(
                    LocalModelInfo(
                        id=f"agentscope-ai/Piccolo-{size}B-BF16",
                        name=f"Piccolo-{size}B-BF16",
                        model_type="decision",
                        size_bytes=weight_bytes,
                        source=DownloadSource.HUGGINGFACE,
                    ),
                )

        models.extend(
            model.model_copy(
                update={
                    "id": repository_for_source(
                        model.id,
                        DownloadSource.MODELSCOPE,
                    ),
                    "source": DownloadSource.MODELSCOPE,
                },
            )
            for model in list(models)
        )
        # Each mirror has its own stored ID and lifecycle controls.
        return self._with_download_state(models, engine="llamacpp")

    def _recommended_mlx_models(self) -> list[LocalModelInfo]:
        """Recommend 4-bit MLX models that fit unified memory."""
        memory_gb = self._detect_available_memory_gb()
        if memory_gb < 4:
            return []

        models = [
            LocalModelInfo(
                id="mlx-community/Qwen3-0.6B-4bit",
                name="Qwen3-0.6B-4bit",
                size_bytes=351386061,
                source=DownloadSource.HUGGINGFACE,
                format="mlx",
            ),
        ]
        if memory_gb > 8:
            models.append(
                LocalModelInfo(
                    id="mlx-community/Qwen3-4B-Instruct-2507-4bit",
                    name="Qwen3-4B-Instruct-2507-4bit",
                    size_bytes=2278972236,
                    source=DownloadSource.HUGGINGFACE,
                    format="mlx",
                ),
            )
        if memory_gb > 16:
            models.append(
                LocalModelInfo(
                    id="mlx-community/Qwen3-8B-4bit",
                    name="Qwen3-8B-4bit",
                    size_bytes=4623784971,
                    source=DownloadSource.HUGGINGFACE,
                    format="mlx",
                ),
            )
        if memory_gb > 32:
            models.append(
                LocalModelInfo(
                    id="mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit",
                    name="Qwen3-30B-A3B-Instruct-2507-4bit",
                    size_bytes=17197087380,
                    source=DownloadSource.HUGGINGFACE,
                    format="mlx",
                ),
            )
        return self._with_download_state(models, engine="mlx")

    def _with_download_state(
        self,
        models: list[LocalModelInfo],
        *,
        engine: str,
    ) -> list[LocalModelInfo]:
        """Attach local download state and paths to a catalog."""
        for model in models:
            model.downloaded = (
                self.is_downloaded(model.id, engine=engine)
                if engine == "mlx"
                else self.is_downloaded(model.id)
            )
            if model.downloaded:
                model.local_path = str(
                    self.get_model_dir(model.id).resolve(),
                )
        return models

    def _check_model_exists(
        self,
        model_id: str,
        engine: str = "llamacpp",
    ) -> bool:
        """Check whether a model directory matches the engine's format."""
        local_path = self.get_model_dir(model_id)
        if not local_path.exists():
            return False
        if engine == "mlx":
            return (local_path / "config.json").is_file() and any(
                local_path.glob("*.safetensors"),
            )
        return any(local_path.glob("*.gguf"))

    def get_model_dir(self, model_id: str) -> Path:
        """Get the expected local path for a given model id."""
        path = Path(model_id).expanduser()
        if path.is_absolute():
            return path
        return self._model_dir.joinpath(*model_id.split("/"))

    def is_downloaded(
        self,
        model_id: str,
        engine: str = "llamacpp",
    ) -> bool:
        """Check if a model id is already downloaded."""
        return self._check_model_exists(model_id, engine=engine)

    @staticmethod
    def _detect_model_format(directory: Path) -> str | None:
        """Return the local format stored in *directory*, when recognized."""
        if any(directory.rglob("*.gguf")):
            return "gguf"
        if (directory / "config.json").is_file() and any(
            directory.glob("*.safetensors"),
        ):
            return "mlx"
        return None

    def list_downloaded_models(
        self,
        engine: str | None = None,
    ) -> list[LocalModelInfo]:
        """Return downloaded local model repositories for one engine."""
        model_root = self._model_dir
        if not model_root.exists():
            return []

        models: list[LocalModelInfo] = []
        for entry in self._iter_downloaded_model_dirs():
            model_format = self._detect_model_format(entry)
            if model_format is None:
                continue
            if engine == "mlx" and model_format != "mlx":
                continue
            if engine == "llamacpp" and model_format != "gguf":
                continue
            repo_id = self._infer_repo_id_from_path(entry)
            size_bytes = self._calculate_downloaded_size(entry)
            is_piccolo = repo_id in PICCOLO_REPO_IDS
            models.append(
                LocalModelInfo(
                    id=repo_id,
                    name=(
                        repo_id.rsplit("/", maxsplit=1)[-1]
                        if is_piccolo or model_format == "mlx"
                        else repo_id
                    ),
                    model_type="decision" if is_piccolo else "chat",
                    source=(
                        DownloadSource.MODELSCOPE
                        if repo_id.startswith(
                            (
                                "AgentScope/Piccolo-",
                                "AgentScope/QwenPaw-Flash-",
                            ),
                        )
                        else (
                            DownloadSource.HUGGINGFACE
                            if repo_id.startswith(
                                ("agentscope-ai/", "mlx-community/"),
                            )
                            else DownloadSource.AUTO
                        )
                    ),
                    size_bytes=size_bytes,
                    downloaded=True,
                    format=model_format,
                    local_path=str(entry.resolve()),
                ),
            )

        return models

    def remove_downloaded_model(
        self,
        model_id: str,
        engine: str | None = None,
    ) -> None:
        """Delete a downloaded local model by repo id or directory name."""
        model_path = self.get_model_dir(model_id)
        if model_path.exists():
            self._cleanup_path(model_path)
            self._cleanup_empty_parent_dirs(model_path.parent)
            return

        raise ValueError(f"Downloaded local model not found: {model_id}")

    def start_download(
        self,
        model_id: str,
        source: DownloadSource | None = None,
        engine: str = "llamacpp",
    ) -> None:
        """Start downloading the selected model into the target directory."""
        logger.info(
            "Starting %s download for [%s] %s",
            engine,
            source,
            model_id,
        )
        if self._is_download_active():
            raise RuntimeError("A model download is already in progress.")

        resolved_source = (
            self._resolve_download_source()
            if source is None or source == DownloadSource.AUTO
            else source
        )
        if engine == "mlx" and resolved_source != DownloadSource.HUGGINGFACE:
            raise ValueError(
                "MLX models can only be downloaded from Hugging Face.",
            )
        repo_id = repository_for_source(model_id, resolved_source)
        final_dir = Path(self.get_model_dir(repo_id)).expanduser().resolve()
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        self._download_tmp_dir.mkdir(parents=True, exist_ok=True)
        model_format = "mlx" if engine == "mlx" else "gguf"
        total_bytes = self._estimate_download_size(
            repo_id=repo_id,
            source=resolved_source,
            model_format=model_format,
        )
        has_files, error_msg = self._check_model_files_exist(
            repo_id=repo_id,
            source=resolved_source,
            model_format="mlx" if engine == "mlx" else "gguf",
        )
        if not has_files:
            raise ValueError(error_msg)

        task_id = uuid.uuid4().hex
        staging_dir = self._download_tmp_dir / task_id
        payload = {
            "repo_id": repo_id,
            "source": resolved_source.value,
            "staging_dir": str(staging_dir),
        }
        if engine == "mlx":
            payload["model_format"] = "mlx"
        spec = ProcessDownloadTaskSpec(
            process_name=f"qwenpaw-model-download-{task_id}",
            command=[
                "qwenpaw-model-download",
                repo_id,
                resolved_source.value,
            ],
            task=ProcessDownloadTask(
                target=type(self)._download_worker,
                payload=payload,
                progress_probe=lambda: DownloadProgressUpdate(
                    downloaded_bytes=self._calculate_downloaded_size(
                        staging_dir,
                    ),
                    total_bytes=total_bytes,
                    model_name=repo_id,
                    source=resolved_source.value,
                ),
                finalize_result=lambda result: self._finalize_download_result(
                    result,
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                ),
                cleanup=lambda: self._cleanup_path(staging_dir),
            ),
            model_name=repo_id,
            source=resolved_source.value,
            total_bytes=total_bytes,
        )
        self._download_controller.start(spec)

    def download_model(
        self,
        model_id: str,
        source: DownloadSource | None = None,
        engine: str = "llamacpp",
    ) -> None:
        if engine == "llamacpp":
            self.start_download(model_id, source=source)
        else:
            self.start_download(model_id, source=source, engine=engine)

    def get_download_progress(self) -> dict[str, Any]:
        """Return the current download progress."""
        return self._download_controller.snapshot()

    def cancel_download(self) -> None:
        """Cancel the current download task."""
        self._download_controller.cancel()

    def _is_download_active(self) -> bool:
        """Return whether a download process is still active."""
        return self._download_controller.is_active()

    def _finalize_download_result(
        self,
        result: DownloadTaskResult,
        *,
        staging_dir: Path,
        final_dir: Path,
    ) -> tuple[DownloadTaskResult, int | None]:
        if result.status != DownloadTaskStatus.COMPLETED:
            return result, None
        local_path = self._promote_staging_directory(
            staging_dir=staging_dir,
            final_dir=final_dir,
            local_path=Path(result.local_path or staging_dir),
        )
        downloaded_bytes = self._calculate_downloaded_size(final_dir)
        return (
            DownloadTaskResult(
                status=result.status,
                local_path=str(local_path),
            ),
            downloaded_bytes,
        )

    def _resolve_download_source(self) -> DownloadSource:
        """Choose Hugging Face when reachable, otherwise use ModelScope."""
        if self._probe_huggingface():
            return DownloadSource.HUGGINGFACE
        return DownloadSource.MODELSCOPE

    def _estimate_download_size(
        self,
        repo_id: str,
        source: DownloadSource,
        model_format: str = "gguf",
    ) -> Optional[int]:
        """Best-effort total byte estimation for progress."""
        if model_format == "gguf":
            if source == DownloadSource.HUGGINGFACE:
                return self._estimate_huggingface_size(repo_id=repo_id)
            return self._estimate_modelscope_size(repo_id=repo_id)
        if source == DownloadSource.HUGGINGFACE:
            return self._estimate_huggingface_size(
                repo_id=repo_id,
                model_format=model_format,
            )
        return self._estimate_modelscope_size(
            repo_id=repo_id,
            model_format=model_format,
        )

    def _check_model_files_exist(
        self,
        repo_id: str,
        source: DownloadSource,
        model_format: str = "gguf",
    ) -> tuple[bool, str]:
        """Return whether the remote repository matches the engine format."""
        if model_format == "gguf":
            return self._check_gguf_exists(repo_id=repo_id, source=source)
        if source == DownloadSource.HUGGINGFACE:
            return self._check_huggingface_model_files(
                repo_id=repo_id,
                model_format=model_format,
            )
        return self._check_modelscope_model_files(
            repo_id=repo_id,
            model_format=model_format,
        )

    def _check_gguf_exists(
        self,
        repo_id: str,
        source: DownloadSource,
    ) -> tuple[bool, str]:
        """Backwards-compatible GGUF-only repository check."""
        if source == DownloadSource.HUGGINGFACE:
            return self._check_huggingface_gguf_exists(repo_id)
        return self._check_modelscope_gguf_exists(repo_id)

    def _check_huggingface_gguf_exists(
        self,
        repo_id: str,
    ) -> tuple[bool, str]:
        """Backwards-compatible GGUF check for Hugging Face."""
        return self._check_huggingface_model_files(repo_id, "gguf")

    def _check_modelscope_gguf_exists(
        self,
        repo_id: str,
    ) -> tuple[bool, str]:
        """Backwards-compatible GGUF check for ModelScope."""
        return self._check_modelscope_model_files(repo_id, "gguf")

    @staticmethod
    def _download_worker(payload: dict[str, Any], queue: Any) -> None:
        """Run the blocking SDK download in a child process."""
        ensure_standard_streams()
        repo_id = payload["repo_id"]
        source = DownloadSource(payload["source"])
        model_format = payload.get("model_format", "gguf")
        staging_dir = Path(payload["staging_dir"]).expanduser().resolve()

        try:
            ModelManager._cleanup_path(staging_dir)
            staging_dir.mkdir(parents=True, exist_ok=True)
            if model_format == "gguf":
                local_path = ModelManager._download_to_directory(
                    repo_id=repo_id,
                    source=source,
                    local_dir=staging_dir,
                )
            else:
                local_path = ModelManager._download_to_directory(
                    repo_id=repo_id,
                    source=source,
                    local_dir=staging_dir,
                    model_format=model_format,
                )
        except Exception:
            queue.put(
                DownloadTaskResult(
                    status=DownloadTaskStatus.FAILED,
                    error="Download failed: " + traceback.format_exc(),
                ).to_message(),
            )
            logger.error(
                "Error when downloading model [%s]:\n%s",
                repo_id,
                traceback.format_exc(),
            )
            raise
        queue.put(
            DownloadTaskResult(
                status=DownloadTaskStatus.COMPLETED,
                local_path=str(Path(local_path).resolve()),
            ).to_message(),
        )

    @staticmethod
    def _download_to_directory(
        repo_id: str,
        source: DownloadSource,
        local_dir: Path,
        model_format: str = "gguf",
    ) -> str:
        """Download a model into the target directory."""
        if model_format == "gguf":
            if source == DownloadSource.HUGGINGFACE:
                return ModelManager._download_from_huggingface(
                    repo_id=repo_id,
                    local_dir=local_dir,
                )
            return ModelManager._download_from_modelscope(
                repo_id=repo_id,
                local_dir=local_dir,
            )
        if source == DownloadSource.HUGGINGFACE:
            return ModelManager._download_from_huggingface(
                repo_id=repo_id,
                local_dir=local_dir,
                model_format=model_format,
            )
        return ModelManager._download_from_modelscope(
            repo_id=repo_id,
            local_dir=local_dir,
            model_format=model_format,
        )

    @staticmethod
    def _download_from_huggingface(
        repo_id: str,
        local_dir: Path,
        model_format: str = "gguf",
    ) -> str:
        """Download a model repository from Hugging Face Hub."""
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ImportError(
                "huggingface_hub is required for Hugging Face downloads.",
            ) from exc

        kwargs = {}
        if model_format == "mlx":
            kwargs["ignore_patterns"] = [
                "*.gguf",
                "original/*",
                "*.pth",
                "*.bin",
                "*.msgpack",
            ]
        elif repo_id in PICCOLO_REPO_IDS:
            # Fetch only GGUF/runtime metadata, including for legacy base IDs.
            kwargs["allow_patterns"] = PICCOLO_DOWNLOAD_PATTERNS
        return snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
            **kwargs,
        )

    @staticmethod
    def _download_from_modelscope(
        repo_id: str,
        local_dir: Path,
        model_format: str = "gguf",
    ) -> str:
        """Download a model repository from ModelScope."""
        options = {}
        if model_format == "mlx":
            options["ignore_file_pattern"] = ["*.gguf", "original/*"]
        elif repo_id in PICCOLO_REPO_IDS:
            options["allow_file_pattern"] = PICCOLO_DOWNLOAD_PATTERNS
        with open(
            os.devnull,
            "a",
            encoding="utf-8",
            buffering=1,
            errors="replace",
        ) as sink_stream:
            with (
                contextlib.redirect_stdout(
                    sink_stream,
                ),
                contextlib.redirect_stderr(sink_stream),
            ):
                return ModelManager._get_modelscope_snapshot_download()(
                    model_id=repo_id,
                    local_dir=str(local_dir),
                    **options,
                )

    def _estimate_huggingface_size(
        self,
        repo_id: str,
        model_format: str = "gguf",
    ) -> Optional[int]:
        """Estimate total download bytes from Hugging Face metadata."""
        try:
            from huggingface_hub import HfApi
        except ImportError:
            return None

        try:
            info = HfApi().repo_info(
                repo_id=repo_id,
                repo_type="model",
                files_metadata=True,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return None

        siblings = getattr(info, "siblings", None) or []
        total = 0
        found = False
        for sibling in siblings:
            name = getattr(sibling, "rfilename", None)
            size = getattr(sibling, "size", None)
            if not isinstance(name, str) or not isinstance(size, int):
                continue
            if name.startswith("."):
                continue
            if model_format == "mlx":
                if name.endswith((".gguf", ".pth", ".bin", ".msgpack")):
                    continue
                if name.startswith("original/"):
                    continue
            elif repo_id in PICCOLO_REPO_IDS and not any(
                fnmatch.fnmatch(name, pattern)
                for pattern in PICCOLO_DOWNLOAD_PATTERNS
            ):
                continue
            total += size
            found = True
        return total if found else None

    def _estimate_modelscope_size(
        self,
        repo_id: str,
        model_format: str = "gguf",
    ) -> Optional[int]:
        """Estimate total download bytes from ModelScope metadata."""
        try:
            hub_api_module = importlib.import_module("modelscope.hub.api")
        except ImportError:
            return None

        try:
            files = hub_api_module.HubApi().get_model_files(
                repo_id,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return None

        total = 0
        found = False
        for item in files:
            if not isinstance(item, dict):
                continue
            name = item.get("Path") or item.get("Name") or ""
            if model_format == "mlx":
                if name.endswith((".gguf", ".pth", ".bin", ".msgpack")):
                    continue
                if name.startswith("original/"):
                    continue
            elif repo_id in PICCOLO_REPO_IDS and not any(
                fnmatch.fnmatch(name, pattern)
                for pattern in PICCOLO_DOWNLOAD_PATTERNS
            ):
                continue
            size = item.get("Size")
            if isinstance(size, int):
                total += size
                found = True
        return total if found else None

    @staticmethod
    def _missing_model_message(repo_id: str, model_format: str) -> str:
        if model_format == "mlx":
            return (
                f"{repo_id} is not an MLX model repository: it must contain "
                "config.json and safetensors weights."
            )
        return (
            f"{repo_id} is not supported by Llama.cpp because it does "
            "not contain any .gguf files."
        )

    def _check_huggingface_model_files(
        self,
        repo_id: str,
        model_format: str = "gguf",
    ) -> tuple[bool, str]:
        try:
            from huggingface_hub import HfApi
            from huggingface_hub.errors import RepositoryNotFoundError
        except ImportError:
            return False, "`huggingface_hub` is not installed"
        try:
            files = HfApi().list_repo_files(repo_id=repo_id)
            if model_format == "mlx":
                has_model = "config.json" in files and any(
                    name.endswith(".safetensors") for name in files
                )
            else:
                has_model = any(name.endswith(".gguf") for name in files)
            if has_model:
                return True, ""
            return (
                False,
                self._missing_model_message(repo_id, model_format),
            )
        except RepositoryNotFoundError:
            return False, f"Repository {repo_id} not found"
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            return False, f"Error when checking repository: {e}"

    def _check_modelscope_model_files(
        self,
        repo_id: str,
        model_format: str = "gguf",
    ) -> tuple[bool, str]:
        try:
            hub_api_module = importlib.import_module("modelscope.hub.api")
        except ImportError:
            return False, "`modelscope` is not installed"
        try:
            files = hub_api_module.HubApi().get_model_files(repo_id)
        except (OSError, RuntimeError, TypeError, ValueError):
            return False, f"Failed to fetch info from {repo_id}"

        names = [
            (f.get("Name", "") or f.get("Path", ""))
            for f in files
            if isinstance(f, dict)
        ]
        if model_format == "mlx":
            has_model = "config.json" in names and any(
                name.endswith(".safetensors") for name in names
            )
        else:
            has_model = any(name.endswith(".gguf") for name in names)
        if has_model:
            return True, ""
        return (
            False,
            self._missing_model_message(repo_id, model_format),
        )

    def _detect_available_memory_gb(self) -> float:
        """Prefer VRAM when available, otherwise use system memory."""
        gpu_memory_gb = system_info.get_vram_size_gb()
        if gpu_memory_gb > 0:
            return gpu_memory_gb
        return system_info.get_memory_size_gb()

    def _probe_huggingface(self) -> bool:
        """Return whether Hugging Face is reachable from this machine."""
        try:
            response = httpx.get(
                "https://huggingface.co",
                follow_redirects=True,
                timeout=5,
            )
        except httpx.HTTPError:
            return False
        return response.status_code < 500

    @staticmethod
    def _get_modelscope_snapshot_download() -> Any:
        """Return a compatible ModelScope snapshot downloader."""
        try:
            snapshot_module = importlib.import_module(
                "modelscope.hub.snapshot_download",
            )
            return snapshot_module.snapshot_download
        except ImportError:
            try:
                modelscope_module = importlib.import_module("modelscope")
                return modelscope_module.snapshot_download
            except ImportError as exc:
                raise ImportError(
                    "ModelScope snapshot download is required.",
                ) from exc

    @staticmethod
    def _drain_queue_message(queue: Any) -> Optional[dict[str, Any]]:
        """Return the latest worker message, if available."""
        if queue is None:
            return None

        latest = None
        while True:
            try:
                latest = queue.get_nowait()
            except Empty:
                return latest

    @staticmethod
    def _calculate_downloaded_size(path: Path) -> int:
        """Compute currently materialized bytes on disk."""
        if not path.exists():
            return 0
        if path.is_file():
            return path.stat().st_size
        return sum(
            entry.stat().st_size
            for entry in path.rglob("*")
            if entry.is_file()
        )

    @staticmethod
    def _promote_staging_directory(
        staging_dir: Path,
        final_dir: Path,
        local_path: Path,
    ) -> Path:
        """Move a finished staged download into the final directory."""
        if final_dir.exists():
            shutil.rmtree(final_dir)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging_dir), str(final_dir))

        if local_path == staging_dir:
            return final_dir
        return final_dir / local_path.relative_to(staging_dir)

    @staticmethod
    def _cleanup_path(path: Path) -> None:
        """Delete a file or directory if it exists."""
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            return
        path.unlink(missing_ok=True)

    def _iter_downloaded_model_dirs(self) -> list[Path]:
        candidates: list[Path] = []
        entries = sorted(
            self._model_dir.rglob("*"),
            key=lambda item: item.parts,
        )
        for entry in entries:
            if not entry.is_dir():
                continue
            if self._is_temporary_download_dir(entry):
                continue
            if self._detect_model_format(entry) is None:
                continue
            if not self._looks_like_model_root(entry):
                continue
            candidates.append(entry)

        selected: list[Path] = []
        for candidate in sorted(candidates, key=lambda item: len(item.parts)):
            if any(candidate.is_relative_to(parent) for parent in selected):
                continue
            selected.append(candidate)
        return selected

    def _is_temporary_download_dir(self, path: Path) -> bool:
        relative_parts = path.relative_to(self._model_dir).parts
        return any(
            part.startswith(".") or part.endswith(".downloading")
            for part in relative_parts
        )

    def _looks_like_model_root(self, path: Path) -> bool:
        visible_children = [
            child for child in path.iterdir() if not child.name.startswith(".")
        ]
        return any(not child.is_dir() for child in visible_children)

    def _infer_repo_id_from_path(self, model_dir: Path) -> str:
        relative_path = model_dir.relative_to(self._model_dir)
        return "/".join(relative_path.parts)

    def _cleanup_empty_parent_dirs(self, path: Path) -> None:
        if not path.resolve().is_relative_to(self._model_dir.resolve()):
            return
        while path != self._model_dir and path.exists():
            if any(path.iterdir()):
                return
            path.rmdir()
            path = path.parent
