# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import multiprocessing
import random
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from copaw.app.crons.models import (  # noqa: E402
    CronJobRequest,
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    JobsFile,
    ScheduleSpec,
)
from copaw.app.crons.repo.json_repo import JsonJobRepository  # noqa: E402
from copaw.app.crons.repo.sqlite_repo import SQLiteJobRepository  # noqa: E402
from copaw.app.runner.models import ChatSpec, ChatsFile  # noqa: E402
from copaw.app.runner.repo.json_repo import JsonChatRepository  # noqa: E402
from copaw.app.runner.repo.sqlite_repo import SQLiteChatRepository  # noqa: E402
from copaw.app.runner.session import (  # noqa: E402
    SafeJSONSession,
    SQLiteSession,
)
from copaw.app.state_db import initialize_state_db  # noqa: E402


def _job_spec() -> CronJobSpec:
    return CronJobSpec(
        id="job-1",
        name="heartbeat",
        schedule=ScheduleSpec(cron="0 9 * * *", timezone="UTC"),
        task_type="agent",
        request=CronJobRequest(input="ping"),
        dispatch=DispatchSpec(
            channel="console",
            target=DispatchTarget(
                user_id="alice",
                session_id="console:alice",
            ),
        ),
    )


class FakeStateModule:
    def __init__(self, state: dict | None = None):
        self._state = state or {}

    def state_dict(self) -> dict:
        return self._state

    def load_state_dict(self, state: dict) -> None:
        self._state = state


@pytest.mark.asyncio
async def test_initialize_state_db_migrates_legacy_files(
    tmp_path: Path,
) -> None:
    chats_path = tmp_path / "chats.json"
    jobs_path = tmp_path / "jobs.json"
    sessions_dir = tmp_path / "sessions"
    db_path = tmp_path / "state.sqlite3"

    legacy_chat = ChatSpec(
        id="chat-1",
        session_id="console:alice",
        user_id="alice",
        channel="console",
        name="Migrated Chat",
    )
    await JsonChatRepository(chats_path).save(
        ChatsFile(version=1, chats=[legacy_chat]),
    )
    await JsonJobRepository(jobs_path).save(
        JobsFile(version=1, jobs=[_job_spec()]),
    )

    legacy_session = SafeJSONSession(save_dir=str(sessions_dir))
    await legacy_session.save_session_state(
        session_id="console:alice",
        user_id="alice",
        agent=FakeStateModule({"memory": ["hello"]}),
    )

    await initialize_state_db(
        db_path,
        chats_path=chats_path,
        jobs_path=jobs_path,
        sessions_dir=sessions_dir,
    )

    chat_repo = SQLiteChatRepository(db_path)
    job_repo = SQLiteJobRepository(db_path)
    sqlite_session = SQLiteSession(
        save_dir=str(sessions_dir),
        db_path=str(db_path),
    )

    loaded_chats = await chat_repo.load()
    loaded_jobs = await job_repo.load()
    loaded_state = await sqlite_session.get_session_state_dict(
        session_id="console:alice",
        user_id="alice",
    )

    assert loaded_chats.chats == [legacy_chat]
    assert loaded_jobs.jobs == [_job_spec()]
    assert loaded_state == {"agent": {"memory": ["hello"]}}


@pytest.mark.asyncio
async def test_initialize_state_db_is_idempotent_after_first_migration(
    tmp_path: Path,
) -> None:
    chats_path = tmp_path / "chats.json"
    jobs_path = tmp_path / "jobs.json"
    sessions_dir = tmp_path / "sessions"
    db_path = tmp_path / "state.sqlite3"

    first_chat = ChatSpec(
        id="chat-1",
        session_id="console:alice",
        user_id="alice",
        channel="console",
        name="First Chat",
    )
    await JsonChatRepository(chats_path).save(
        ChatsFile(version=1, chats=[first_chat]),
    )

    await initialize_state_db(
        db_path,
        chats_path=chats_path,
        jobs_path=jobs_path,
        sessions_dir=sessions_dir,
    )

    second_chat = ChatSpec(
        id="chat-2",
        session_id="console:bob",
        user_id="bob",
        channel="console",
        name="Second Chat",
    )
    await JsonChatRepository(chats_path).save(
        ChatsFile(version=1, chats=[second_chat]),
    )

    await initialize_state_db(
        db_path,
        chats_path=chats_path,
        jobs_path=jobs_path,
        sessions_dir=sessions_dir,
    )

    loaded = await SQLiteChatRepository(db_path).load()
    assert [chat.id for chat in loaded.chats] == ["chat-1"]


@pytest.mark.asyncio
async def test_sqlite_chat_repo_reuses_existing_session_mapping(
    tmp_path: Path,
) -> None:
    repo = SQLiteChatRepository(tmp_path / "state.sqlite3")
    first = ChatSpec(
        id="chat-1",
        session_id="console:alice",
        user_id="alice",
        channel="console",
        name="First Chat",
    )
    second = ChatSpec(
        id="chat-2",
        session_id="console:alice",
        user_id="alice",
        channel="console",
        name="Renamed Chat",
    )

    await repo.upsert_chat(first)
    await repo.upsert_chat(second)

    loaded = await repo.load()
    assert second.id == "chat-1"
    assert len(loaded.chats) == 1
    assert loaded.chats[0].name == "Renamed Chat"


def _sqlite_session_writer(save_dir: str, db_path: str, worker_idx: int) -> None:
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    from copaw.app.runner.session import SQLiteSession

    session = SQLiteSession(save_dir=save_dir, db_path=db_path)
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
async def test_sqlite_session_cross_process_update_is_safe(
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    db_path = tmp_path / "state.sqlite3"
    session = SQLiteSession(save_dir=str(sessions_dir), db_path=str(db_path))

    ctx = multiprocessing.get_context("spawn")
    processes = [
        ctx.Process(
            target=_sqlite_session_writer,
            args=(str(sessions_dir), str(db_path), idx),
        )
        for idx in range(4)
    ]

    for process in processes:
        process.start()

    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

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
