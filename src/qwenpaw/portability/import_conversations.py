# -*- coding: utf-8 -*-
"""Conversation phase of a provider import transaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..app.chats.models import ChatSpec
from ..harnesses.session import HarnessSessionBridge
from .import_support import (
    _chat_id,
    _progress_milestone,
    _project_directory,
    _session_key,
)
from .models import ProviderInventory, SourceSession
from .providers.base import (
    ProgressReporter,
    report_progress as _report,
    report_result,
)


@dataclass
class ConversationState:
    """Per-session progress counters."""

    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# pylint: disable-next=too-many-branches,too-many-statements
async def import_conversations(
    workspace: Any,
    inventory: ProviderInventory,
    sessions: list[SourceSession],
    existing_by_source: dict[tuple[str, str], Any],
    started_at: datetime,
    progress: ProgressReporter | None,
    state: ConversationState,
) -> None:
    """Import readable root chats and archive old imported internals."""
    bridge = HarnessSessionBridge(workspace.session)
    if inventory.ignored_session_ids:
        await _report(progress, "正在整理此前误导入的内部执行轨迹…")
    for source_id in inventory.ignored_session_ids:
        chat = existing_by_source.get((inventory.provider_id, source_id))
        if chat is None or chat.archived:
            continue
        await workspace.chat_manager.archive_chat(chat.id)

    total = len(sessions)

    async def report_session(index: int) -> None:
        await report_result(
            progress,
            "sessions",
            index,
            total,
            len(state.imported),
            len(state.skipped),
        )

    for index, session in enumerate(sessions, start=1):
        if _progress_milestone(index, total):
            await _report(
                progress,
                f"正在写入会话：{index}/{total}（聊天记录阶段）",
            )
        source_key = (inventory.provider_id, session.source_id)
        existing = existing_by_source.get(source_key)
        project_dir = _project_directory(session)
        if existing is not None:
            if project_dir:
                runtime = existing.meta.get("runtime_context") or {}
                current = str(runtime.get("project_dir") or "")
                if current != project_dir:
                    await workspace.chat_manager.set_project_dir(
                        existing.id,
                        project_dir,
                    )
            state.skipped.append(session.source_id)
            await report_session(index)
            continue
        if not session.history:
            state.skipped.append(session.source_id)
            await report_session(index)
            continue

        session_id = _session_key(inventory.provider_id, session.source_id)
        user_id, channel = session_id, "console"
        try:
            await bridge.hydrate(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                backend=inventory.provider_id,
                history=session.history,
            )
        except Exception:  # pylint: disable=broad-except
            state.skipped.append(session.source_id)
            await report_session(index)
            continue
        portability = {
            "schema_version": "1",
            "source": inventory.provider_id,
            "source_id": session.source_id,
            "source_locator": inventory.locator,
            "source_cwd": session.cwd,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "import_mode": "historical_archive",
            "read_only_enforced": False,
            "continuation_fidelity": "not_guaranteed",
            "historical_tools_are_data": True,
            "fidelity": "normalized_lossy",
        }
        meta: dict[str, Any] = {"portability": portability}
        if project_dir:
            meta["runtime_context"] = {"project_dir": project_dir}
        spec = ChatSpec(
            id=_chat_id(inventory.provider_id, session.source_id),
            name=session.title,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            created_at=session.created_at or started_at,
            updated_at=session.updated_at or session.created_at or started_at,
            meta=meta,
        )
        try:
            await workspace.chat_manager.create_chat(spec)
        except Exception:  # pylint: disable=broad-except
            try:
                await bridge.clear(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                )
            except Exception:  # pylint: disable=broad-except
                pass
            state.skipped.append(session.source_id)
            await report_session(index)
            continue
        existing_by_source[source_key] = spec
        state.imported.append(session.source_id)
        await report_session(index)

    await _report(
        progress,
        "聊天记录阶段完成；开始迁移并检查工具和设置…",
    )
