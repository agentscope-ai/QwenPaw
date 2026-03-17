# -*- coding: utf-8 -*-
"""Pytest configuration and shared fixtures for CoPaw tests."""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from typing import Generator

import httpx
import pytest


def _find_free_port(host: str = "127.0.0.1") -> int:
    """Find a free port on the given host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return sock.getsockname()[1]


def _tee_stream(stream, buffer: list[str]) -> None:
    """Read subprocess output, print it live, and keep a copy."""
    try:
        for line in iter(stream.readline, ""):
            buffer.append(line)
            print(line, end="", flush=True)
    finally:
        stream.close()


@pytest.fixture(scope="module")
def running_app() -> Generator[httpx.Client, None, None]:
    """Start the CoPaw app and yield an HTTP client for testing.

    This fixture starts the app once per test module and keeps it running
    for all tests in that module. The app is stopped when all tests complete.

    Yields:
        httpx.Client: An HTTP client configured to talk to the running app.
    """
    host = "127.0.0.1"
    port = _find_free_port(host)
    log_lines: list[str] = []

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "copaw",
            "app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            "warning",  # Reduce noise in test output
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None

    log_thread = threading.Thread(
        target=_tee_stream,
        args=(process.stdout, log_lines),
        daemon=True,
    )
    log_thread.start()

    try:
        # Wait for backend to be ready
        max_wait = 120  # Longer timeout for slower machines
        start_time = time.time()
        backend_ready = False
        last_error = None

        with httpx.Client(timeout=10.0) as client:
            while time.time() - start_time < max_wait:
                if process.poll() is not None:
                    logs = "".join(log_lines)[-4000:]
                    if "ImportError" in logs or "ModuleNotFoundError" in logs:
                        raise RuntimeError(
                            f"Failed due to missing dependency:\n{logs}",
                        )
                    raise RuntimeError(
                        f"Process exited early with code {process.returncode}.\nLogs:\n{logs}",
                    )

                try:
                    response = client.get(f"http://{host}:{port}/api/version")
                    if response.status_code == 200:
                        backend_ready = True
                        break
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    last_error = str(e)
                    time.sleep(1.0)

            if not backend_ready:
                logs = "".join(log_lines)[-4000:]
                raise RuntimeError(
                    "Backend did not start within timeout period. "
                    f"Last error: {last_error}\nLogs:\n{logs}",
                )

        # Create client for tests
        test_client = httpx.Client(base_url=f"http://{host}:{port}", timeout=30.0)
        yield test_client
        test_client.close()

    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        log_thread.join(timeout=2)
