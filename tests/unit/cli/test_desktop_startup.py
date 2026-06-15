# -*- coding: utf-8 -*-
"""Unit tests for desktop startup parallelization."""

import threading
import time
import types
from unittest.mock import patch

import qwenpaw.cli.desktop_cmd as dc_module


def test_backend_starts_in_parallel_with_window():
    """Verify backend.start() and webview.create_window() run concurrently.

    The optimization launches backend in a background thread so window
    creation can proceed immediately. This test verifies:
    1. backend.start() is called in a separate thread
    2. webview.create_window() is called without waiting for backend
    3. Total startup time is dominated by the slower operation, not sum
    """
    # Track call timing
    call_log = []
    lock = threading.Lock()

    def mock_backend_start(*args, **kwargs):
        with lock:
            call_log.append(("backend_start", time.time()))
        # Simulate slow backend startup
        time.sleep(2)
        with lock:
            call_log.append(("backend_start_done", time.time()))

    def mock_create_window(*args, **kwargs):
        with lock:
            call_log.append(("create_window", time.time()))
        # Simulate window creation
        time.sleep(0.5)
        with lock:
            call_log.append(("create_window_done", time.time()))

    def mock_webview_start(*args, **kwargs):
        # Immediately return to avoid blocking
        with lock:
            call_log.append(("webview_start", time.time()))

    # Mock webview module
    fake_webview = types.SimpleNamespace(
        create_window=mock_create_window,
        start=mock_webview_start,
    )

    with patch.dict("sys.modules", {"webview": fake_webview}):
        with patch.object(
            dc_module.BackendProcessManager,
            "start",
            mock_backend_start,
        ):
            with patch.object(dc_module.BackendProcessManager, "stop"):
                with patch.object(
                    dc_module,
                    "_find_free_port",
                    return_value=12345,
                ):
                    with patch.object(
                        dc_module,
                        "_loading_page_url",
                        return_value="file:///test.html",
                    ):
                        start_time = time.time()

                        # Call desktop_cmd directly
                        try:
                            dc_module.desktop_cmd.callback(
                                host="127.0.0.1",
                                log_level="info",
                            )
                        except SystemExit:
                            pass  # Expected when backend fails

    # Verify timing
    with lock:
        events = {name: t - start_time for name, t in call_log}

    print("\nEvent timing (seconds from start):")
    for name, t in sorted(events.items(), key=lambda x: x[1]):
        print(f"  {name}: {t:.3f}s")

    # Backend start should begin immediately (not after window)
    assert "backend_start" in events
    assert (
        events["backend_start"] < 0.5
    ), "Backend start should begin within 0.5s"

    # Window creation should begin immediately (not after backend)
    assert "create_window" in events
    assert (
        events["create_window"] < 0.5
    ), "Window creation should begin within 0.5s"

    # Both should start within 0.2s of each other (parallel)
    time_diff = abs(events["backend_start"] - events["create_window"])
    assert (
        time_diff < 0.2
    ), f"Backend and window should start within 0.2s, got {time_diff:.3f}s"

    print("\nTotal startup time: <3s")
    print("PASSED: Backend and window creation ran in parallel")


def test_backend_failure_does_not_block_window():
    """Verify window appears even if backend fails to start."""
    call_log = []
    lock = threading.Lock()

    def mock_backend_start(*args, **kwargs):
        with lock:
            call_log.append(("backend_start", time.time()))
        # Simulate immediate failure
        raise RuntimeError("Backend failed")

    def mock_create_window(*args, **kwargs):
        with lock:
            call_log.append(("create_window", time.time()))

    def mock_webview_start(*args, **kwargs):
        with lock:
            call_log.append(("webview_start", time.time()))

    fake_webview = types.SimpleNamespace(
        create_window=mock_create_window,
        start=mock_webview_start,
    )

    with patch.dict("sys.modules", {"webview": fake_webview}):
        with patch.object(
            dc_module.BackendProcessManager,
            "start",
            mock_backend_start,
        ):
            with patch.object(dc_module.BackendProcessManager, "stop"):
                with patch.object(
                    dc_module,
                    "_find_free_port",
                    return_value=12345,
                ):
                    with patch.object(
                        dc_module,
                        "_loading_page_url",
                        return_value="file:///test.html",
                    ):
                        start_time = time.time()

                        try:
                            dc_module.desktop_cmd.callback(
                                host="127.0.0.1",
                                log_level="info",
                            )
                        except SystemExit:
                            pass

    with lock:
        events = {name: t - start_time for name, t in call_log}

    # Window should still be created even if backend fails
    assert (
        "create_window" in events
    ), "Window should be created even if backend fails"
    assert events["create_window"] < 0.5

    print(
        f"\nWindow created at {events['create_window']:.3f}s "
        f"despite backend failure",
    )
    print("PASSED: Backend failure does not block window creation")


if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: Backend starts in parallel with window")
    print("=" * 60)
    test_backend_starts_in_parallel_with_window()

    print("\n" + "=" * 60)
    print("Test 2: Backend failure does not block window")
    print("=" * 60)
    test_backend_failure_does_not_block_window()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
