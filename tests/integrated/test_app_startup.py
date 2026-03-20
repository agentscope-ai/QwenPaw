# -*- coding: utf-8 -*-
"""Integrated tests for CoPaw app startup and console."""
# pylint:disable=consider-using-with
from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

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


def _assert_console_html(response: httpx.Response) -> None:
    assert (
        response.status_code == 200
    ), f"Console not accessible: {response.status_code}"
    assert (
        "text/html" in response.headers.get("content-type", "").lower()
    ), "Console should return HTML content"

    html_content = response.text
    assert len(html_content) > 0, "Console HTML should not be empty"
    assert (
        "<!doctype html>" in html_content.lower()
        or "<html" in html_content.lower()
    ), "Console should return valid HTML"


def _expected_static_dir() -> Path:
    """Return the console static directory the app should resolve to."""
    repo_root = Path(__file__).resolve().parents[2]
    static_candidates = (
        repo_root / "src" / "copaw" / "console",
        repo_root / "console" / "dist",
        repo_root / "console_dist",
    )
    return next(
        (
            candidate.resolve()
            for candidate in static_candidates
            if (candidate / "index.html").is_file()
        ),
        (repo_root / "console" / "dist").resolve(),
    )


def _wait_for_backend_ready(
    *,
    client: httpx.Client,
    host: str,
    port: int,
    process: subprocess.Popen[str],
    log_lines: list[str],
) -> None:
    """Wait until the backend responds or fail with useful logs."""
    max_wait = 60
    start_time = time.time()
    last_error = None

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
                version_data = response.json()
                assert "version" in version_data
                assert isinstance(version_data["version"], str)
                return
        except (httpx.ConnectError, httpx.TimeoutException) as error:
            last_error = str(error)
            time.sleep(1.0)

    logs = "".join(log_lines)[-4000:]
    raise AssertionError(
        "Backend did not start within timeout period. "
        f"Last error: {last_error}\n"
        f"Logs:\n{logs}",
    )


def _assert_console_assets(
    *,
    client: httpx.Client,
    host: str,
    port: int,
) -> None:
    """Assert the console entrypoint, SPA route, and logo are served."""
    console_response = client.get(f"http://{host}:{port}/console/")
    _assert_console_html(console_response)

    spa_response = client.get(f"http://{host}:{port}/console/settings")
    _assert_console_html(spa_response)

    logo_response = client.get(f"http://{host}:{port}/logo.png")
    assert logo_response.status_code == 200
    assert (
        "image/png"
        in logo_response.headers.get(
            "content-type",
            "",
        ).lower()
    )


def _assert_static_dir_log(
    log_lines: list[str],
    expected_static_dir: Path,
) -> None:
    """Assert startup logs contain the resolved static directory."""
    logs = "".join(log_lines)
    assert f"STATIC_DIR: {expected_static_dir}" in logs, logs[-4000:]


def _terminate_process(process: subprocess.Popen[str]) -> None:
    """Stop the spawned app process."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _run_app_startup_and_console_assertions(
    *,
    cwd: str | None = None,
) -> None:
    """Start the app in a subprocess and verify console assets."""
    host = "127.0.0.1"
    port = _find_free_port(host)
    log_lines: list[str] = []
    expected_static_dir = _expected_static_dir()

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
        cwd=cwd,
    )

    assert process.stdout is not None

    log_thread = threading.Thread(
        target=_tee_stream,
        args=(process.stdout, log_lines),
        daemon=True,
    )
    log_thread.start()

    try:
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            _wait_for_backend_ready(
                client=client,
                host=host,
                port=port,
                process=process,
                log_lines=log_lines,
            )
            _assert_console_assets(client=client, host=host, port=port)
            _assert_static_dir_log(log_lines, expected_static_dir)

    finally:
        _terminate_process(process)
        log_thread.join(timeout=2)


def test_app_startup_and_console() -> None:
    """Test that copaw app starts correctly with backend and console."""
    _run_app_startup_and_console_assertions()


def test_app_startup_and_console_from_non_repo_cwd() -> None:
    """Console should still resolve correctly when launched outside repo."""
    with tempfile.TemporaryDirectory(prefix="copaw-cwd-") as temp_dir:
        _run_app_startup_and_console_assertions(cwd=temp_dir)
