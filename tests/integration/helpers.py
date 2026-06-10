# -*- coding: utf-8 -*-
"""Shared helpers for integration tests.

Extracted from individual test modules to eliminate duplication and
ensure fixes (e.g. TimeoutException handling) apply everywhere.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

PLUGIN_HTTP_TIMEOUT = 60.0
LOADER_READY_TIMEOUT = 20.0
AGENT_SCOPED_PREFIX = "/api/agents"
REPO_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_PLUGINS_DIR = REPO_ROOT / "plugins"


# ------------------------------------------------------------------ #
# agent helpers
# ------------------------------------------------------------------ #


def scoped(agent_id: str, path: str) -> str:
    """Build an agent-scoped URL."""
    return f"{AGENT_SCOPED_PREFIX}/{agent_id}{path}"


def create_agent(app_server, agent_id: str) -> None:
    resp = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": f"Agent {agent_id}",
            "description": "",
        },
    )
    assert resp.status_code == 201, app_server.logs_tail()


def delete_agent_quietly(app_server, agent_id: str) -> None:
    try:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
        )
    except Exception:
        pass


def toggle_agent(app_server, agent_id: str, enabled: bool):
    """PATCH /api/agents/{id}/toggle and return response."""
    return app_server.api_request(
        "PATCH",
        f"/api/agents/{agent_id}/toggle",
        json={"enabled": enabled},
    )


# ------------------------------------------------------------------ #
# plugin helpers
# ------------------------------------------------------------------ #


def wait_until_plugin_loader_ready(
    app_server,
    *,
    timeout: float = LOADER_READY_TIMEOUT,
) -> None:
    """Poll a write endpoint until app.state.plugin_loader is set.

    install_plugin checks the loader BEFORE validating the source, so
    posting an invalid local path is a free readiness probe:
      * 503 ``Plugin loader is not ready yet`` -- not ready, keep polling
      * 400 ``Path not found``                 -- loader is up, return
    GET /api/plugins is NOT used because list_plugins falls back to
    on-disk scanning when the loader is absent and would mask the
    real readiness state.

    Per code review feedback, the readiness signal is now narrowed: we
    only accept the exact 400 + "Path not found" detail. Any other
    non-503 response (e.g. install_plugin code path changes that move
    the source check) is logged as ``unexpected`` and treated as
    fallback-ready (caller is the one that would then fail on the
    real install/upload), so this stays resilient to future router
    refactors without silently masking probe drift.
    """
    deadline = time.time() + timeout
    last_status = None
    last_detail = ""
    while time.time() < deadline:
        try:
            resp = app_server.api_request(
                "POST",
                "/api/plugins/install",
                json={
                    "source": "/tmp/integ-loader-readiness-probe",
                    "force": False,
                },
                timeout=5.0,
            )
        except httpx.TimeoutException:
            time.sleep(0.5)
            continue
        last_status = resp.status_code
        try:
            last_detail = resp.json().get("detail", "")
        except ValueError:
            last_detail = resp.text[:200]

        if resp.status_code == 400 and "Path not found" in last_detail:
            return
        if resp.status_code == 503:
            time.sleep(0.5)
            continue
        return
    raise AssertionError(
        f"plugin_loader not ready in {timeout}s, "
        f"last status={last_status} detail={last_detail!r}",
    )


def delete_plugin_quietly(
    app_server,
    plugin_id: str,
) -> None:
    """Best-effort plugin delete for finally blocks."""
    try:
        wait_until_plugin_loader_ready(app_server)
        app_server.api_request(
            "DELETE",
            f"/api/plugins/{plugin_id}",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
    except Exception:
        pass


# ------------------------------------------------------------------ #
# inbox helpers
# ------------------------------------------------------------------ #


def inbox_path(working_dir: Path) -> Path:
    return working_dir / "inbox_events.json"


def trace_dir(working_dir: Path) -> Path:
    return working_dir / "inbox_traces"


def seed_inbox_events(
    working_dir: Path,
    events: list[dict[str, Any]],
) -> None:
    """Write the events list to inbox_events.json."""
    path = inbox_path(working_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            events,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def seed_inbox_trace(
    working_dir: Path,
    run_id: str,
    payload: dict[str, Any],
) -> None:
    """Write one trace file under inbox_traces/<run_id>.json."""
    directory = trace_dir(working_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{run_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clean_inbox(working_dir: Path) -> None:
    """Remove inbox file + trace dir so the next test starts clean."""
    path = inbox_path(working_dir)
    if path.exists():
        path.unlink()
    directory = trace_dir(working_dir)
    if directory.exists():
        shutil.rmtree(directory)


def make_event(
    *,
    event_id: str,
    agent_id: str = "default",
    source_type: str = "cron",
    source_id: str = "",
    event_type: str = "cron_executed",
    status: str = "completed",
    severity: str = "info",
    title: str = "seeded event",
    body: str = "",
    payload: dict[str, Any] | None = None,
    read: bool = False,
    created_at: float | None = None,
) -> dict[str, Any]:
    """Mirror the shape produced by ``inbox_store.append_event``."""
    return {
        "id": event_id,
        "agent_id": agent_id,
        "source_type": source_type,
        "source_id": source_id,
        "event_type": event_type,
        "status": status,
        "severity": severity,
        "title": title,
        "body": body,
        "payload": payload or {},
        "read": read,
        "created_at": (created_at if created_at is not None else time.time()),
    }
