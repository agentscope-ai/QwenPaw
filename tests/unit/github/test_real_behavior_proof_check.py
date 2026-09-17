# -*- coding: utf-8 -*-
"""Unit tests for real_behavior_proof_check.py CI entry point.

Covers event payload parsing, missing fields, and label API failure
paths that the pure-policy tests do not exercise.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=wrong-import-position,line-too-long,unused-import
# flake8: noqa: E501
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock  # noqa: E402

# Add scripts/github to path.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "scripts" / "github"),
)

import real_behavior_proof_check as check_mod  # noqa: E402


def _write_event(tmp_path: Path, pr_data: dict) -> str:
    """Write a GitHub Actions event payload to a temp file and return
    its path."""
    event = {"pull_request": pr_data}
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    return str(path)


class TestEventPayloadParsing:
    """Verify that main() correctly reads PR fields from the GitHub
    Actions event payload."""

    @staticmethod
    def test_passes_with_valid_body(tmp_path: Path):
        event_path = _write_event(
            tmp_path,
            {
                "body": "## Description\n\nFixed a bug.\n\n## Evidence\n\npytest passed.",
                "author_association": "CONTRIBUTOR",
                "user": {"login": "contributor", "type": "User"},
                "labels": [],
                "number": 42,
                "html_url": "https://github.com/test/repo/pull/42",
            },
        )
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path}):
            assert check_mod.main() == 0

    @staticmethod
    def test_fails_with_missing_evidence(tmp_path: Path):
        event_path = _write_event(
            tmp_path,
            {
                "body": "## Description\n\nFixed a bug.",
                "author_association": "CONTRIBUTOR",
                "user": {"login": "contributor", "type": "User"},
                "labels": [],
                "number": 42,
            },
        )
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path}):
            assert check_mod.main() == 1

    @staticmethod
    def test_skips_maintainer(tmp_path: Path):
        event_path = _write_event(
            tmp_path,
            {
                "body": "",
                "author_association": "MEMBER",
                "user": {"login": "maint", "type": "User"},
                "labels": [],
                "number": 1,
            },
        )
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path}):
            assert check_mod.main() == 0

    @staticmethod
    def test_skips_bot(tmp_path: Path):
        event_path = _write_event(
            tmp_path,
            {
                "body": "",
                "author_association": "NONE",
                "user": {"login": "bot", "type": "Bot"},
                "labels": [],
                "number": 1,
            },
        )
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path}):
            assert check_mod.main() == 0


class TestMissingFields:
    """Verify graceful handling of missing or empty PR fields."""

    @staticmethod
    def test_handles_missing_body(tmp_path: Path):
        event_path = _write_event(
            tmp_path,
            {
                "author_association": "CONTRIBUTOR",
                "user": {"login": "c", "type": "User"},
                "labels": [],
            },
        )
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path}):
            # Missing body → missing sections → exit 1
            assert check_mod.main() == 1

    @staticmethod
    def test_handles_none_body(tmp_path: Path):
        event_path = _write_event(
            tmp_path,
            {
                "body": None,
                "author_association": "CONTRIBUTOR",
                "user": {"login": "c", "type": "User"},
                "labels": [],
            },
        )
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path}):
            assert check_mod.main() == 1

    @staticmethod
    def test_handles_missing_pull_request_key(tmp_path: Path):
        """When GITHUB_EVENT_PATH points to a file with no
        pull_request key (e.g. push event)."""
        path = tmp_path / "event.json"
        path.write_text(json.dumps({"ref": "refs/heads/main"}))
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(path)}):
            # No PR data → empty body → missing → exit 1
            assert check_mod.main() == 1

    @staticmethod
    def test_handles_missing_event_file(tmp_path: Path):
        """When GITHUB_EVENT_PATH doesn't exist (e.g. local run)."""
        with mock.patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": str(tmp_path / "nonexistent.json")},
        ):
            # No event file → empty pr dict → missing → exit 1
            assert check_mod.main() == 1


class TestLabelParsing:
    """Verify label extraction from PR payload."""

    @staticmethod
    def test_reads_labels_from_event(tmp_path: Path):
        event_path = _write_event(
            tmp_path,
            {
                "body": "## Description\n\nx.\n\n## Evidence\n\ny.",
                "author_association": "CONTRIBUTOR",
                "user": {"login": "c", "type": "User"},
                "labels": [
                    {"name": "proof: sufficient"},
                    {"name": "bug"},
                ],
            },
        )
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path}):
            # proof: sufficient label → skipped
            assert check_mod.main() == 0

    @staticmethod
    def test_handles_empty_labels_list(tmp_path: Path):
        event_path = _write_event(
            tmp_path,
            {
                "body": "## Description\n\nx.\n\n## Evidence\n\ny.",
                "author_association": "CONTRIBUTOR",
                "user": {"login": "c", "type": "User"},
                "labels": [],
            },
        )
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path}):
            assert check_mod.main() == 0
