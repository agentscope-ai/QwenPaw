# -*- coding: utf-8 -*-
"""Concurrency regression tests for qwenpawmail's JSON ThreadStore."""
from __future__ import annotations

import threading
import json
from concurrent.futures import ThreadPoolExecutor

from qwenpawmail_mcp.errors import MailError
from qwenpawmail_mcp.thread_store import ThreadStore


def _envelope(uid: str, *, reply: bool = False) -> dict:
    return {
        "uid": uid,
        "message_id": f"<message-{uid}@example.com>",
        "references": "<message-1@example.com>" if reply else "",
        "in_reply_to": "<message-1@example.com>" if reply else "",
        "subject": "Re: hello" if reply else "hello",
        "from": "alice@example.com",
        "to": "bob@example.com",
        "date": "Tue, 28 Jul 2026 10:00:00 +0800",
        "seen": False,
        "flagged": False,
    }


class _BlockingSyncClient:
    def __init__(self, started: threading.Event, release: threading.Event):
        self.started = started
        self.release = release

    def list_folders(self):
        return [{"name": "INBOX", "flags": []}]

    def fetch_envelopes_after(self, _folder, **_kwargs):
        self.started.set()
        assert self.release.wait(timeout=2)
        return [_envelope("2", reply=True)], 1


def test_concurrent_sync_and_update_labels_preserve_both(tmp_path):
    store = ThreadStore(tmp_path)
    thread_id = store.add_message(_envelope("1"), "INBOX", "inbox")
    store.save()
    sync_started = threading.Event()
    release_sync = threading.Event()
    client = _BlockingSyncClient(sync_started, release_sync)

    with ThreadPoolExecutor(max_workers=2) as pool:
        sync_future = pool.submit(store.sync, client)
        assert sync_started.wait(timeout=1)
        labels_future = pool.submit(
            store.update_labels,
            thread_id,
            ["important"],
        )
        # update_labels must wait at the same store transaction boundary.
        assert not labels_future.done()
        release_sync.set()
        sync_future.result(timeout=2)
        labels_future.result(timeout=2)

    reloaded = ThreadStore(tmp_path)
    thread = reloaded.get_thread(thread_id)
    assert thread["message_count"] == 2
    assert "important" in thread["labels"]


def test_concurrent_update_labels_and_delete_reload_consistently(tmp_path):
    store = ThreadStore(tmp_path)
    thread_id = store.add_message(_envelope("1"), "INBOX", "inbox")
    store.save()
    start = threading.Barrier(3)

    def _update():
        start.wait(timeout=2)
        try:
            store.update_labels(thread_id, add=["temporary"])
        except MailError:
            # Valid ordering: delete acquired the transaction lock first.
            pass

    def _delete():
        start.wait(timeout=2)
        store.remove_thread(thread_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        update_future = pool.submit(_update)
        delete_future = pool.submit(_delete)
        start.wait(timeout=2)
        update_future.result(timeout=2)
        delete_future.result(timeout=2)

    reloaded = ThreadStore(tmp_path)
    assert reloaded.list_threads() == {"threads": [], "total": 0}
    labels = json.loads((tmp_path / "labels.json").read_text("utf-8"))
    assert thread_id not in labels


def test_process_transactions_reload_stale_store_snapshots(tmp_path):
    seed = ThreadStore(tmp_path)
    thread_id = seed.add_message(_envelope("1"), "INBOX", "inbox")
    seed.save()

    first_process = ThreadStore(tmp_path)
    stale_second_process = ThreadStore(tmp_path)
    with first_process.process_transaction():
        first_process.update_labels(thread_id, add=["important"])
    with stale_second_process.process_transaction():
        stale_second_process.add_message(
            _envelope("2", reply=True),
            "INBOX",
            "inbox",
        )
        stale_second_process.save()

    reloaded = ThreadStore(tmp_path)
    thread = reloaded.get_thread(thread_id)
    assert thread["message_count"] == 2
    assert "important" in thread["labels"]
