# -*- coding: utf-8 -*-

from __future__ import annotations

from copaw.local_models.download_manager import (
    DownloadProgressUpdate,
    DownloadProgressTracker,
    ProcessDownloadTask,
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

    progress.begin(total_bytes=42, source="example")
    progress.apply_result(
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

    progress.begin(total_bytes=10, source="example")
    progress.apply_result(
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


def test_download_progress_update_round_trips_through_dict() -> None:
    update = DownloadProgressUpdate(
        downloaded_bytes=12,
        total_bytes=42,
        model_name="demo/model",
        source="example",
    )

    restored = DownloadProgressUpdate.from_dict(update.to_dict())

    assert restored == update


def test_download_progress_message_round_trips() -> None:
    update = DownloadProgressUpdate(
        downloaded_bytes=12,
        total_bytes=42,
        model_name="demo/model",
        source="example",
    )

    restored = DownloadProgressUpdate.from_message(update.to_message())

    assert restored == update


def test_download_result_message_round_trips() -> None:
    result = DownloadTaskResult(
        status=DownloadTaskStatus.COMPLETED,
        local_path="/tmp/model",
    )

    restored = DownloadTaskResult.from_message(result.to_message())

    assert restored == result


def test_process_download_task_wraps_worker_hooks() -> None:
    captured: dict[str, object] = {}
    cleanup_calls: list[str] = []
    progress_update = DownloadProgressUpdate(downloaded_bytes=7)
    finalized_result = DownloadTaskResult(
        status=DownloadTaskStatus.COMPLETED,
        local_path="/tmp/model",
    )

    class _FakeContext:
        def Process(self, **kwargs):
            captured.update(kwargs)
            return object()

    task = ProcessDownloadTask(
        target=lambda payload, queue: None,
        payload={"demo": "value"},
        progress_probe=lambda: progress_update,
        finalize_result=lambda result: (finalized_result, 7),
        cleanup=lambda: cleanup_calls.append("cleanup"),
    )

    process = task.create_process(
        _FakeContext(),
        process_name="demo-process",
        queue="queue",
    )
    result, downloaded_bytes = task.finalize(
        DownloadTaskResult(status=DownloadTaskStatus.COMPLETED),
    )
    task.run_cleanup()

    assert process is not None
    assert captured == {
        "target": task.target,
        "args": ({"demo": "value"}, "queue"),
        "name": "demo-process",
        "daemon": True,
    }
    assert task.probe_progress() == progress_update
    assert result == finalized_result
    assert downloaded_bytes == 7
    assert cleanup_calls == ["cleanup"]
