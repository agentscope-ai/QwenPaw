# -*- coding: utf-8 -*-
"""Durable transcript recovery across a full app process restart."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import httpx
import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.schemas import Message, Role, TextContent


@dataclass
class _RunningApp:
    process: subprocess.Popen[str]
    client: httpx.Client
    log_file: IO[str]
    log_path: Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_app(working_dir: Path) -> _RunningApp:
    port = _free_port()
    env = os.environ.copy()
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DASHSCOPE_API_KEY",
    ):
        env.pop(key, None)
    env.update(
        {
            "QWENPAW_WORKING_DIR": str(working_dir),
            "QWENPAW_SECRET_DIR": str(working_dir.parent / "secret"),
            "QWENPAW_BACKUP_DIR": str(working_dir.parent / "backups"),
            "QWENPAW_AUTH_ENABLED": "false",
            "QWENPAW_RUNNING_IN_CONTAINER": "true",
            "NO_PROXY": "*",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        },
    )
    log_path = working_dir.parent / f"app-{port}.log"
    log_file = log_path.open("w+", encoding="utf-8")
    process = subprocess.Popen(  # pylint: disable=consider-using-with
        [
            sys.executable,
            "-m",
            "qwenpaw",
            "app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        timeout=15.0,
        trust_env=False,
    )
    deadline = time.time() + 90.0
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            response = client.get("/api/healthz")
            if response.status_code == 200:
                return _RunningApp(process, client, log_file, log_path)
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.25)
    client.close()
    _stop_process(process)
    log_file.flush()
    log_file.seek(0)
    logs = log_file.read()
    log_file.close()
    raise AssertionError(f"app did not start:\n{logs[-4000:]}")


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        process.terminate()
    else:
        process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _stop_app(app: _RunningApp) -> None:
    app.client.close()
    _stop_process(app.process)
    app.log_file.close()


@pytest.mark.integration
@pytest.mark.p1
def test_transcript_is_readable_after_full_app_restart(tmp_path: Path) -> None:
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    first = _start_app(working_dir)
    second: _RunningApp | None = None
    try:
        created = first.client.post(
            "/api/chats",
            headers={"X-Agent-Id": "default"},
            json={
                "name": "restart transcript",
                "session_id": "restart-session",
                "user_id": "restart-user",
                "channel": "console",
                "meta": {},
            },
        )
        assert created.status_code == 200, created.text
        chat_id = str(created.json()["id"])
        _stop_app(first)

        store = TranscriptStore(
            working_dir / "workspaces" / "default" / "transcript.db",
        )
        store.start_turn(
            session_id="restart-session",
            user_id="restart-user",
            channel="console",
            turn_id="restart-turn",
            source="qwenpaw",
        )
        store.upsert_message(
            session_id="restart-session",
            turn_id="restart-turn",
            message=Message(
                id="restart-message",
                role=Role.USER,
                content=[TextContent(text="survived restart")],
            ).completed(),
            ordinal=0,
        )
        store.finish_turn(
            session_id="restart-session",
            turn_id="restart-turn",
            status="completed",
        )
        store.close()

        second = _start_app(working_dir)
        restored = second.client.get(
            f"/api/chats/{chat_id}",
            headers={"X-Agent-Id": "default"},
        )

        assert restored.status_code == 200, restored.text
        body = restored.json()
        assert [item["id"] for item in body["messages"]] == [
            "restart-message",
        ]
        assert body["messages"][0]["content"][0]["text"] == (
            "survived restart"
        )
        assert body["history"]["completeness"] == "complete"
    finally:
        if first.process.poll() is None:
            _stop_app(first)
        if second is not None:
            _stop_app(second)
