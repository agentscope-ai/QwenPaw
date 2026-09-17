# -*- coding: utf-8 -*-
"""Legacy 会话逐轮用量迁移必须保留可靠归属并可幂等重放。"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from qwenpaw.token_usage.legacy_backfill import collect_usage_candidates


def test_collect_usage_candidates_uses_chat_and_turn_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "default"
    sessions = workspace / "sessions" / "console"
    sessions.mkdir(parents=True)
    conversation_id = uuid4()
    user_id = uuid4()
    (workspace / "chats.json").write_text(
        json.dumps(
            {
                "chats": [
                    {
                        "id": str(conversation_id),
                        "user_id": str(user_id),
                        "session_id": "session-1",
                        "channel": "console",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    state = {
        "agent": {
            "state": {
                "context": [
                    {
                        "id": "assistant-message-1",
                        "role": "assistant",
                        "created_at": "2026-09-05T08:30:00+00:00",
                        "metadata": {
                            "qwenpaw_turn_usage": {
                                "usage": {
                                    "provider_id": "cpa",
                                    "model_name": "gpt-5.6-sol",
                                    "prompt_tokens": 120,
                                    "completion_tokens": 30,
                                }
                            }
                        },
                    }
                ]
            }
        }
    }
    (sessions / f"{user_id}_session-1.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    first = collect_usage_candidates(tmp_path)
    second = collect_usage_candidates(tmp_path)

    assert len(first) == 1
    assert first == second
    assert first[0].conversation_id == conversation_id
    assert first[0].provider_key == "cpa"
    assert first[0].model_key == "gpt-5.6-sol"
    assert first[0].prompt_tokens == 120
    assert first[0].completion_tokens == 30
    assert isinstance(first[0].record_id, UUID)


def test_collect_usage_candidates_skips_unattributed_or_estimated_turns(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspaces" / "default"
    sessions = workspace / "sessions" / "console"
    sessions.mkdir(parents=True)
    conversation_id = uuid4()
    (workspace / "chats.json").write_text(
        json.dumps(
            {
                "chats": [
                    {
                        "id": str(conversation_id),
                        "user_id": "user-1",
                        "session_id": "session-1",
                        "channel": "console",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    state = {
        "agent": {
            "state": {
                "context": [
                    {
                        "id": "estimated",
                        "role": "assistant",
                        "created_at": "2026-09-05T08:30:00+00:00",
                        "metadata": {
                            "qwenpaw_turn_usage": {
                                "usage": {
                                    "estimated": True,
                                    "provider_id": "",
                                    "model_name": "",
                                    "prompt_tokens": 12,
                                    "completion_tokens": 3,
                                }
                            }
                        },
                    }
                ]
            }
        }
    }
    (sessions / "user-1_session-1.json").write_text(json.dumps(state), encoding="utf-8")

    assert collect_usage_candidates(tmp_path) == []
