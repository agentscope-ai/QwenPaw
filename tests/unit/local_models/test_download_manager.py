# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from copaw.local_models.download_manager import (
    DownloadProgressUpdate,
    DownloadProgressTracker,
    ProcessDownloadController,
    ProcessDownloadTaskSpec,
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


def test_handle_message_returns_when_queue_is_closed() -> None:
    progress = DownloadProgressTracker()
    controller = ProcessDownloadController(
        context=object(),
        progress=progress,
    )
    spec = ProcessDownloadTaskSpec(
        process_name="demo-process",
        command=["demo"],
        task=ProcessDownloadTask(
            target=lambda payload, queue: None,
            payload={},
        ),
    )

    class _ClosedQueue:
        def get_nowait(self):
            raise ValueError("Queue is closed")

    assert controller._handle_message(_ClosedQueue(), spec) is False


def test_handle_message_stops_after_terminal_result() -> None:
    progress = DownloadProgressTracker()
    progress.begin(total_bytes=5, source="example")
    controller = ProcessDownloadController(
        context=object(),
        progress=progress,
    )
    finished: list[dict[str, object]] = []
    spec = ProcessDownloadTaskSpec(
        process_name="demo-process",
        command=["demo"],
        task=ProcessDownloadTask(
            target=lambda payload, queue: None,
            payload={},
        ),
    )

    def _fake_finish_task(**kwargs):
        finished.append(kwargs)

    controller._finish_task = _fake_finish_task  # type: ignore[method-assign]

    terminal_message = DownloadTaskResult(
        status=DownloadTaskStatus.FAILED,
        error="boom",
    ).to_message()

    class _Queue:
        def __init__(self) -> None:
            self._messages = [terminal_message]
            self.calls = 0

        def get_nowait(self):
            self.calls += 1
            if self._messages:
                return self._messages.pop(0)
            raise AssertionError(
                "queue should not be polled after terminal result",
            )

    queue = _Queue()

    assert controller._handle_message(queue, spec) is True
    assert queue.calls == 1
    assert len(finished) == 1


def test_handle_message_marks_finalize_exceptions_as_failed() -> None:
    progress = DownloadProgressTracker()
    progress.begin(total_bytes=5, source="example")
    controller = ProcessDownloadController(
        context=object(),
        progress=progress,
    )
    finished: list[dict[str, object]] = []
    spec = ProcessDownloadTaskSpec(
        process_name="demo-process",
        command=["demo"],
        task=ProcessDownloadTask(
            target=lambda payload, queue: None,
            payload={},
            finalize_result=lambda result: (_ for _ in ()).throw(
                PermissionError("file is in use"),
            ),
        ),
    )

    def _fake_finish_task(**kwargs):
        finished.append(kwargs)

    controller._finish_task = _fake_finish_task  # type: ignore[method-assign]

    terminal_message = DownloadTaskResult(
        status=DownloadTaskStatus.COMPLETED,
        local_path="/tmp/bin",
    ).to_message()

    class _Queue:
        def __init__(self) -> None:
            self._messages = [terminal_message]

        def get_nowait(self):
            if self._messages:
                return self._messages.pop(0)
            raise AssertionError("queue should not be polled again")

    assert controller._handle_message(_Queue(), spec) is True
    assert len(finished) == 1
    finished_result = finished[0]["result"]
    assert isinstance(finished_result, DownloadTaskResult)
    assert finished_result.status == DownloadTaskStatus.FAILED
    assert finished_result.error == (
        "Download finalize step failed: file is in use"
    )
    assert finished[0]["cleanup_spec"] is True
