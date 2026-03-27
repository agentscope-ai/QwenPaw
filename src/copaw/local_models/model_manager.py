# -*- coding: utf-8 -*-
"""Class-based local model downloader."""

from __future__ import annotations

import importlib
import logging
import multiprocessing as mp
import shutil
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from queue import Empty
from typing import Any, Optional

import httpx
from pydantic import Field

from ..utils import system_info
from .schema import DownloadSource
from ..providers.provider import ModelInfo
from ..constant import DEFAULT_LOCAL_PROVIDER_DIR

logger = logging.getLogger(__name__)


class DownloadTaskStatus(str, Enum):
    """Download lifecycle for a single downloader instance."""

    IDLE = "idle"
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


class ModelManager:
    """A manager for downloading local models with progress tracking."""

    def __init__(
        self,
    ) -> None:
        self._context = mp.get_context("spawn")
        self._lock = threading.Lock()
        self._process: Optional[Any] = None
        self._queue: Optional[Any] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._staging_dir: Optional[Path] = None
        self._final_dir: Optional[Path] = None
        self._resolved_source: Optional[DownloadSource] = None
        self._last_size_sample = 0
        self._last_sample_time = time.monotonic()
        self._model_dir = DEFAULT_LOCAL_PROVIDER_DIR / "models"
        self._progress: dict[str, Any] = {
            "status": DownloadTaskStatus.IDLE.value,
            "downloaded_bytes": 0,
            "total_bytes": None,
            "speed_bytes_per_sec": 0.0,
            "source": None,
            "error": None,
            "local_path": None,
        }

    def get_recommended_models(self) -> list[LocalModelInfo] | None:
        """Recommend model names from the current machine capacity."""
        memory_gb = self._detect_available_memory_gb()

        if memory_gb < 4:
            return None

        if memory_gb <= 8:
            models = [
                LocalModelInfo(
                    id="CoPaw-flash-2B-Q4_K_M",
                    name="AgentScope/CoPaw-flash-2B-Q4_K_M",
                    size_bytes=1560460768,
                ),
                LocalModelInfo(
                    id="Copaw-2B-Q8_0",
                    name="AgentScope/CoPaw-flash-2B-Q8_0",
                    size_bytes=2552356320,
                ),
            ]
        elif memory_gb <= 16:
            models = [
                LocalModelInfo(
                    id="CoPaw-flash-4B-Q4_K_M",
                    name="AgentScope/CoPaw-flash-4B-Q4_K_M",
                    size_bytes=3066384736,
                ),
                LocalModelInfo(
                    id="CoPaw-flash-4B-Q8_0",
                    name="AgentScope/CoPaw-flash-4B-Q8_0",
                    size_bytes=5157833056,
                ),
            ]
        else:
            models = [
                LocalModelInfo(
                    id="CoPaw-flash-9B-Q4_K_M",
                    name="AgentScope/CoPaw-flash-9B-Q4_K_M",
                    size_bytes=5476080128,
                ),
                LocalModelInfo(
                    id="CoPaw-flash-9B-Q8_0",
                    name="AgentScope/CoPaw-flash-9B-Q8_0",
                    size_bytes=10590617600,
                ),
            ]

        # check local download status for each recommended model
        for model in models:
            model.downloaded = self.is_downloaded(model.name)

        return models

    def get_model_dir(self, repo_id: str) -> Path:
        """Get the expected local path for a given model repo_id."""
        return self._model_dir / repo_id.split("/")[-1]

    def is_downloaded(self, repo_id: str) -> bool:
        """Check if a model repo_id is already downloaded."""
        local_path = self.get_model_dir(repo_id)
        return local_path.exists() and any(local_path.glob("*.gguf"))

    def download_model(
        self,
        model_name: str,
    ) -> None:
        """Start downloading the selected model into the target directory."""
        with self._lock:
            if self._is_download_active():
                raise RuntimeError("A model download is already in progress.")

            repo_id = model_name
            final_dir = (
                Path(self.get_model_dir(repo_id)).expanduser().resolve()
            )

            final_dir.parent.mkdir(parents=True, exist_ok=True)
            self._resolved_source = self._resolve_download_source()
            total_bytes = self._estimate_download_size(
                repo_id=repo_id,
                source=self._resolved_source,
            )

            task_id = uuid.uuid4().hex
            self._final_dir = final_dir
            self._staging_dir = (
                final_dir.parent / f".{final_dir.name}.{task_id}.downloading"
            )
            self._queue = self._context.Queue()
            payload = {
                "repo_id": repo_id,
                "source": self._resolved_source.value,
                "staging_dir": str(self._staging_dir),
            }
            self._process = self._context.Process(
                target=type(self)._download_worker,
                args=(payload, self._queue),
                name=f"copaw-model-download-{task_id}",
                daemon=True,
            )

            self._progress = {
                "status": DownloadTaskStatus.PENDING.value,
                "downloaded_bytes": 0,
                "total_bytes": total_bytes,
                "speed_bytes_per_sec": 0.0,
                "source": self._resolved_source.value,
                "error": None,
                "local_path": None,
            }
            self._last_size_sample = 0
            self._last_sample_time = time.monotonic()
            self._process.start()
            self._progress["status"] = DownloadTaskStatus.DOWNLOADING.value
            self._monitor_thread = threading.Thread(
                target=self._monitor_download,
                name=f"copaw-model-download-monitor-{task_id}",
                daemon=True,
            )
            self._monitor_thread.start()

    def get_download_progress(self) -> dict[str, Any]:
        """Return the current download progress."""
        with self._lock:
            return dict(self._progress)

    def cancel_download(self) -> None:
        """Cancel the current download task."""
        with self._lock:
            process = self._process
            staging_dir = self._staging_dir
            active = self._is_download_active()
            if not active:
                return
            self._progress["status"] = DownloadTaskStatus.CANCELLED.value
            self._progress["speed_bytes_per_sec"] = 0.0

        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)

        if staging_dir is not None:
            self._cleanup_path(staging_dir)

        with self._lock:
            self._process = None
            self._queue = None

    def _is_download_active(self) -> bool:
        """Return whether a download process is still active."""
        return self._process is not None and self._process.is_alive()

    def _monitor_download(self) -> None:
        """Watch the child process and update progress from disk usage."""
        while True:
            with self._lock:
                process = self._process
                queue = self._queue
                staging_dir = self._staging_dir
                final_dir = self._final_dir
                status = self._progress["status"]

            if status == DownloadTaskStatus.CANCELLED.value:
                return

            if staging_dir is not None:
                downloaded_bytes = self._calculate_downloaded_size(staging_dir)
                now = time.monotonic()
                elapsed = max(now - self._last_sample_time, 1e-6)
                speed = max(
                    0.0,
                    (downloaded_bytes - self._last_size_sample) / elapsed,
                )
                with self._lock:
                    self._progress["downloaded_bytes"] = downloaded_bytes
                    self._progress["speed_bytes_per_sec"] = speed
                self._last_sample_time = now
                self._last_size_sample = downloaded_bytes

            message = self._drain_queue_message(queue)
            if message is not None:
                self._handle_worker_message(message, staging_dir, final_dir)
                return

            if process is None:
                return

            if not process.is_alive():
                process.join(timeout=0.1)
                message = self._drain_queue_message(queue)
                if message is None:
                    with self._lock:
                        self._progress[
                            "status"
                        ] = DownloadTaskStatus.FAILED.value
                        self._progress[
                            "error"
                        ] = "Download process exited unexpectedly."
                        self._progress["speed_bytes_per_sec"] = 0.0
                        self._process = None
                        self._queue = None
                    if staging_dir is not None:
                        self._cleanup_path(staging_dir)
                    return
                self._handle_worker_message(message, staging_dir, final_dir)
                return

            time.sleep(0.5)

    def _handle_worker_message(
        self,
        message: dict[str, Any],
        staging_dir: Optional[Path],
        final_dir: Optional[Path],
    ) -> None:
        """Apply the final worker message to the instance state."""
        status = message.get("status", DownloadTaskStatus.FAILED.value)
        if status == DownloadTaskStatus.COMPLETED.value:
            if staging_dir is None or final_dir is None:
                raise RuntimeError("Download directories are not initialized.")
            local_path = self._promote_staging_directory(
                staging_dir=staging_dir,
                final_dir=final_dir,
                local_path=Path(message["local_path"]),
            )
            with self._lock:
                self._progress["status"] = DownloadTaskStatus.COMPLETED.value
                self._progress[
                    "downloaded_bytes"
                ] = self._calculate_downloaded_size(
                    final_dir,
                )
                self._progress["speed_bytes_per_sec"] = 0.0
                self._progress["local_path"] = str(local_path)
                self._process = None
                self._queue = None
            return

        if staging_dir is not None:
            self._cleanup_path(staging_dir)
        with self._lock:
            self._progress["status"] = status
            self._progress["error"] = (
                message.get("error") or "Download failed."
            )
            self._progress["speed_bytes_per_sec"] = 0.0
            self._process = None
            self._queue = None

    def _resolve_download_source(self) -> DownloadSource:
        """Choose Hugging Face when reachable, otherwise use ModelScope."""
        if self._probe_huggingface():
            return DownloadSource.HUGGINGFACE
        return DownloadSource.MODELSCOPE

    def _estimate_download_size(
        self,
        repo_id: str,
        source: DownloadSource,
    ) -> Optional[int]:
        """Best-effort total byte estimation for progress."""
        if source == DownloadSource.HUGGINGFACE:
            return self._estimate_huggingface_size(
                repo_id=repo_id,
            )
        return self._estimate_modelscope_size(
            repo_id=repo_id,
        )

    @staticmethod
    def _download_worker(payload: dict[str, Any], queue: Any) -> None:
        """Run the blocking SDK download in a child process."""
        repo_id = payload["repo_id"]
        source = DownloadSource(payload["source"])
        staging_dir = Path(payload["staging_dir"]).expanduser().resolve()

        try:
            ModelManager._cleanup_path(staging_dir)
            staging_dir.mkdir(parents=True, exist_ok=True)
            local_path = ModelManager._download_to_directory(
                repo_id=repo_id,
                source=source,
                local_dir=staging_dir,
            )
            queue.put(
                {
                    "status": DownloadTaskStatus.COMPLETED.value,
                    "local_path": str(Path(local_path).resolve()),
                },
            )
        except Exception as exc:
            queue.put(
                {
                    "status": DownloadTaskStatus.FAILED.value,
                    "error": str(exc),
                },
            )
            raise

    @staticmethod
    def _download_to_directory(
        repo_id: str,
        source: DownloadSource,
        local_dir: Path,
    ) -> str:
        """Download a model into the target directory."""
        if source == DownloadSource.HUGGINGFACE:
            return ModelManager._download_from_huggingface(
                repo_id=repo_id,
                local_dir=local_dir,
            )
        return ModelManager._download_from_modelscope(
            repo_id=repo_id,
            local_dir=local_dir,
        )

    @staticmethod
    def _download_from_huggingface(
        repo_id: str,
        local_dir: Path,
    ) -> str:
        """Download a model repository from Hugging Face Hub."""
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ImportError(
                "huggingface_hub is required for Hugging Face downloads.",
            ) from exc

        return snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
        )

    @staticmethod
    def _download_from_modelscope(
        repo_id: str,
        local_dir: Path,
    ) -> str:
        """Download a model repository from ModelScope."""
        return ModelManager._get_modelscope_snapshot_download()(
            model_id=repo_id,
            local_dir=str(local_dir),
        )

    def _estimate_huggingface_size(
        self,
        repo_id: str,
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
            total += size
            found = True
        return total if found else None

    def _estimate_modelscope_size(
        self,
        repo_id: str,
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
            size = item.get("Size")
            if isinstance(size, int):
                total += size
                found = True
        return total if found else None

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
