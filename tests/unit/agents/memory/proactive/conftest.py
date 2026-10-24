# -*- coding: utf-8 -*-
"""Shared doubles for the proactive agenda delivery tests."""
# pylint: disable=protected-access

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


def agenda_entry(
    topic_id: str,
    *,
    title: str = "",
    kind: str = "follow_up",
    opener: str = "",
    next_action: str = "",
    due_at: str = "",
) -> dict[str, Any]:
    """One agenda entry shaped exactly like ReMe's ``interests.yaml``."""
    entry: dict[str, Any] = {
        "topic_id": topic_id,
        "title": title or f"title-{topic_id}",
        "kind": kind,
        "scenario_type": "resume_task",
        "opener": opener or f"opener-{topic_id}",
        "next_action": next_action or f"next-{topic_id}",
        "preconditions": [],
        "delivery": "in_conversation",
        "linked_memory": [f"memory/{topic_id}.md"],
        "order_reason": "ranked by the agenda editor",
    }
    if due_at:
        entry["due_at"] = due_at
    return entry


class FakeMemoryManager:
    """Stands in for ``ReMeLightMemoryManager``'s action surface."""

    def __init__(
        self,
        agenda: list[dict[str, Any]] | None = None,
        *,
        topics: list[dict[str, Any]] | None = None,
        date: str = "2026-10-11",
        refresh_success: bool = True,
        refresh_swaps_agenda: list[dict[str, Any]] | None = None,
        delivered_ids: list[str] | None = None,
        read_success: bool = True,
        feedback_success: bool = True,
    ):
        self.agenda = list(agenda or [])
        self.topics = list(topics or [])
        self.date = date
        self.refresh_success = refresh_success
        self.refresh_swaps_agenda = refresh_swaps_agenda
        self.delivered_ids = list(delivered_ids or [])
        self.read_success = read_success
        self.feedback_success = feedback_success
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.feedback: list[list[dict[str, Any]]] = []

    async def list_actions(self) -> dict[str, Any]:
        return {}

    async def run_action(self, action: str, **kwargs: Any):
        self.calls.append((action, kwargs))
        if action == "proactive":
            return self._read(kwargs)
        if action == "proactive_refresh":
            if self.refresh_swaps_agenda is not None:
                self.agenda = list(self.refresh_swaps_agenda)
            return SimpleNamespace(
                success=self.refresh_success,
                answer="refreshed" if self.refresh_success else "boom",
                metadata={},
            )
        if action == "proactive_feedback":
            self.feedback.append(list(kwargs.get("items") or []))
            return SimpleNamespace(
                success=self.feedback_success,
                answer="recorded" if self.feedback_success else "rejected",
                metadata={},
            )
        raise ValueError(f"unexpected action: {action}")

    def _read(self, kwargs: dict[str, Any]) -> SimpleNamespace:
        if not self.read_success:
            return SimpleNamespace(
                success=False,
                answer="read failed",
                metadata={},
            )
        payload = {
            "date": kwargs.get("date") or self.date,
            "topics": self.topics,
            "agenda": self.agenda,
            "delivered_ids": self.delivered_ids,
            "summary": f"{len(self.agenda)} agenda item(s)",
        }
        return SimpleNamespace(
            success=True,
            answer={"summary": payload["summary"]},
            metadata=payload,
        )

    def actions(self) -> list[str]:
        return [name for name, _ in self.calls]


@pytest.fixture
def fake_manager() -> FakeMemoryManager:
    return FakeMemoryManager()


@pytest.fixture(autouse=True)
def _clear_ledger_cache():
    """The delivery ledger cache is process-wide; never leak it."""
    from qwenpaw.agents.memory.proactive import proactive_delivery

    proactive_delivery._ledgers.clear()
    yield
    proactive_delivery._ledgers.clear()
