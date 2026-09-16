# -*- coding: utf-8 -*-
"""ReMe 收件箱事件应携带可在文件中心定位的记忆文件。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


@pytest.mark.asyncio
async def test_reme_job_reports_changed_memory_files_and_source_conversation(
    tmp_path,
) -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.working_dir = str(tmp_path)
    manager.agent_id = "agent-a"
    manager._scope_actor_user_id = None
    manager._scope_access_checker = None
    manager.get_memory_config = lambda: SimpleNamespace(
        daily_dir="memory",
        digest_dir="digest",
        auto_memory_inbox_push_enabled=True,
    )

    async def run_job(_name, **kwargs):
        assert "_source_conversation_id" not in kwargs
        target = tmp_path / "memory" / "2026-09-16" / "qingdao.md"
        target.parent.mkdir(parents=True)
        target.write_text("# 青岛", encoding="utf-8")
        return SimpleNamespace(success=True, answer="已生成记忆", metadata={})

    manager._reme = SimpleNamespace(is_started=True, run_job=run_job)
    manager._update_qwenpaw_model = AsyncMock()

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        new_callable=AsyncMock,
        return_value={"id": "event-1", "status": "success"},
    ) as append_event:
        await manager._run_reme_job_unlocked(
            "auto_memory",
            _source_conversation_id="de307e1e-a799-4323-8fbb-4699dea2990c",
            session_id="session-1",
        )

    payload = append_event.await_args.kwargs["payload"]
    assert payload["source_conversation_id"] == (
        "de307e1e-a799-4323-8fbb-4699dea2990c"
    )
    assert payload["memory_files"] == [
        {
            "scope": "public",
            "section": "daily",
            "path": "2026-09-16/qingdao.md",
        },
    ]


def test_inbox_memory_file_filter_rejects_unmanaged_paths() -> None:
    assert ReMeLightMemoryManager._sanitize_memory_file_locators(
        [
            {"scope": "private", "section": "daily", "path": "ok/note.md"},
            {"scope": "private", "section": "daily", "path": "../secret.md"},
            {"scope": "private", "section": "daily", "path": "C:\\secret.md"},
            {"scope": "other", "section": "daily", "path": "note.md"},
        ],
    ) == [
        {"scope": "private", "section": "daily", "path": "ok/note.md"},
    ]
