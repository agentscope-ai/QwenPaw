import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from copaw.app.rollback.service import SnapshotService


@pytest.fixture
def temp_workspace():
    with TemporaryDirectory() as temp_dir:
        workspace_dir = Path(temp_dir)
        yield workspace_dir


@pytest.mark.asyncio
async def test_snapshot_service_init_and_track(temp_workspace):
    svc = SnapshotService(temp_workspace)

    # Init
    await svc.init()
    assert svc.git_dir.exists()
    assert (svc.git_dir / "info" / "exclude").exists()

    # Create a test file
    test_file = temp_workspace / "test.txt"
    test_file.write_text("hello world")

    # Track
    hash1 = await svc.track()
    assert hash1 is not None

    # Modify file
    test_file.write_text("hello modified")

    # Track again
    hash2 = await svc.track()
    assert hash2 is not None
    assert hash1 != hash2


@pytest.mark.asyncio
async def test_snapshot_service_patch(temp_workspace):
    svc = SnapshotService(temp_workspace)

    # Setup initial state
    f1 = temp_workspace / "f1.txt"
    f1.write_text("f1")
    hash1 = await svc.track()

    # Modify one file, create another
    f1.write_text("f1 modified")
    f2 = temp_workspace / "f2.txt"
    f2.write_text("f2")

    # Track again
    hash2 = await svc.track()

    # Get patch
    changed_files = await svc.patch(hash1)

    assert "f1.txt" in changed_files
    assert "f2.txt" in changed_files
    assert len(changed_files) == 2


@pytest.mark.asyncio
async def test_snapshot_service_revert(temp_workspace):
    svc = SnapshotService(temp_workspace)

    # Initial state
    f1 = temp_workspace / "test.txt"
    f1.write_text("initial")
    hash1 = await svc.track()

    # Changed state
    f1.write_text("changed")
    f2 = temp_workspace / "new.txt"
    f2.write_text("new")

    hash2 = await svc.track()
    patch_files = await svc.patch(hash1)

    # Revert to hash1
    success = await svc.revert(hash1, patch_files)

    assert success
    assert f1.read_text() == "initial"
    assert not f2.exists()


@pytest.mark.asyncio
async def test_snapshot_service_history(temp_workspace):
    svc = SnapshotService(temp_workspace)

    f1 = temp_workspace / "test.txt"

    # State 1
    f1.write_text("state1")
    hash1 = await svc.track()

    # State 2
    f1.write_text("state2")
    hash2 = await svc.track()
    patch2 = await svc.patch(hash1)
    await svc.add_history_entry("sess1", hash1, hash2, patch2)

    # Check latest applied
    latest = await svc.get_latest_applied()
    assert latest is not None
    assert latest.before_hash == hash1
    assert latest.after_hash == hash2
    assert latest.files == patch2
    assert latest.status == "applied"

    # Mark undone
    await svc.mark_undone(latest.id)

    # Check latest undone
    undone = await svc.get_latest_undone()
    assert undone is not None
    assert undone.id == latest.id

    # Add new history after undo should clear undone
    f1.write_text("state3")
    hash3 = await svc.track()
    patch3 = await svc.patch(hash2) # Assuming we didn't actually revert workspace in this test
    await svc.add_history_entry("sess1", hash2, hash3, patch3)

    undone_after = await svc.get_latest_undone()
    assert undone_after is None
