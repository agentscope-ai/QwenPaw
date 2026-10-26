# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Offline file consistency across QwenPaw actions and real ReMe jobs."""

import asyncio
import os
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from watchfiles import Change

from qwenpaw.agents.memory.reme_config import get_reme_app_config
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
    _load_validated_reme_app,
)
from qwenpaw.config.config import AgentProfileConfig

pytestmark = [pytest.mark.integration, pytest.mark.p1]


@pytest.fixture(name="embedded_memory")
def make_embedded_memory(tmp_path):
    """Assemble real jobs without reading user config or calling a provider."""
    profile = AgentProfileConfig(id="review", name="Review")
    memory_config = profile.running.reme_light_memory_config
    memory_config.auto_memory_inbox_push_enabled = True
    cfg = get_reme_app_config(
        working_dir=str(tmp_path),
        agent_config=profile,
    )
    cfg.update(log_to_console=False, log_to_file=False, enable_logo=False)
    cfg["components"]["as_llm"]["default"]["credential"] = {
        "api_key": "offline-test-key",
    }
    manager = object.__new__(ReMeLightMemoryManager)
    manager.agent_id = profile.id
    manager._reme = _load_validated_reme_app()(**cfg)
    manager._lifecycle_condition = asyncio.Condition()
    manager._lifecycle_operation = None
    manager._active_reme_jobs = 0
    manager._llm_job_lock = asyncio.Lock()
    manager._load_memory_config = lambda: memory_config
    return manager, cfg


@pytest.mark.asyncio
async def test_startup_reconciliation_indexes_first_event_once(
    embedded_memory,
    tmp_path,
    monkeypatch,
):
    """Merge the initial scan with the embedded watcher's first live event."""
    from reme.steps.index.update_changes import UpdateIndexStep

    manager, cfg = embedded_memory
    app = manager._reme
    note = tmp_path / cfg["daily_dir"] / "startup.md"
    builds = []
    build_item = UpdateIndexStep.build_item

    async def record_build(step, path):
        builds.append(str(path))
        return await build_item(step, path)

    async def first_batch(*_paths, **_kwargs):
        note.write_text("# Startup\nOne memory.", encoding="utf-8")
        yield {(Change.added, str(note))}

    monkeypatch.setattr(UpdateIndexStep, "build_item", record_build)
    monkeypatch.setattr(
        "reme.steps.index.watch_changes.watch_in_thread",
        first_batch,
    )
    try:
        await app.start()
        await asyncio.wait_for(
            app.context.jobs["index_update_loop"]._task,
            timeout=5,
        )
        assert builds == [str(note)]
        nodes = await app.context.components["file_store"][
            "default"
        ].get_nodes()
        assert [node.path for node in nodes] == [
            f"{cfg['daily_dir']}/startup.md",
        ]
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_cancelled_host_write_keeps_lease_and_serializes_next_write(
    embedded_memory,
    tmp_path,
    monkeypatch,
):
    """Cancellation retains the writer's path lock and host lifecycle lease."""
    manager, cfg = embedded_memory
    app = manager._reme
    target = tmp_path / cfg["daily_dir"] / "note.md"
    entered, release = threading.Event(), threading.Event()
    replace = os.replace

    def delayed_replace(source, destination):
        if Path(destination) == target and not entered.is_set():
            entered.set()
            assert release.wait(5)
        replace(source, destination)

    async def write(content, path=None):
        return await manager.run_action(
            "write",
            path=path or f"{cfg['daily_dir']}/note.md",
            name="Note",
            description="test",
            content=content,
        )

    tasks = []
    try:
        await app.start()
        monkeypatch.setattr(os, "replace", delayed_replace)
        first = asyncio.create_task(write("cancelled write"))
        tasks.append(first)
        assert await asyncio.to_thread(entered.wait, 5)
        for _ in range(3):
            first.cancel()
            await asyncio.sleep(0)
        assert not first.done()
        assert manager._active_reme_jobs == 1
        second = asyncio.create_task(write("successful write"))
        tasks.append(second)
        await asyncio.sleep(0)
        assert not second.done()
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        assert results[1].success
        assert manager._active_reme_jobs == 0
        assert "successful write" in target.read_text(encoding="utf-8")

        long_path = f"{cfg['daily_dir']}/" + "a" * 241 + ".md"
        assert (await write("long filename", long_path)).success
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await app.close()


@pytest.mark.asyncio
async def test_missing_tag_write_preserves_memory_and_warns_host(
    embedded_memory,
    tmp_path,
    monkeypatch,
):
    """Actual Auto-Tag validation produces a visible partial-success result."""
    from reme.steps.evolve.auto_memory import AutoMemoryStep

    manager, cfg = embedded_memory
    app = manager._reme
    note_path = f"{cfg['daily_dir']}/untagged.md"

    async def write_memory(step):
        response = await app.run_job(
            "write",
            path=note_path,
            name="Untagged",
            description="test",
            content="Durable memory",
        )
        assert response.success
        step.context["changes"] = [{"change": "added", "path": note_path}]
        step.context.response.answer = "Memory saved successfully"
        step.context.response.metadata["modified"] = True
        return step.context.response

    append_event = AsyncMock(return_value={"id": "tag-warning"})
    monkeypatch.setattr(AutoMemoryStep, "execute", write_memory)
    monkeypatch.setattr(
        manager,
        "_prepare_auto_memory_job",
        AsyncMock(return_value="auto_memory_with_tags"),
    )
    monkeypatch.setattr(
        app.context.components["agent_wrapper"]["default"],
        "reply",
        AsyncMock(return_value={"result": "", "last_message": {}}),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        append_event,
    )
    try:
        await app.start()
        response = await manager.run_action("auto_memory", messages=[])
        event = append_event.await_args.kwargs
        assert response.success
        assert response.metadata["auto_tag"]["failed"] == 1
        assert "Memory saved successfully" in response.answer
        assert "auto-tagging failed for 1 file(s)" in response.answer
        assert event["status"] == "success"
        assert event["severity"] == "warning"
        assert event["payload"]["auto_tag"]["failed"] == 1
        assert "Durable memory" in (tmp_path / note_path).read_text(
            encoding="utf-8",
        )
    finally:
        await app.close()
