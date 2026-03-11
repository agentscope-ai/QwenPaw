# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import multiprocessing
import random
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from copaw.app.runner.session import SafeJSONSession  # noqa: E402


class FakeStateModule:
    def __init__(self, state: dict | None = None):
        self._state = state or {}

    def state_dict(self) -> dict:
        return self._state

    def load_state_dict(self, state: dict) -> None:
        self._state = state


@pytest.mark.asyncio
async def test_update_session_state_recovers_empty_file(tmp_path: Path) -> None:
    session = SafeJSONSession(save_dir=str(tmp_path))
    session_path = Path(
        session._get_save_path("console:alice", user_id="alice"),
    )
    session_path.write_text("", encoding="utf-8")

    await session.update_session_state(
        session_id="console:alice",
        user_id="alice",
        key="agent.memory",
        value=["msg"],
    )

    saved = json.loads(session_path.read_text(encoding="utf-8"))
    assert saved == {"agent": {"memory": ["msg"]}}
    assert len(list(tmp_path.glob("alice_console--alice.corrupt.*.json"))) == 1


@pytest.mark.asyncio
async def test_get_session_state_dict_recovers_non_object_payload(
    tmp_path: Path,
) -> None:
    session = SafeJSONSession(save_dir=str(tmp_path))
    session_path = Path(
        session._get_save_path("console:alice", user_id="alice"),
    )
    session_path.write_text(json.dumps(["bad"]), encoding="utf-8")

    loaded = await session.get_session_state_dict(
        session_id="console:alice",
        user_id="alice",
    )

    assert loaded == {}
    assert json.loads(session_path.read_text(encoding="utf-8")) == {}
    assert len(list(tmp_path.glob("alice_console--alice.corrupt.*.json"))) == 1


@pytest.mark.asyncio
async def test_save_and_load_session_state_round_trip(tmp_path: Path) -> None:
    session = SafeJSONSession(save_dir=str(tmp_path))
    agent = FakeStateModule({"messages": ["hello"]})
    memory = FakeStateModule({"items": [1, 2, 3]})

    await session.save_session_state(
        session_id="console:alice",
        user_id="alice",
        agent=agent,
        memory=memory,
    )

    restored_agent = FakeStateModule()
    restored_memory = FakeStateModule()
    await session.load_session_state(
        session_id="console:alice",
        user_id="alice",
        agent=restored_agent,
        memory=restored_memory,
    )

    assert restored_agent.state_dict() == {"messages": ["hello"]}
    assert restored_memory.state_dict() == {"items": [1, 2, 3]}


def _session_writer_process(save_dir: str, worker_idx: int) -> None:
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    from copaw.app.runner.session import SafeJSONSession

    session = SafeJSONSession(save_dir=save_dir)
    rng = random.Random(worker_idx)
    for iteration in range(16):
        asyncio.run(
            session.update_session_state(
                session_id="console:alice",
                user_id="alice",
                key=("workers", f"worker-{worker_idx}"),
                value={"iteration": iteration},
            ),
        )
        if rng.random() < 0.3:
            import time

            time.sleep(rng.random() / 100)


@pytest.mark.asyncio
async def test_update_session_state_cross_process_is_safe(
    tmp_path: Path,
) -> None:
    ctx = multiprocessing.get_context("spawn")
    processes = [
        ctx.Process(
            target=_session_writer_process,
            args=(str(tmp_path), idx),
        )
        for idx in range(4)
    ]

    for process in processes:
        process.start()

    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    session = SafeJSONSession(save_dir=str(tmp_path))
    loaded = await session.get_session_state_dict(
        session_id="console:alice",
        user_id="alice",
    )

    assert sorted(loaded["workers"].keys()) == [
        "worker-0",
        "worker-1",
        "worker-2",
        "worker-3",
    ]
