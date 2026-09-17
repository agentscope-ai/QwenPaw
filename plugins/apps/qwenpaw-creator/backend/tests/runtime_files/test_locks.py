# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=arguments-out-of-order
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import multiprocessing

import pytest

from services.runtime_files import (
    CrossProcessFileLock,
    FieldBlockConflictError,
    FieldBlockBaseConflictError,
    FieldBlockStore,
    FieldBlockTokenError,
    LockTimeoutError,
    pointers_overlap,
)


pytestmark = pytest.mark.unit


def _hold_lock(path: str, ready, release) -> None:
    with CrossProcessFileLock(path, timeout_seconds=2):
        ready.set()
        release.wait(timeout=5)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 15, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def test_fcntl_lock_times_out_across_processes_and_releases_on_exit(tmp_path):
    path = tmp_path / "project-write.lock"
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_lock,
        args=(str(path), ready, release),
    )
    process.start()
    assert ready.wait(timeout=3)

    with pytest.raises(LockTimeoutError):
        with CrossProcessFileLock(
            path,
            timeout_seconds=0.05,
            poll_interval_seconds=0.005,
        ):
            pass

    # Simulate a worker crash rather than a graceful context-manager exit.  The
    # OS must release the advisory lock when it closes the dead descriptor.
    process.terminate()
    process.join(timeout=3)
    assert process.exitcode not in {None, 0}
    with CrossProcessFileLock(path, timeout_seconds=0.2):
        assert path.exists()


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("", "/story", True),
        ("/story", "/story/title", True),
        ("/story/title", "/story/title", True),
        ("/story/1", "/story/10", False),
        ("/a~1b", "/a/b", False),
        ("/a~1b", "/a~1b/title", True),
    ],
)
def test_json_pointer_overlap_is_segment_aware(first, second, expected):
    assert pointers_overlap(first, second) is expected
    assert pointers_overlap(second, first) is expected


def test_field_blocks_conflict_on_ancestor_and_expire_by_ttl(tmp_path):
    clock = MutableClock()
    store = FieldBlockStore(
        tmp_path / "runtime" / "locks" / "fields",
        clock=clock,
    )
    title = store.acquire(
        project_id="project-1",
        json_pointer="/timelines/items/timeline:main/elements_by_id/element-1",
        owner_kind="user",
        owner_id="browser-1",
        base_field_hash="sha256:before",
        ttl_seconds=5,
    )

    with pytest.raises(FieldBlockConflictError) as caught:
        store.acquire(
            project_id="project-1",
            json_pointer="/timelines/items/timeline:main/elements_by_id/element-1/label",
            owner_kind="agent",
            owner_id="run-1",
            base_field_hash="sha256:before",
            ttl_seconds=5,
        )
    assert caught.value.block.block_id == title.block_id

    sibling = store.acquire(
        project_id="project-1",
        json_pointer="/timelines/items/timeline:main/elements_by_id/element-10/label",
        owner_kind="agent",
        owner_id="run-1",
        base_field_hash="sha256:other",
        ttl_seconds=5,
    )
    assert len(store.list_active(project_id="project-1")) == 2

    with pytest.raises(FieldBlockTokenError):
        store.release(sibling.block_id, token="wrong-token")
    renewed = store.renew(
        sibling.block_id,
        token=sibling.token,
        ttl_seconds=10,
    )
    assert renewed.expires_at == clock.value + timedelta(seconds=10)

    clock.value += timedelta(seconds=11)
    assert set(store.cleanup_expired()) == {title.block_id, sibling.block_id}
    assert store.list_active() == []


def test_field_block_release_is_idempotent_after_valid_release(tmp_path):
    store = FieldBlockStore(tmp_path / "fields")
    block = store.acquire(
        project_id="project-1",
        json_pointer="/strategy/title",
        owner_kind="user",
        owner_id="browser-1",
        base_field_hash="sha256:before",
        ttl_seconds=30,
    )
    assert store.release(block.block_id, token=block.token) is True
    assert store.release(block.block_id, token=block.token) is False


def test_field_block_base_is_checked_under_index_lock(tmp_path):
    store = FieldBlockStore(tmp_path / "fields")

    with pytest.raises(FieldBlockBaseConflictError) as caught:
        store.acquire(
            project_id="project-1",
            json_pointer="/name",
            owner_kind="user",
            owner_id="browser-1",
            base_field_hash="sha256:old",
            ttl_seconds=30,
            current_field_hash=lambda: "sha256:new",
        )

    assert caught.value.actual == "sha256:new"
    assert store.list_active() == []


def test_guard_write_rejects_overlap_unless_token_owns_block(tmp_path):
    store = FieldBlockStore(tmp_path / "fields")
    block = store.acquire(
        project_id="project-1",
        json_pointer="/story",
        owner_kind="user",
        owner_id="browser-1",
        base_field_hash="sha256:before",
        ttl_seconds=30,
    )

    with pytest.raises(FieldBlockConflictError):
        with store.guard_write(
            project_id="project-1",
            json_pointers=["/story/title"],
        ):
            pass

    with store.guard_write(
        project_id="project-1",
        json_pointers=["/story/title"],
        token=block.token,
    ):
        pass
