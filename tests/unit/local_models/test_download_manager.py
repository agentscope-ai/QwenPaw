# -*- coding: utf-8 -*-

from __future__ import annotations

from copaw.local_models.download_manager import (
    apply_download_result,
    begin_download_task,
    DownloadProgressTracker,
    DownloadTaskResult,
    DownloadTaskStatus,
)


def test_download_task_result_round_trips_through_dict() -> None:
    result = DownloadTaskResult(
        status=DownloadTaskStatus.COMPLETED,
        local_path="/tmp/model",
    )

    restored = DownloadTaskResult.from_dict(result.to_dict())

    assert restored == result


def test_apply_download_result_marks_failure() -> None:
    progress = DownloadProgressTracker()

    begin_download_task(progress, total_bytes=42, source="example")
    apply_download_result(
        progress,
        DownloadTaskResult(
            status=DownloadTaskStatus.FAILED,
            error="boom",
        ),
    )

    snapshot = progress.snapshot()
    assert snapshot["status"] == "failed"
    assert snapshot["error"] == "boom"


def test_apply_download_result_marks_completed() -> None:
    progress = DownloadProgressTracker()

    begin_download_task(progress, total_bytes=10, source="example")
    apply_download_result(
        progress,
        DownloadTaskResult(
            status=DownloadTaskStatus.COMPLETED,
            local_path="/tmp/bin",
        ),
        downloaded_bytes=10,
    )

    snapshot = progress.snapshot()
    assert snapshot["status"] == "completed"
    assert snapshot["local_path"] == "/tmp/bin"
    assert snapshot["downloaded_bytes"] == 10
