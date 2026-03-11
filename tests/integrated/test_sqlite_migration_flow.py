# -*- coding: utf-8 -*-
"""Integrated tests for SQLite migration and chat HTTP flow."""
# pylint:disable=consider-using-with
from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx


def _find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return sock.getsockname()[1]


def _tee_stream(stream, buffer: list[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            buffer.append(line)
            print(line, end="", flush=True)
    finally:
        stream.close()


def _wait_for_ready(
    process: subprocess.Popen,
    host: str,
    port: int,
    log_lines: list[str],
    timeout_sec: float = 60.0,
) -> None:
    start_time = time.time()
    last_error = None
    with httpx.Client(timeout=5.0) as client:
        while time.time() - start_time < timeout_sec:
            if process.poll() is not None:
                logs = "".join(log_lines)[-4000:]
                raise AssertionError(
                    f"Process exited early with code {process.returncode}.\n"
                    f"Logs:\n{logs}",
                )
            try:
                response = client.get(f"http://{host}:{port}/api/version")
                if response.status_code == 200:
                    return
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = str(exc)
                time.sleep(1.0)

    logs = "".join(log_lines)[-4000:]
    raise AssertionError(
        "Backend did not start within timeout period. "
        f"Last error: {last_error}\nLogs:\n{logs}",
    )


def test_sqlite_migration_and_chat_http_flow(tmp_path: Path) -> None:
    host = "127.0.0.1"
    port = _find_free_port(host)
    log_lines: list[str] = []
    repo_root = Path(__file__).resolve().parents[2]
    src_path = str(repo_root / "src")

    working_dir = tmp_path / "working"
    sessions_dir = working_dir / "sessions"
    sessions_dir.mkdir(parents=True)

    legacy_chat = {
        "version": 1,
        "chats": [
            {
                "id": "chat-legacy",
                "name": "Migrated Chat",
                "session_id": "console:legacy",
                "user_id": "legacy",
                "channel": "console",
                "created_at": "2026-03-11T00:00:00+00:00",
                "updated_at": "2026-03-11T00:00:00+00:00",
                "meta": {},
            },
        ],
    }
    (working_dir / "chats.json").write_text(
        json.dumps(legacy_chat, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (working_dir / "jobs.json").write_text(
        json.dumps({"version": 1, "jobs": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (sessions_dir / "legacy_console--legacy.json").write_text(
        json.dumps({"agent": {"memory": []}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["COPAW_WORKING_DIR"] = str(working_dir)
    env["COPAW_SECRET_DIR"] = str(tmp_path / "working.secret")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{src_path}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else src_path
    )

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
        env=env,
        cwd=repo_root,
    )

    assert process.stdout is not None
    log_thread = threading.Thread(
        target=_tee_stream,
        args=(process.stdout, log_lines),
        daemon=True,
    )
    log_thread.start()

    try:
        _wait_for_ready(process, host, port, log_lines)

        with httpx.Client(timeout=10.0) as client:
            base_url = f"http://{host}:{port}"

            migrated = client.get(f"{base_url}/api/chats")
            assert migrated.status_code == 200
            migrated_list = migrated.json()
            assert [item["id"] for item in migrated_list] == ["chat-legacy"]

            detail = client.get(f"{base_url}/api/chats/chat-legacy")
            assert detail.status_code == 200
            assert detail.json() == {"messages": []}

            created = client.post(
                f"{base_url}/api/chats",
                json={
                    "id": "",
                    "name": "Created Chat",
                    "session_id": "console:new-user",
                    "user_id": "new-user",
                    "channel": "console",
                    "meta": {"from": "test"},
                },
            )
            assert created.status_code == 200
            created_chat = created.json()
            assert created_chat["name"] == "Created Chat"

            updated = client.put(
                f"{base_url}/api/chats/{created_chat['id']}",
                json={
                    **created_chat,
                    "name": "Renamed Chat",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["name"] == "Renamed Chat"

            filtered = client.get(
                f"{base_url}/api/chats",
                params={"user_id": "new-user", "channel": "console"},
            )
            assert filtered.status_code == 200
            assert [item["id"] for item in filtered.json()] == [
                created_chat["id"],
            ]

            deleted = client.post(
                f"{base_url}/api/chats/batch-delete",
                json=[created_chat["id"]],
            )
            assert deleted.status_code == 200
            assert deleted.json() == {"deleted": True}

            final_list = client.get(f"{base_url}/api/chats")
            assert final_list.status_code == 200
            assert [item["id"] for item in final_list.json()] == [
                "chat-legacy",
            ]

        db_path = working_dir / "state.sqlite3"
        assert db_path.is_file()
        with sqlite3.connect(db_path) as conn:
            chat_count = conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
            session_count = conn.execute(
                "SELECT COUNT(*) FROM sessions",
            ).fetchone()[0]
        assert chat_count == 1
        assert session_count >= 1

    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        log_thread.join(timeout=2)
