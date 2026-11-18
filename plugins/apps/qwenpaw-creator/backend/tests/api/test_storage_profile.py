# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""GET /storage/profile reports the runtime footprint without touching it."""

from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

TOTAL_KEYS = {
    "taskWorkBytes",
    "taskWorkLegacyBytes",
    "taskWorkReclaimableBytes",
    "transactionsBytes",
    "transactionsLegacyBytes",
    "orphanBytes",
}


def test_profile_answers_even_with_no_projects(
    api_request,
    app,
    api_runtime_root,
):
    response = api_request(app, "GET", "/storage/profile")

    assert response.status_code == 200
    body = response.json()
    assert Path(body["dataRoot"]).is_dir()
    assert body["scratchReleaseEnabled"] is True
    assert body["projects"] == []
    assert set(body["totals"]) == TOTAL_KEYS
    assert all(value == 0 for value in body["totals"].values())


def test_orphan_scan_is_opt_in(api_request, app):
    response = api_request(
        app,
        "GET",
        "/storage/profile",
        params={"includeOrphans": "true"},
    )

    assert response.status_code == 200
    assert set(response.json()["totals"]) == TOTAL_KEYS
