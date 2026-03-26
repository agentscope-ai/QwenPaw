from __future__ import annotations

from copaw.app.runner.models import ChatRuntimeStatus, ChatRuntimeStatusBreakdownItem
from copaw.app.runner.runtime_status_store import (
    RuntimeStatusWriteContext,
    load_persisted_runtime_status,
    persist_runtime_status,
    reset_current_runtime_status_context,
    set_current_runtime_status_context,
)
from copaw.app.runner.session import SafeJSONSession


async def test_persist_and_load_runtime_status(tmp_path) -> None:
    session = SafeJSONSession(save_dir=str(tmp_path))
    token = set_current_runtime_status_context(
        RuntimeStatusWriteContext(
            session=session,
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            chat_id="chat-1",
        )
    )
    try:
        await persist_runtime_status(
            ChatRuntimeStatus(
                context_window_tokens=1000,
                used_tokens=400,
                used_ratio=0.4,
                reserved_response_tokens=100,
                remaining_tokens=500,
                model_id="model-a",
                provider_id="provider-a",
                profile_label="Local runtime",
                breakdown=[
                    ChatRuntimeStatusBreakdownItem(
                        key="messages",
                        label="Messages",
                        tokens=400,
                        ratio=0.4,
                        section="user",
                    )
                ],
            )
        )
    finally:
        reset_current_runtime_status_context(token)

    loaded = await load_persisted_runtime_status(
        session,
        session_id="session-1",
        user_id="user-1",
        chat_id="chat-1",
    )

    assert loaded is not None
    assert loaded.used_tokens == 400
    assert loaded.model_id == "model-a"
    assert loaded.agent_id == "agent-1"
    assert loaded.session_id == "session-1"
    assert loaded.user_id == "user-1"
    assert loaded.chat_id == "chat-1"
    assert loaded.scope_level == "chat"
    assert loaded.snapshot_source == "runtime_push"
    assert loaded.snapshot_stage == "pre_model_call"


async def test_load_runtime_status_ignores_other_chat_id(tmp_path) -> None:
    session = SafeJSONSession(save_dir=str(tmp_path))
    token = set_current_runtime_status_context(
        RuntimeStatusWriteContext(
            session=session,
            agent_id="agent-2",
            session_id="session-2",
            user_id="user-2",
            chat_id="chat-2",
        )
    )
    try:
        await persist_runtime_status(
            ChatRuntimeStatus(
                context_window_tokens=1000,
                used_tokens=300,
                used_ratio=0.3,
                reserved_response_tokens=100,
                remaining_tokens=600,
                model_id="model-b",
                provider_id="provider-b",
                profile_label="Cloud/runtime",
                breakdown=[],
            )
        )
    finally:
        reset_current_runtime_status_context(token)

    loaded = await load_persisted_runtime_status(
        session,
        session_id="session-2",
        user_id="user-2",
        chat_id="chat-other",
    )

    assert loaded is None