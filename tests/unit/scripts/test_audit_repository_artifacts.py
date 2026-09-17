# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from scripts.audit_repository_artifacts import classify_path


@pytest.mark.parametrize(
    ("path", "tracked", "expected"),
    [
        ("tmp/task/working/history.db", False, "business_data"),
        ("tmp/browser-screenshot.png", False, "evidence_or_backup"),
        ("playwright-report/index.html", False, "regenerable"),
        ("test-results/chat.png", False, "evidence_or_backup"),
        ("tests/unit/test_example.py", True, "tracked_maintenance_asset"),
    ],
)
def test_classification(path: str, tracked: bool, expected: str):
    assert classify_path(Path(path), tracked).category == expected
