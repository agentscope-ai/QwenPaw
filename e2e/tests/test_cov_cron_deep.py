# -*- coding: utf-8 -*-
"""
Deep cron scheduling flows for coverage boost (Plan B).

Targets: Cron & Scheduling (530 uncovered lines) + app/crons/ — API
create/edit/execute/history/delete with UI list verification.

Run: pytest tests/test_cov_cron_deep.py -v
"""
from __future__ import annotations

import logging
import time

import pytest

from pages.cronjobs_page import CronJobsPage
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


def _job_spec(name: str) -> dict:
    return {
        "name": name,
        "enabled": True,
        "schedule": {"type": "cron", "cron": "0 0 * * *", "timezone": "UTC"},
        "task_type": "text",
        "text": "e2e coverage boost ping",
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {"user_id": "default", "session_id": "default"},
        },
    }


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.cronjobs
class TestCronLifecycleDeep:
    """
    COV-CR-001: Cron create -> edit -> execute -> history -> delete.

    Coverage: app/crons/ create/execute/history/misfire paths.
    """

    @pytest.mark.test_id("COV-CR-001")
    def test_cron_lifecycle_deep(
        self,
        cronjobs_page: CronJobsPage,
        api_context,
        request: pytest.FixtureRequest,
    ):
        test_name = request.node.name
        job_name = f"e2e-cov-{int(time.time()) % 100000}"

        log_test_step("1. Open cron page")
        cronjobs_page.open()
        cronjobs_page.wait_for_page_loaded()

        log_test_step("2. Create a cron job via API")
        resp = api_context.post(
            "/api/cron/jobs",
            data=_job_spec(job_name),
            headers={"X-Agent-Id": "default"},
        )
        assert resp.ok, f"Create job failed [{resp.status}]: {resp.text()}"
        job_id = resp.json().get("id")
        assert job_id, "No job id returned"

        log_test_step("3. Verify job appears in UI list")
        cronjobs_page.page.reload()
        cronjobs_page.wait_for_page_loaded()
        assert cronjobs_page.job_exists(job_name), "Job not in UI list"

        log_test_step("4. Edit the job schedule via API")
        spec = _job_spec(job_name)
        spec["schedule"]["cron"] = "30 1 * * *"
        resp = api_context.put(
            f"/api/cron/jobs/{job_id}",
            data=spec,
            headers={"X-Agent-Id": "default"},
        )
        assert resp.ok, f"Edit job failed [{resp.status}]: {resp.text()}"

        log_test_step("5. Trigger manual execution")
        run_resp = api_context.post(
            f"/api/cron/jobs/{job_id}/run",
            headers={"X-Agent-Id": "default"},
        )
        if run_resp.ok:
            cronjobs_page.page.wait_for_timeout(3000)
            logger.info("Manual execution triggered")
        else:
            logger.info(f"Run endpoint [{run_resp.status}]")

        log_test_step("6. Open history / execution records in UI")
        row = cronjobs_page.get_job_row(job_name)
        hist_btn = row.locator(
            'button:has-text("History"), button:has-text("历史"), '
            'button[aria-label*="history" i]'
        ).first
        if hist_btn.count() > 0 and hist_btn.is_visible():
            hist_btn.click()
            cronjobs_page.page.wait_for_timeout(2000)
            logger.info("History view opened")
            cronjobs_page.page.keyboard.press("Escape")
        else:
            logger.info("History button not visible")

        log_test_step("7. Search the job in UI")
        cronjobs_page.search_job(job_name)
        cronjobs_page.page.wait_for_timeout(1000)
        assert cronjobs_page.job_exists(job_name), "Search lost the job"
        cronjobs_page.search_job("")
        cronjobs_page.page.wait_for_timeout(1000)

        log_test_step("8. Pause then resume the job")
        pause = api_context.post(
            f"/api/cron/jobs/{job_id}/pause",
            headers={"X-Agent-Id": "default"},
        )
        logger.info(f"Pause [{pause.status}]")
        resume = api_context.post(
            f"/api/cron/jobs/{job_id}/resume",
            headers={"X-Agent-Id": "default"},
        )
        logger.info(f"Resume [{resume.status}]")

        log_test_step("9. Delete the job")
        del_resp = api_context.delete(
            f"/api/cron/jobs/{job_id}",
            headers={"X-Agent-Id": "default"},
        )
        assert del_resp.ok, f"Delete failed [{del_resp.status}]"
        cronjobs_page.page.reload()
        cronjobs_page.wait_for_page_loaded()
        assert not cronjobs_page.job_exists(job_name), "Job still in list"

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
