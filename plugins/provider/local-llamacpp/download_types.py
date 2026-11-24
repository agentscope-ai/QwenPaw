# -*- coding: utf-8 -*-
"""JSON messages exchanged with standalone download workers."""
from __future__ import annotations
from dataclasses import dataclass
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
