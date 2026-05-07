# -*- coding: utf-8 -*-
"""Shared fixtures for integration tests.

These fixtures start a real QwenPaw app subprocess with isolated workspace
directories and a sanitized environment to avoid touching local secrets.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest


_SENSITIVE_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DASHSCOPE_API_KEY",
    "DINGTALK_APP_KEY",
    "DINGTALK_APP_SECRET",
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "DISCORD_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
)


def _find_free_port(host: str = "127.0.0.1") -> int:
    """Bind to port 0 and return the assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _tee_stream(stream, buffer: list[str]) -> None:
    """Read subprocess output, print it live, and keep a copy."""
    try:
        for line in iter(stream.readline, ""):
            buffer.append(line)
            print(line, end="", flush=True)
    finally:
        stream.close()


@dataclass
class AppServer:
    """Handle to a running app subprocess used by tests."""

    host: str
    port: int
    process: subprocess.Popen[str]
    client: httpx.Client
    logs: list[str]
    log_thread: threading.Thread

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def logs_tail(self, chars: int = 4000) -> str:
        return "".join(self.logs)[-chars:]

    @staticmethod
    def _compact(value: Any, max_len: int = 240) -> str:
        """Render values as a compact single-line summary."""
        if value is None:
            return "-"
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except TypeError:
                text = repr(value)
        text = text.replace("\n", "\\n")
        return f"{text[: max_len - 3]}..." if len(text) > max_len else text

    def api_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request and always print request/response summary."""
        url = f"{self.base_url}{path}" if path.startswith("/") else path
        request_payload = kwargs.get("json")
        if request_payload is None:
            request_payload = kwargs.get("data")
        request_params = kwargs.get("params")

        response = self.client.request(
            method=method.upper(),
            url=url,
            **kwargs,
        )
        response_text = response.text
        if len(response_text) > 240:
            response_text = f"{response_text[:237]}..."

        level = "PASS" if 200 <= response.status_code < 400 else "FAIL"
        print(
            (
                f"[integration][{level}] {method.upper()} {path} | "
                f"params={self._compact(request_params)} | "
                f"request={self._compact(request_payload)} | "
                f"status={response.status_code} | "
                f"response={self._compact(response_text)}"
            ),
            flush=True,
        )
        return response


@pytest.fixture
def app_server(tmp_path: Path) -> Iterator[AppServer]:
    """Start one isolated qwenpaw app process for a test."""
    host = "127.0.0.1"
    port = _find_free_port(host)

    working_dir = tmp_path / "working"
    secret_dir = tmp_path / "working.secret"
    backups_dir = tmp_path / "working.backups"
    working_dir.mkdir(parents=True, exist_ok=True)
    secret_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for key in _SENSITIVE_ENV_VARS:
        env.pop(key, None)

    env["QWENPAW_WORKING_DIR"] = str(working_dir)
    env["QWENPAW_SECRET_DIR"] = str(secret_dir)
    env["QWENPAW_BACKUP_DIR"] = str(backups_dir)
    env["QWENPAW_AUTH_ENABLED"] = "false"
    env["NO_PROXY"] = "*"
    env["PYTHONUNBUFFERED"] = "1"

    logs: list[str] = []
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "qwenpaw",
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
        env=env,
    ) as process:
        assert process.stdout is not None

        log_thread = threading.Thread(
            target=_tee_stream,
            args=(process.stdout, logs),
            daemon=True,
        )
        log_thread.start()

        client = httpx.Client(timeout=5.0, trust_env=False)

        try:
            max_wait_seconds = 60
            start_at = time.time()
            last_error: str | None = None
            while time.time() - start_at < max_wait_seconds:
                if process.poll() is not None:
                    raise AssertionError(
                        "qwenpaw app exited during startup.\n"
                        f"exit_code={process.returncode}\n"
                        f"logs:\n{''.join(logs)[-4000:]}",
                    )

                try:
                    resp = client.get(f"http://{host}:{port}/api/version")
                    if resp.status_code == 200:
                        break
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    last_error = str(exc)
                time.sleep(0.5)
            else:
                raise AssertionError(
                    "qwenpaw app did not become ready in time.\n"
                    f"last_error={last_error}\n"
                    f"logs:\n{''.join(logs)[-4000:]}",
                )

            yield AppServer(
                host=host,
                port=port,
                process=process,
                client=client,
                logs=logs,
                log_thread=log_thread,
            )
        finally:
            client.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log_thread.join(timeout=2)
