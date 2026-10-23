"""W2 precise host-only retained-lease error API; real owner identity unit."""

from qwenpaw.app.channels.management import ManagementError
from qwenpaw.plugins.ownership import (
    RuntimeKey,
    RuntimeOwners,
    RuntimeStopReceipt,
)


def test_cleanup_failure_error_carries_exact_lease_without_changing_safe_reason(
    tmp_path,
):
    owners = RuntimeOwners()
    exact = owners.reserve(
        "sample",
        RuntimeKey("management", "sample", "A"),
        tmp_path / "sample",
        instance_id="exact-worker",
    )
    error = ManagementError(
        "MANAGEMENT_CLEANUP_FAILED",
        needs_restart=True,
        receipt=RuntimeStopReceipt(False, exited=False),
        lease=exact,
    )
    assert error.lease is exact
    assert str(error) == "MANAGEMENT_CLEANUP_FAILED"
    assert error.reason_code == "MANAGEMENT_CLEANUP_FAILED"
    assert error.needs_restart and not error.receipt.stopped
