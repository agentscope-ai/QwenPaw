# -*- coding: utf-8 -*-
"""Chrome plugin integration contracts grouped by runtime boundary."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path("plugins/bundle/chrome/assets/scripts")


def _load(name: str):
    """Load a Native Messaging helper locally for this test module."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            name,
            SCRIPTS / f"{name}.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


# test_chrome_command_receipt_honesty.py

SERVICE_WORKER = Path(
    "plugins/bundle/chrome/assets/extensions/chrome/service_worker.js",
)
HARNESS = Path("tests/integration/js/service_worker_harness.mjs")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is required to execute the service worker harness",
)


def run_scenario(name: str, **payload: object) -> dict:
    completed = subprocess.run(
        ["node", str(HARNESS), str(SERVICE_WORKER)],
        input=json.dumps({"scenario": name, **payload}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_running_is_durable_before_the_executor_runs() -> None:
    result = run_scenario("execute_order")
    assert result["stateWhenExecutorRan"] == "RUNNING"
    assert result["states"] == ["RECEIVED", "RUNNING", "COMPLETED"]


def test_receipts_carry_the_executor_epoch() -> None:
    first = run_scenario("epoch_present")
    second = run_scenario("epoch_present")
    assert first["receipt"]["executorEpoch"]
    assert (
        first["receipt"]["executorEpoch"] != second["receipt"]["executorEpoch"]
    )


def test_status_query_writes_nothing_and_keeps_the_target() -> None:
    result = run_scenario("status_pure_read", queries=300)
    assert result["storageSetCalls"] == 0
    assert result["storageRemoveCalls"] == 0
    assert result["targetReceiptStillPresent"] is True


@pytest.mark.parametrize(
    "case,expected",
    [
        ("completed", "COMPLETED"),
        ("received_stale_epoch", "NOT_STARTED"),
        ("received_current_epoch", "IN_FLIGHT"),
        ("running_current_epoch", "IN_FLIGHT"),
        ("running_stale_epoch", "ABANDONED"),
        ("evicted", "LOST"),
        ("absent", "UNKNOWN"),
    ],
)
def test_observed_state_closed_set(case, expected) -> None:
    result = run_scenario("observed_states", case=case)
    assert result["observedState"] == expected


def test_stale_receipt_is_never_reexecuted() -> None:
    result = run_scenario("stale_epoch_no_reexec")
    assert result["executorCalls"] == 0
    assert result["receiptState"] in {"RECEIVED", "RUNNING"}


# test_chrome_cdp_send_guard.py

SERVICE_WORKER = Path(
    "plugins/bundle/chrome/assets/extensions/chrome/service_worker.js",
)


# test_chrome_dialog_capability.py

SERVICE_WORKER = Path(
    "plugins/bundle/chrome/assets/extensions/chrome/service_worker.js",
)


# test_chrome_extension_tab_lease_cohesion.py

WORKER = Path(
    "plugins/bundle/chrome/assets/extensions/chrome/service_worker.js",
)


# test_chrome_protocol_parity.py


# test_chrome_self_degradation.py

WORKER = Path(
    "plugins/bundle/chrome/assets/extensions/chrome/service_worker.js",
)


def _function_body(source: str, name: str, next_name: str) -> str:
    return source.split(name, 1)[1].split(next_name, 1)[0]


# test_chrome_silent_guard_removed.py

SERVICE_WORKER = Path(
    "plugins/bundle/chrome/assets/extensions/chrome/service_worker.js",
)


# test_chrome_watchdog_reconnect.py

WORKER = Path(
    "plugins/bundle/chrome/assets/extensions/chrome/service_worker.js",
)
