# -*- coding: utf-8 -*-
"""Integrated tests for CoPaw app startup and console."""
# pylint:disable=consider-using-with
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time

import httpx


def _find_free_port(host: str = "127.0.0.1") -> int:
    """Bind to portary 0 and return the OS-assigned free port."""
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


def test_app_startup_and_console() -> None:
    """Test that copaw app starts correctly with backend and console."""
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
            "info",
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
        max_wait = 60
        start_time = time.time()
        backend_ready = False
        last_error = None

        with httpx.Client(timeout=5.0) as client:
            while time.time() - start_time < max_wait:
                if process.poll() is not None:
                    logs = "".join(log_lines)[-4000:]
                    if "ImportError" in logs or "ModuleNotFoundError" in logs:
                        raise AssertionError(
                            "Failed due to dependency issue:\n" f"{logs}",
                        )
                    raise AssertionError(
                        f"Process exited early with code"
                        f" {process.returncode}.\nLogs:\n{logs}",
                    )

                try:
                    response = client.get(f"http://{host}:{port}/api/version")
                    if response.status_code == 200:
                        backend_ready = True
                        version_data = response.json()
                        assert "version" in version_data
                        assert isinstance(version_data["version"], str)
                        break
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    last_error = str(e)
                    time.sleep(1.0)

            if not backend_ready:
                logs = "".join(log_lines)[-4000:]
                raise AssertionError(
                    "Backend did not start within timeout period. "
                    f"Last error: {last_error}\n"
                    f"Logs:\n{logs}",
                )

            console_response = client.get(f"http://{host}:{port}/console/")
            assert (
                console_response.status_code == 200
            ), f"Console not accessible: {console_response.status_code}"

            assert (
                "text/html"
                in console_response.headers.get("content-type", "").lower()
            ), "Console should return HTML content"

            html_content = console_response.text
            assert len(html_content) > 0, "Console HTML should not be empty"
            assert (
                "<!doctype html>" in html_content.lower()
                or "<html" in html_content.lower()
            ), "Console should return valid HTML"

    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        log_thread.join(timeout=2)
