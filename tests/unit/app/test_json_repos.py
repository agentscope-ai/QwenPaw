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

from copaw.app.crons.models import (  # noqa: E402
    CronJobRequest,
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    JobsFile,
    ScheduleSpec,
)
from copaw.app.crons.repo.json_repo import JsonJobRepository  # noqa: E402
from copaw.app.runner.models import ChatsFile  # noqa: E402
from copaw.app.runner.repo.json_repo import JsonChatRepository  # noqa: E402


@pytest.mark.asyncio
async def test_chat_repo_recovers_empty_file(tmp_path: Path) -> None:
    repo = JsonChatRepository(tmp_path / "chats.json")
    repo.path.write_text("", encoding="utf-8")

    loaded = await repo.load()

    assert loaded == ChatsFile(version=1, chats=[])
    assert json.loads(repo.path.read_text(encoding="utf-8")) == {
        "version": 1,
        "chats": [],
    }
    backups = list(tmp_path.glob("chats.corrupt.*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_chat_repo_recovers_schema_invalid_file(tmp_path: Path) -> None:
    repo = JsonChatRepository(tmp_path / "chats.json")
    repo.path.write_text(
        json.dumps({"version": 1, "chats": {}}),
        encoding="utf-8",
    )

    loaded = await repo.load()

    assert loaded == ChatsFile(version=1, chats=[])
    assert json.loads(repo.path.read_text(encoding="utf-8")) == {
        "version": 1,
        "chats": [],
    }
    assert len(list(tmp_path.glob("chats.corrupt.*.json"))) == 1


@pytest.mark.asyncio
async def test_job_repo_recovers_malformed_json(tmp_path: Path) -> None:
    repo = JsonJobRepository(tmp_path / "jobs.json")
    repo.path.write_text("{", encoding="utf-8")

    loaded = await repo.load()

    assert loaded == JobsFile(version=1, jobs=[])
    assert json.loads(repo.path.read_text(encoding="utf-8")) == {
        "version": 1,
        "jobs": [],
    }
    assert len(list(tmp_path.glob("jobs.corrupt.*.json"))) == 1


def _chat_repo_writer_process(path_str: str, worker_idx: int) -> None:
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    from copaw.app.runner.models import ChatSpec, ChatsFile
    from copaw.app.runner.repo.json_repo import JsonChatRepository

    repo = JsonChatRepository(path_str)
    rng = random.Random(worker_idx)
    for iteration in range(24):
        chats = [
            ChatSpec(
                session_id=f"session-{worker_idx}-{iteration}-{i}",
                user_id=f"user-{worker_idx}",
                name=f"chat-{worker_idx}",
                meta={"blob": "z" * 1024, "i": i},
            )
            for i in range(40)
        ]
        asyncio.run(repo.save(ChatsFile(version=1, chats=chats)))
        if rng.random() < 0.3:
            import time

            time.sleep(rng.random() / 100)


def test_chat_repo_cross_process_writes_are_safe(tmp_path: Path) -> None:
    repo_path = tmp_path / "chats.json"
    ctx = multiprocessing.get_context("spawn")
    processes = [
        ctx.Process(
            target=_chat_repo_writer_process,
            args=(str(repo_path), idx),
        )
        for idx in range(4)
    ]

    for process in processes:
        process.start()

    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    saved = json.loads(repo_path.read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert isinstance(saved["chats"], list)
    assert len(saved["chats"]) == 40


@pytest.mark.asyncio
async def test_job_repo_round_trip(tmp_path: Path) -> None:
    repo = JsonJobRepository(tmp_path / "jobs.json")
    jobs_file = JobsFile(
        version=1,
        jobs=[
            CronJobSpec(
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
            ),
        ],
    )

    await repo.save(jobs_file)

    loaded = await repo.load()

    assert loaded == jobs_file
