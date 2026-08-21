#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed the QwenPaw Data docker-compose demo.

This script is meant to run inside the `seed` container once PostgreSQL and the
context service are healthy. It:

1. Creates the GAAP demo table and inserts 475 rows from the bundled SQL.
2. Imports the bundled semantic workbook into the context service.
3. Configures the PostgreSQL datasource in semantic config.
4. Submits a weave task and waits for it to finish.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

import psycopg

from context_manager.demo.loader import (
    seed_postgres_sql,
    semantic_workbook_bytes,
)


DEMO_DATASOURCE_ID = "postgresql-demo-gaap"
DEMO_DATASOURCE_NAME = "Demo PG - GAAP use case"


def _env(key: str, default: str) -> str:
    return os.getenv(key, default).strip()


def _auth_headers() -> dict[str, str]:
    token = _env("CONTEXT_TOKEN", "qwenpaw-data-demo-token")
    return {"Authorization": f"Bearer {token}"}


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, object] | None = None,
    timeout: float = 30.0,
) -> object:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"context service returned HTTP {exc.code}: {detail}",
        ) from exc


def _request_file(
    url: str,
    filename: str,
    content: bytes,
    *,
    headers: dict[str, str],
    timeout: float = 60.0,
) -> object:
    boundary = f"----QwenPawDataDemo{uuid.uuid4().hex}"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            (
                b"Content-Type: application/vnd.openxmlformats-officedocument."
                b"spreadsheetml.sheet\r\n\r\n"
            ),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ],
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            **headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"context service returned HTTP {exc.code}: {detail}",
        ) from exc


def seed_postgres(dsn: str) -> None:
    """Execute the bundled seed SQL."""
    sql = seed_postgres_sql()
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            cursor.execute("SELECT COUNT(*) FROM dws_gaap_di")
            count = int(cursor.fetchone()[0])
    print(f"PostgreSQL demo seeded: {count} rows in dws_gaap_di")


def import_workbook(base_url: str) -> dict[str, object]:
    """Upload the bundled semantic workbook."""
    workbook_bytes = semantic_workbook_bytes()
    result = _request_file(
        f"{base_url}/api/semantic-config/import/excel",
        "demo_semantic_config.xlsx",
        workbook_bytes,
        headers=_auth_headers(),
    )
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError(f"semantic demo import failed: {result!r}")
    print(
        "Semantic workbook imported:",
        json.dumps(result.get("summary", {}), sort_keys=True),
    )
    return result


def configure_datasource(base_url: str) -> None:
    """Point the demo datasource at the PostgreSQL container."""
    dsn = _env(
        "POSTGRES_DSN",
        "postgresql://qwenpaw_data:qwenpaw-data-demo@postgres:5432/"
        "qwenpaw_data_demo",
    )
    # Parse the DSN so we can send structured config.
    parsed = psycopg.conninfo.conninfo_to_dict(dsn)
    configured = _request_json(
        f"{base_url}/api/semantic-config/datasource/{DEMO_DATASOURCE_ID}",
        method="PUT",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        payload={
            "datasource_name": DEMO_DATASOURCE_NAME,
            "datasource_type": "postgresql",
            "config": {
                "host": parsed.get("host", "postgres"),
                "port": int(parsed.get("port", "5432")),
                "dbname": parsed.get("dbname", "qwenpaw_data_demo"),
                "user": parsed.get("user", "qwenpaw_data"),
                "password": parsed.get("password", "qwenpaw-data-demo"),
            },
        },
    )
    if (
        not isinstance(configured, dict)
        or configured.get("datasource_id") != DEMO_DATASOURCE_ID
    ):
        raise RuntimeError(
            f"demo datasource configuration failed: {configured!r}",
        )
    print(f"Configured DataBridge datasource: {DEMO_DATASOURCE_ID}")


def submit_weave(base_url: str) -> dict[str, object]:
    """Submit a FULL weave for the demo datasource and wait for completion."""
    task = _request_json(
        f"{base_url}/api/semantic-config/weave-task/submit",
        method="POST",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        payload={
            "datasource_id": DEMO_DATASOURCE_ID,
            "task_name": "docker-compose-demo-seed",
            "weave_mode": "FULL",
        },
    )
    if not isinstance(task, dict):
        raise RuntimeError(f"weave submit failed: {task!r}")
    task_id = task.get("task_id")
    print(f"Weave task submitted: {task_id}")

    deadline = time.monotonic() + 600
    status = task.get("status", "RUNNING")
    while status not in {"SUCCESS", "FAILED", "KILLED"}:
        if time.monotonic() > deadline:
            raise RuntimeError(f"timed out waiting for weave task {task_id}")
        time.sleep(2)
        page = _request_json(
            f"{base_url}/api/semantic-config/weave-task?page=1&size=100",
            headers=_auth_headers(),
        )
        if isinstance(page, dict) and isinstance(page.get("records"), list):
            for record in page["records"]:
                if (
                    isinstance(record, dict)
                    and record.get("task_id") == task_id
                ):
                    status = record.get("status", status)
                    task = record
                    break
        print(f"  weave status: {status}")

    if status != "SUCCESS":
        raise RuntimeError(
            f"weave task {task_id} finished with status {status}: {task!r}",
        )
    print("Weave completed successfully")
    return task


def wait_for_context(base_url: str, timeout: float = 120.0) -> None:
    """Poll the context health endpoint until it responds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=5):
                print("Context service is healthy")
            return
        except urllib.error.URLError:
            time.sleep(2)
    raise RuntimeError("context service did not become healthy in time")


def main() -> int:
    base_url = _env("CONTEXT_URL", "http://context:8765").rstrip("/")
    dsn = _env(
        "POSTGRES_DSN",
        "postgresql://qwenpaw_data:qwenpaw-data-demo@postgres:5432/"
        "qwenpaw_data_demo",
    )

    try:
        wait_for_context(base_url)
        seed_postgres(dsn)
        import_workbook(base_url)
        configure_datasource(base_url)
        submit_weave(base_url)
    except (
        OSError,
        RuntimeError,
        psycopg.Error,
        urllib.error.URLError,
    ) as exc:
        print(f"demo seed failed: {exc}", file=sys.stderr)
        return 1

    print("Demo seed complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
