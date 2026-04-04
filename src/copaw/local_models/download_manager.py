# -*- coding: utf-8 -*-
"""Shared download state types and progress tracking helpers."""

from __future__ import annotations

import threading
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from enum import Enum
from queue import Empty
from typing import Any, Callable

from ..utils.command_runner import (
    ManagedProcess,
    shutdown_process_sync,
    start_multiprocessing_process,
)


class DownloadTaskStatus(str, Enum):
    """Download lifecycle for a single downloader instance."""

    IDLE = "idle"
    PENDING = "pending"
    DOWNLOADING = "downloading"
    CANCELING = "canceling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadTaskMessageType(str, Enum):
    PROGRESS = "progress"
    RESULT = "result"


@dataclass(frozen=True)
class DownloadProgress:
    """Normalized download progress shared by local model downloads."""

    status: DownloadTaskStatus = DownloadTaskStatus.IDLE
    model_name: str | None = None
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bytes_per_sec: float = 0.0
    source: str | None = None
    error: str | None = None
    local_path: str | None = None


@dataclass(frozen=True)
class DownloadTaskResult:
    """Normalized terminal result for a background download task."""

    status: DownloadTaskStatus
    local_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Return a serializable result for thread/process boundaries."""
        return {
            "status": self.status.value,
            "local_path": self.local_path,
            "error": self.error,
        }

    def to_message(self) -> dict[str, Any]:
        return {
            "type": DownloadTaskMessageType.RESULT.value,
            "payload": self.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DownloadTaskResult:
        """Build a task result from a serialized payload."""
        return cls(
            status=DownloadTaskStatus(payload["status"]),
            local_path=payload.get("local_path"),
            error=payload.get("error"),
        )

    @classmethod
    def from_message(cls, payload: dict[str, Any]) -> DownloadTaskResult:
        return cls.from_dict(payload["payload"])


@dataclass(frozen=True)
class DownloadProgressUpdate:
    downloaded_bytes: int
    total_bytes: int | None = None
    model_name: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "model_name": self.model_name,
            "source": self.source,
        }

    def to_message(self) -> dict[str, Any]:
        return {
            "type": DownloadTaskMessageType.PROGRESS.value,
            **self.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DownloadProgressUpdate:
        return cls(
            downloaded_bytes=int(payload["downloaded_bytes"]),
            total_bytes=payload.get("total_bytes"),
            model_name=payload.get("model_name"),
            source=payload.get("source"),
        )

    @classmethod
    def from_message(
        cls,
        payload: dict[str, Any],
    ) -> DownloadProgressUpdate:
        return cls.from_dict(payload)


DownloadResultFinalizer = Callable[
    [DownloadTaskResult],
    tuple[DownloadTaskResult, int | None],
]
DownloadCleanup = Callable[[], None]
DownloadProgressProbe = Callable[[], DownloadProgressUpdate | None]
DownloadWorkerTarget = Callable[[dict[str, Any], Any], None]


@dataclass
class ProcessDownloadTask:
    target: DownloadWorkerTarget
    payload: dict[str, Any]
    progress_probe: DownloadProgressProbe | None = None
    finalize_result: DownloadResultFinalizer | None = None
    cleanup: DownloadCleanup | None = None

    def create_process(
        self,
        context: Any,
        *,
        process_name: str,
        queue: Any,
    ) -> Any:
        return context.Process(
            target=self.target,
            args=(self.payload, queue),
            name=process_name,
            daemon=True,
        )

    def probe_progress(self) -> DownloadProgressUpdate | None:
        if self.progress_probe is None:
            return None
        return self.progress_probe()

    def finalize(
        self,
        result: DownloadTaskResult,
    ) -> tuple[DownloadTaskResult, int | None]:
        if self.finalize_result is None:
            return result, None
        return self.finalize_result(result)

    def run_cleanup(self) -> None:
        if self.cleanup is not None:
            self.cleanup()


@dataclass
class ProcessDownloadTaskSpec:
    process_name: str
    command: list[str]
    task: ProcessDownloadTask
    model_name: str | None = None
    source: str | None = None
    total_bytes: int | None = None
    poll_interval: float = 1.0


@dataclass
class ManagedDownloadTask:
    process: ManagedProcess
    queue: Any
    monitor_thread: threading.Thread
    spec: ProcessDownloadTaskSpec


class DownloadProgressTracker:
    """Thread-safe tracker for lifecycle and throughput of a download task."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress = DownloadProgress()
        self._last_size_sample = 0
        self._last_sample_time = time.monotonic()

    def _set_status(
        self,
        status: DownloadTaskStatus,
        *,
        error: str | None = None,
        local_path: str | None = None,
        model_name: str | None = None,
        source: str | None = None,
        total_bytes: int | None = None,
    ) -> DownloadProgress:
        """Update lifecycle status and optional metadata."""
        with self._lock:
            next_total_bytes = (
                self._progress.total_bytes
                if total_bytes is None
                else total_bytes
            )
            next_model_name = (
                self._progress.model_name if model_name is None else model_name
            )
            next_source = self._progress.source if source is None else source
            next_error = self._progress.error if error is None else error
            next_local_path = (
                self._progress.local_path if local_path is None else local_path
            )
            next_speed = self._progress.speed_bytes_per_sec
            if status in {
                DownloadTaskStatus.CANCELING,
                DownloadTaskStatus.CANCELLED,
                DownloadTaskStatus.COMPLETED,
                DownloadTaskStatus.FAILED,
            }:
                next_speed = 0.0

            self._progress = replace(
                self._progress,
                status=status,
                model_name=next_model_name,
                total_bytes=next_total_bytes,
                speed_bytes_per_sec=next_speed,
                source=next_source,
                error=next_error,
                local_path=next_local_path,
            )
            return self._progress

    def get_status(self) -> DownloadTaskStatus:
        """Return the current lifecycle status."""
        with self._lock:
            return self._progress.status

    def get_progress(self) -> DownloadProgress:
        """Return the current typed progress snapshot."""
        with self._lock:
            return self._progress

    def snapshot(self) -> dict[str, Any]:
        """Return a dict snapshot matching existing polling APIs."""
        with self._lock:
            raw = asdict(self._progress)
        raw["status"] = self.get_status().value
        return raw

    def begin(
        self,
        *,
        total_bytes: int | None = None,
        model_name: str | None = None,
        source: str | None = None,
    ) -> None:
        with self._lock:
            self._progress = DownloadProgress(
                status=DownloadTaskStatus.PENDING,
                model_name=model_name,
                downloaded_bytes=0,
                total_bytes=total_bytes,
                speed_bytes_per_sec=0.0,
                source=source,
                error=None,
                local_path=None,
            )
            self._last_size_sample = 0
            self._last_sample_time = time.monotonic()
        self._set_status(DownloadTaskStatus.DOWNLOADING)

    def request_cancel(self) -> DownloadProgress:
        return self._set_status(DownloadTaskStatus.CANCELING)

    def apply_progress_update(
        self,
        update: DownloadProgressUpdate,
    ) -> DownloadProgress:
        with self._lock:
            now = time.monotonic()
            elapsed = max(now - self._last_sample_time, 1e-6)
            speed = max(
                0.0,
                (update.downloaded_bytes - self._last_size_sample) / elapsed,
            )
            next_total_bytes = (
                self._progress.total_bytes
                if update.total_bytes is None
                else update.total_bytes
            )
            next_model_name = (
                self._progress.model_name
                if update.model_name is None
                else update.model_name
            )
            next_source = (
                self._progress.source
                if update.source is None
                else update.source
            )
            self._progress = replace(
                self._progress,
                model_name=next_model_name,
                downloaded_bytes=update.downloaded_bytes,
                total_bytes=next_total_bytes,
                speed_bytes_per_sec=speed,
                source=next_source,
            )
            self._last_size_sample = update.downloaded_bytes
            self._last_sample_time = now
            return self._progress

    def apply_result(
        self,
        result: DownloadTaskResult,
        *,
        downloaded_bytes: int | None = None,
    ) -> DownloadTaskResult:
        if result.status == DownloadTaskStatus.COMPLETED:
            if result.local_path is None:
                raise RuntimeError(
                    "Completed download result must include local_path.",
                )
            if downloaded_bytes is not None:
                self.apply_progress_update(
                    DownloadProgressUpdate(
                        downloaded_bytes=downloaded_bytes,
                    ),
                )
            self._set_status(
                DownloadTaskStatus.COMPLETED,
                local_path=result.local_path,
                total_bytes=self.get_progress().total_bytes,
            )
            return result

        if result.status == DownloadTaskStatus.CANCELLED:
            self._set_status(DownloadTaskStatus.CANCELLED)
            return result

        self._set_status(
            result.status,
            error=result.error or "Download failed.",
        )
        return result


class ProcessDownloadController:
    """Manage a single process-backed download task and its progress."""

    def __init__(
        self,
        *,
        context: Any,
        progress: DownloadProgressTracker,
    ) -> None:
        self._context = context
        self._progress = progress
        self._lock = threading.Lock()
        self._task: ManagedDownloadTask | None = None

    def start(self, spec: ProcessDownloadTaskSpec) -> None:
        with self._lock:
            if self._task is not None and self._task.process.is_alive():
                raise RuntimeError("A download is already in progress.")

            queue = self._context.Queue()
            raw_process = spec.task.create_process(
                self._context,
                process_name=spec.process_name,
                queue=queue,
            )
            process = start_multiprocessing_process(
                raw_process,
                command=spec.command,
            )
            monitor_thread = threading.Thread(
                target=self._monitor_task,
                args=(process, queue, spec),
                name=f"{spec.process_name}-monitor",
                daemon=True,
            )
            self._task = ManagedDownloadTask(
                process=process,
                queue=queue,
                monitor_thread=monitor_thread,
                spec=spec,
            )

            self._progress.begin(
                total_bytes=spec.total_bytes,
                model_name=spec.model_name,
                source=spec.source,
            )
            monitor_thread.start()

    def cancel(self) -> None:
        with self._lock:
            task = self._task
            if task is None or not task.process.is_alive():
                return
            self._progress.request_cancel()

        shutdown_process_sync(
            task.process,
            graceful_timeout=2.0,
            kill_timeout=2.0,
        )

        if task.monitor_thread is not threading.current_thread():
            task.monitor_thread.join(timeout=2.0)

        self._finish_task(
            task=task,
            result=DownloadTaskResult(
                status=DownloadTaskStatus.CANCELLED,
            ),
            cleanup_spec=True,
        )

    def snapshot(self) -> dict[str, Any]:
        return self._progress.snapshot()

    def is_active(self) -> bool:
        with self._lock:
            task = self._task
        return bool(task is not None and task.process.is_alive())

    def _monitor_task(
        self,
        process: ManagedProcess,
        queue: Any,
        spec: ProcessDownloadTaskSpec,
    ) -> None:
        while True:
            status = self._progress.get_status()
            if status in {
                DownloadTaskStatus.CANCELING,
                DownloadTaskStatus.CANCELLED,
            }:
                return

            progress_update = spec.task.probe_progress()
            if progress_update is not None:
                self._progress.apply_progress_update(progress_update)

            if self._handle_message(queue, spec):
                return

            if not process.is_alive():
                process.join(timeout=0.1)
                if self._handle_message(queue, spec):
                    return

                self._finish_task(
                    task=ManagedDownloadTask(
                        process=process,
                        queue=queue,
                        monitor_thread=threading.current_thread(),
                        spec=spec,
                    ),
                    result=DownloadTaskResult(
                        status=DownloadTaskStatus.FAILED,
                        error="Download process exited unexpectedly.",
                    ),
                    cleanup_spec=True,
                )
                return

            time.sleep(spec.poll_interval)

    def _handle_message(
        self,
        queue: Any,
        spec: ProcessDownloadTaskSpec,
    ) -> bool:
        while True:
            try:
                message = queue.get_nowait()
            except (Empty, ValueError, OSError):
                return False

            message_type = message.get("type")
            if message_type == DownloadTaskMessageType.PROGRESS.value:
                self._progress.apply_progress_update(
                    DownloadProgressUpdate.from_message(message),
                )
                continue

            if message_type != DownloadTaskMessageType.RESULT.value:
                continue

            result = DownloadTaskResult.from_message(message)
            result, downloaded_bytes = spec.task.finalize(result)

            self._finish_task(
                spec=spec,
                result=result,
                downloaded_bytes=downloaded_bytes,
                cleanup_spec=result.status != DownloadTaskStatus.COMPLETED,
            )
            return True

    def _get_task_for_spec(
        self,
        spec: ProcessDownloadTaskSpec,
    ) -> ManagedDownloadTask | None:
        with self._lock:
            task = self._task
        if task is None or task.spec is not spec:
            return None
        return task

    def _finish_task(
        self,
        *,
        result: DownloadTaskResult,
        task: ManagedDownloadTask | None = None,
        spec: ProcessDownloadTaskSpec | None = None,
        downloaded_bytes: int | None = None,
        cleanup_spec: bool = False,
    ) -> None:
        resolved_task = task
        resolved_spec = spec
        if resolved_task is None and resolved_spec is not None:
            resolved_task = self._get_task_for_spec(resolved_spec)
        if resolved_spec is None and resolved_task is not None:
            resolved_spec = resolved_task.spec

        if cleanup_spec and resolved_spec is not None:
            self._cleanup_task_spec(resolved_spec)

        if resolved_task is not None:
            self._release_task_resources(resolved_task)

        with self._lock:
            current_task = self._task
            if current_task is not None and (
                current_task is resolved_task
                or (
                    resolved_spec is not None
                    and current_task.spec is resolved_spec
                )
            ):
                self._task = None

        self._progress.apply_result(
            result,
            downloaded_bytes=downloaded_bytes,
        )

    @staticmethod
    def _cleanup_task_spec(spec: ProcessDownloadTaskSpec) -> None:
        spec.task.run_cleanup()

    @staticmethod
    def _release_task_resources(task: ManagedDownloadTask) -> None:
        with suppress(AttributeError, OSError, ValueError):
            task.queue.close()
        with suppress(AttributeError, OSError, ValueError, AssertionError):
            task.queue.join_thread()
        with suppress(AttributeError, OSError, ValueError):
            task.process.close()
