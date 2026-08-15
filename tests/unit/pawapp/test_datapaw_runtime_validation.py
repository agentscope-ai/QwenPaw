# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Load-time validation of the datapaw context-service configuration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAIN_FILE = (
    REPOSITORY_ROOT / "plugins" / "apps" / "datapaw" / "backend" / "main.py"
)


@pytest.fixture(scope="module")
def backend():
    spec = importlib.util.spec_from_file_location(
        "datapaw_main_runtime_validation",
        MAIN_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_context_env(monkeypatch):
    for name in (
        "DATAPAW_CONTEXT_MODE",
        "DATAPAW_CONTEXT_URL",
        "DATAPAW_CONTEXT_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_external_mode_with_url_and_token_is_valid(
    backend,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATAPAW_CONTEXT_MODE", "external")
    monkeypatch.setenv("DATAPAW_CONTEXT_URL", "http://127.0.0.1:8300")
    monkeypatch.setenv("DATAPAW_CONTEXT_TOKEN", "secret")

    assert backend._context_runtime_issue() is None


def test_external_mode_without_endpoint_reports_missing_vars(
    backend,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATAPAW_CONTEXT_MODE", "external")

    issue = backend._context_runtime_issue()

    assert issue is not None
    assert issue["code"] == "EXTERNAL_MODE_INCOMPLETE"
    assert "DATAPAW_CONTEXT_URL" in issue["message"]
    assert "DATAPAW_CONTEXT_TOKEN" in issue["message"]
    assert issue["remediation"]


def test_external_url_without_token_reports_the_token(
    backend,
    monkeypatch,
) -> None:
    # Setting the URL alone selects external mode implicitly.
    monkeypatch.setenv("DATAPAW_CONTEXT_URL", "http://127.0.0.1:8300")

    issue = backend._context_runtime_issue()

    assert issue is not None
    assert issue["code"] == "EXTERNAL_MODE_INCOMPLETE"
    assert "DATAPAW_CONTEXT_TOKEN" in issue["message"]
    assert "DATAPAW_CONTEXT_URL" not in issue["message"]


def test_managed_mode_without_runtime_reports_runtime_missing(
    backend,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        backend._context_service,
        "runtime_available",
        lambda: False,
    )

    issue = backend._context_runtime_issue()

    assert issue is not None
    assert issue["code"] == "RUNTIME_MISSING"
    assert "DATAPAW_CONTEXT_MODE=external" in issue["remediation"]


def test_managed_mode_with_runtime_is_valid(backend, monkeypatch) -> None:
    monkeypatch.setattr(
        backend._context_service,
        "runtime_available",
        lambda: True,
    )

    assert backend._context_runtime_issue() is None
