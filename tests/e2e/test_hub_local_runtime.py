# -*- coding: utf-8 -*-
"""Cross-platform end-to-end coverage for a Hub-managed Local runtime."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest


_HUB_READY_TIMEOUT_SECONDS = 120.0


def _allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _wait_for_hub(
    client: httpx.Client,
    process: subprocess.Popen[Any],
) -> None:
    deadline = time.monotonic() + _HUB_READY_TIMEOUT_SECONDS
    last_error = "Hub did not respond"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"Hub exited before readiness with code {process.returncode}",
            )
        try:
            response = client.get("/api/version")
            if response.status_code == 200:
                return
            last_error = f"Hub readiness returned HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise AssertionError(last_error)


def _stop_runtime(client: httpx.Client, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/hub/runtimes", headers=headers)
    if response.status_code != 200:
        return
    for runtime in response.json().get("items", []):
        client.post(
            f"/api/hub/runtimes/{runtime['runtime_id']}/stop",
            headers=headers,
        )


def _runtime_logs(hub_root: Path) -> str:
    logs: list[str] = []
    for log_path in sorted((hub_root / "runtimes").glob("*/logs/app.log")):
        logs.append(
            f"--- {log_path.relative_to(hub_root)} ---\n"
            f"{log_path.read_text(encoding='utf-8')}",
        )
    return "\n".join(logs) or "No runtime log was created."


def _hub_environment(hub_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["QWENPAW_HUB_DIR"] = str(hub_root)
    return environment


def _wait_for_runtime(
    client: httpx.Client,
    process: subprocess.Popen[Any],
    headers: dict[str, str],
) -> None:
    deadline = time.monotonic() + 90
    last_error = "Runtime did not become ready"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"Hub exited while starting runtime with code "
                f"{process.returncode}",
            )
        try:
            response = client.get("/api/healthz", headers=headers)
            if response.status_code == 200:
                return
            last_error = (
                f"Runtime readiness returned HTTP {response.status_code}: "
                f"{response.text}"
            )
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise AssertionError(last_error)


@pytest.mark.skipif(
    os.environ.get("QWENPAW_LOCAL_RUNTIME_E2E") != "1",
    reason="requires an OS runner with the native isolation dependency",
)
@pytest.mark.xfail(
    sys.platform == "win32",
    reason=(
        "Windows runner port binding is flaky (WinError 10061); "
        "see PR #7260 CI"
    ),
    strict=False,
)
def test_hub_starts_and_proxies_local_runtime(tmp_path: Path) -> None:
    """Start a real Hub and verify its managed QwenPaw HTTP endpoint."""
    port = _allocate_port()
    hub_root = tmp_path / "hub"
    hub_root.mkdir(parents=True)
    log_path = tmp_path / "hub.log"
    environment = _hub_environment(hub_root)
    command = [
        sys.executable,
        "-m",
        "qwenpaw",
        "hub",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "debug",
    ]
    token = ""
    failure: Exception | None = None
    with log_path.open("w", encoding="utf-8") as log_handle:
        # pylint: disable-next=consider-using-with
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=hub_root,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                timeout=90,
            ) as client:
                _wait_for_hub(client, process)
                registration = client.post(
                    "/api/auth/register",
                    json={
                        "username": "local-runtime-e2e-admin",
                        "password": "local-runtime-e2e-password",
                    },
                )
                assert registration.status_code == 200, registration.text
                token = str(registration.json()["token"])
                headers = {"Authorization": f"Bearer {token}"}

                _wait_for_runtime(client, process, headers)
                health = client.get("/api/healthz", headers=headers)
                assert health.status_code == 200, health.text
                assert health.json()["status"] in {"ok", "healthy"}

                runtimes = client.get(
                    "/api/hub/runtimes",
                    headers=headers,
                )
                assert runtimes.status_code == 200, runtimes.text
                items = runtimes.json()["items"]
                assert len(items) == 1
                assert items[0]["state"] == "running"
                assert items[0]["provisioner"] == "local"
                stopped = client.post(
                    f"/api/hub/runtimes/{items[0]['runtime_id']}/stop",
                    headers=headers,
                )
                assert stopped.status_code == 200, stopped.text
                assert stopped.json()["state"] == "stopped"
        except Exception as exc:  # pylint: disable=broad-exception-caught
            failure = exc
        finally:
            if process.poll() is None:
                if token:
                    try:
                        with httpx.Client(
                            base_url=f"http://127.0.0.1:{port}",
                            timeout=5,
                        ) as cleanup_client:
                            _stop_runtime(cleanup_client, token)
                    except httpx.HTTPError:
                        pass
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    if failure is not None:
        pytest.fail(
            f"{failure}\n"
            f"Hub log:\n{log_path.read_text(encoding='utf-8')}\n"
            f"Runtime logs:\n{_runtime_logs(hub_root)}",
        )
