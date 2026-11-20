# -*- coding: utf-8 -*-
"""
E2E regression test: cron run token usage lands in session turn records.

Covers #8705: agent-type cron runs execute via workspace.stream_query
directly, skipping Channel._commit_turn_usage, so their token usage was
never persisted to the session's turn records.

This test drives a real cron run against a real model and then checks
the session state file on disk for ``qwenpaw_turn_usage`` metadata on
the closing assistant message.

Requires:
- Isolated test backend: e2e/scripts/start_test_server.sh
- QWENPAW_DASHSCOPE_API_KEY set (real model call; skipped otherwise)

Run: pytest tests/test_cron_usage.py -v
"""
from __future__ import annotations

import json
import logging
import time

import pytest

from config.settings import config
from utils.helpers import log_test_result, log_test_step

logger = logging.getLogger(__name__)

TURN_USAGE_META_KEY = "qwenpaw_turn_usage"
_RUN_POLL_TIMEOUT_S = 180
_RUN_POLL_INTERVAL_S = 2


def _job_spec(name: str) -> dict:
    # Far-future schedule so the job only runs when triggered manually.
    return {
        "name": name,
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": "0 0 1 1 *",
            "timezone": "UTC",
        },
        "task_type": "agent",
        "request": {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Reply with exactly: ok",
                        },
                    ],
                },
            ],
        },
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {"user_id": "default", "session_id": "default"},
        },
    }


def _find_usage_meta(working_dir, job_id: str) -> dict | None:
    """Return the first qwenpaw_turn_usage meta found in cron session files."""
    candidates = list(working_dir.glob("**/sessions/**/*.json"))
    # Prefer the exact job's session file, then fall back to any cron one.
    matches = [p for p in candidates if job_id in p.name] or [
        p for p in candidates if "cron" in p.name.lower()
    ]
    for path in matches:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to read session file %s: %s", path, exc)
            continue

        def _walk(node):
            if isinstance(node, dict):
                if TURN_USAGE_META_KEY in node:
                    return node[TURN_USAGE_META_KEY]
                for value in node.values():
                    found = _walk(value)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for value in node:
                    found = _walk(value)
                    if found is not None:
                        return found
            return None

        found = _walk(data)
        if found is not None:
            return found
    return None


def _wait_for_run_done(api_context, job_id: str, page) -> dict:
    """Poll job history until a terminal record appears."""
    deadline = time.time() + _RUN_POLL_TIMEOUT_S
    while time.time() < deadline:
        resp = api_context.get(f"/api/cron/jobs/{job_id}/history")
        assert resp.ok, f"History failed [{resp.status}]: {resp.text()}"
        records = resp.json()
        for record in records:
            if record.get("status") in ("success", "error", "cancelled"):
                return record
        page.wait_for_timeout(_RUN_POLL_INTERVAL_S * 1000)
    raise AssertionError(
        f"Cron run did not finish within {_RUN_POLL_TIMEOUT_S}s",
    )


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cronjobs
@pytest.mark.requires_llm
class TestCronTurnUsagePersistence:
    """
    CRON-USAGE-001: cron agent run persists token usage into turn records.

    Create an agent cron job, trigger it manually, wait for completion,
    then assert the session state file contains qwenpaw_turn_usage with
    a positive token count.
    """

    @pytest.mark.test_id("CRON-USAGE-001")
    def test_cron_run_usage_persisted(
        self,
        page,
        api_context,
        request: pytest.FixtureRequest,
    ):
        test_name = request.node.name
        job_name = f"e2e-usage-{int(time.time()) % 100000}"

        log_test_step("1. Create agent cron job via API")
        resp = api_context.post("/api/cron/jobs", data=_job_spec(job_name))
        assert resp.ok, f"Create job failed [{resp.status}]: {resp.text()}"
        job_id = resp.json().get("id")
        assert job_id, "No job id returned"
        logger.info("Created job %s", job_id)

        try:
            log_test_step("2. Trigger manual execution")
            run_resp = api_context.post(f"/api/cron/jobs/{job_id}/run")
            assert (
                run_resp.ok
            ), f"Run trigger failed [{run_resp.status}]: {run_resp.text()}"

            log_test_step("3. Wait for the run to finish")
            record = _wait_for_run_done(api_context, job_id, page)
            assert record["status"] == "success", (
                f"Cron run ended with {record['status']}: "
                f"{record.get('error')}"
            )

            log_test_step("4. Assert usage meta in session turn records")
            # Give the session state writer a moment to flush.
            page.wait_for_timeout(2000)
            meta = _find_usage_meta(config.working_dir, job_id)
            assert meta is not None, (
                f"No {TURN_USAGE_META_KEY} meta found in cron session "
                "files under the working dir"
            )
            usage = meta.get("usage") or {}
            total = usage.get("total_tokens")
            assert isinstance(total, int) and total > 0, (
                f"Expected positive total_tokens in usage meta, got: "
                f"{meta}"
            )
            logger.info("Cron turn usage persisted: %s", usage)
            log_test_result(test_name, "PASS", "cron usage persisted")
        finally:
            log_test_step("5. Cleanup cron job")
            try:
                del_resp = api_context.delete(f"/api/cron/jobs/{job_id}")
                logger.info("Delete job [%s]", del_resp.status)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Failed to delete job %s: %s", job_id, exc)
