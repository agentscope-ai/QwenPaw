# -*- coding: utf-8 -*-
"""Shared download state types and progress tracking helpers."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any


class DownloadTaskStatus(str, Enum):
    """Download lifecycle for a single downloader instance."""

    IDLE = "idle"
    PENDING = "pending"
    DOWNLOADING = "downloading"
    CANCELING = "canceling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DownloadTaskResult:
        """Build a task result from a serialized payload."""
        return cls(
            status=DownloadTaskStatus(payload["status"]),
            local_path=payload.get("local_path"),
            error=payload.get("error"),
        )


class DownloadProgressTracker:
    """Thread-safe tracker for lifecycle and throughput of a download task."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress = DownloadProgress()
        self._last_size_sample = 0
        self._last_sample_time = time.monotonic()

    def reset(
        self,
        *,
        status: DownloadTaskStatus = DownloadTaskStatus.IDLE,
        total_bytes: int | None = None,
        model_name: str | None = None,
        source: str | None = None,
        error: str | None = None,
        local_path: str | None = None,
    ) -> DownloadProgress:
        """Reset progress to a fresh lifecycle state."""
        with self._lock:
            self._progress = DownloadProgress(
                status=status,
                model_name=model_name,
                downloaded_bytes=0,
                total_bytes=total_bytes,
                speed_bytes_per_sec=0.0,
                source=source,
                error=error,
                local_path=local_path,
            )
            self._last_size_sample = 0
            self._last_sample_time = time.monotonic()
            return self._progress

    def set_status(
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

    def update_downloaded(
        self,
        downloaded_bytes: int,
        *,
        total_bytes: int | None = None,
        model_name: str | None = None,
        source: str | None = None,
    ) -> DownloadProgress:
        """Update downloaded bytes and recompute current transfer speed."""
        with self._lock:
            now = time.monotonic()
            elapsed = max(now - self._last_sample_time, 1e-6)
            speed = max(
                0.0,
                (downloaded_bytes - self._last_size_sample) / elapsed,
            )
            next_total_bytes = (
                self._progress.total_bytes
                if total_bytes is None
                else total_bytes
            )
            next_model_name = (
                self._progress.model_name if model_name is None else model_name
            )
            next_source = self._progress.source if source is None else source
            self._progress = replace(
                self._progress,
                model_name=next_model_name,
                downloaded_bytes=downloaded_bytes,
                total_bytes=next_total_bytes,
                speed_bytes_per_sec=speed,
                source=next_source,
            )
            self._last_size_sample = downloaded_bytes
            self._last_sample_time = now
            return self._progress

    def mark_cancelled(self) -> DownloadProgress:
        """Transition to cancelled state."""
        return self.set_status(DownloadTaskStatus.CANCELLED)

    def mark_canceling(self) -> DownloadProgress:
        """Transition to canceling state."""
        return self.set_status(DownloadTaskStatus.CANCELING)

    def mark_failed(
        self,
        error: str,
        *,
        status: DownloadTaskStatus = DownloadTaskStatus.FAILED,
    ) -> DownloadProgress:
        """Transition to a failed terminal state."""
        return self.set_status(status, error=error)

    def mark_completed(
        self,
        *,
        local_path: str,
        downloaded_bytes: int | None = None,
    ) -> DownloadProgress:
        """Transition to completed state and optionally finalize byte count."""
        with self._lock:
            progress = self._progress
        if downloaded_bytes is not None:
            progress = self.update_downloaded(downloaded_bytes)
        return self.set_status(
            DownloadTaskStatus.COMPLETED,
            local_path=local_path,
            total_bytes=progress.total_bytes,
        )

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


def begin_download_task(
    progress: DownloadProgressTracker,
    *,
    total_bytes: int | None = None,
    model_name: str | None = None,
    source: str | None = None,
) -> None:
    """Initialize progress for a new background task."""
    progress.reset(
        status=DownloadTaskStatus.PENDING,
        total_bytes=total_bytes,
        model_name=model_name,
        source=source,
    )
    progress.set_status(DownloadTaskStatus.DOWNLOADING)


def apply_download_result(
    progress: DownloadProgressTracker,
    result: DownloadTaskResult,
    *,
    downloaded_bytes: int | None = None,
) -> DownloadTaskResult:
    """Apply a terminal task result to a progress tracker."""
    if result.status == DownloadTaskStatus.COMPLETED:
        if result.local_path is None:
            raise RuntimeError(
                "Completed download result must include local_path.",
            )
        progress.mark_completed(
            local_path=result.local_path,
            downloaded_bytes=downloaded_bytes,
        )
        return result

    if result.status == DownloadTaskStatus.CANCELLED:
        progress.mark_cancelled()
        return result

    progress.mark_failed(
        result.error or "Download failed.",
        status=result.status,
    )
    return result
