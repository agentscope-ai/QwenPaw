# -*- coding: utf-8 -*-
"""Concurrent write-lock stress tests for shared knowledge bases."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from qwenpaw.agents.knowledge.dream import KnowledgeUnit, integrate_units
from qwenpaw.agents.knowledge.lock import (
    KnowledgeLockTimeout,
    knowledge_write_lock,
)
from qwenpaw.agents.knowledge.store import ensure_kb


def _patch_kb_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    root = lambda kb_id: tmp_path / "knowledge_bases" / kb_id
    monkeypatch.setattr("qwenpaw.agents.knowledge.lock.kb_root", root)
    monkeypatch.setattr("qwenpaw.agents.knowledge.dream.kb_root", root)


def test_second_writer_times_out_while_lock_held(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_lock_stress")

    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def holder():
        try:
            with knowledge_write_lock("kb_lock_stress", timeout_s=5.0):
                entered.set()
                assert release.wait(timeout=5.0)
        except BaseException as exc:  # noqa: BLE001 — collect for assert
            errors.append(exc)

    def waiter():
        try:
            assert entered.wait(timeout=5.0)
            with knowledge_write_lock(
                "kb_lock_stress",
                timeout_s=0.3,
                poll_s=0.05,
            ):
                errors.append(RuntimeError("waiter should not acquire lock"))
        except KnowledgeLockTimeout:
            pass
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=waiter)
    t1.start()
    t2.start()
    t2.join(timeout=5.0)
    release.set()
    t1.join(timeout=5.0)
    assert not t1.is_alive() and not t2.is_alive()
    assert errors == []


def test_concurrent_integrate_units_all_succeed(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_concurrent")

    def write_one(idx: int) -> list:
        return integrate_units(
            kb_id="kb_concurrent",
            agent_id=f"agent_{idx}",
            units=[
                KnowledgeUnit(
                    name=f"口径-{idx}",
                    bucket="wiki",
                    summary=f"content {idx}",
                    confidence=0.9,
                ),
            ],
            derived_from=[f"tool:t{idx}"],
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(write_one, i) for i in range(6)]
        results = [f.result(timeout=30) for f in as_completed(futures)]

    assert all(len(r) == 1 for r in results)
    wiki = tmp_path / "knowledge_bases" / "kb_concurrent" / "business" / "wiki"
    files = list(wiki.glob("*.md"))
    assert len(files) == 6
    bodies = {p.read_text(encoding="utf-8") for p in files}
    assert all("content " in b for b in bodies)
    # No truncated / empty files.
    assert all(len(b) > 40 for b in bodies)


def test_concurrent_same_title_only_one_wins(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_dedup")

    def write_dup(idx: int) -> int:
        written = integrate_units(
            kb_id="kb_dedup",
            agent_id=f"agent_{idx}",
            units=[
                KnowledgeUnit(
                    name="统一口径",
                    bucket="procedure",
                    summary=f"from {idx}",
                ),
            ],
            derived_from=[f"t{idx}"],
        )
        return len(written)

    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(
            pool.map(write_dup, range(4)),
        )

    assert sum(counts) == 1
    procedure = tmp_path / "knowledge_bases" / "kb_dedup" / "business" / "procedure"
    assert len(list(procedure.glob("*.md"))) == 1


def test_lock_serializes_critical_section(tmp_path, monkeypatch):
    """Only one holder may be inside the critical section at a time."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_serial")

    active = 0
    max_active = 0
    guard = threading.Lock()

    def worker(_idx: int) -> None:
        nonlocal active, max_active
        with knowledge_write_lock("kb_serial", timeout_s=10.0, poll_s=0.02):
            with guard:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with guard:
                active -= 1

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(worker, range(5)))

    assert max_active == 1
