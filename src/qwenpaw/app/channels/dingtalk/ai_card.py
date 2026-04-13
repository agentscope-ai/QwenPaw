# -*- coding: utf-8 -*-
"""DingTalk AI Card helpers."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

PROCESSING = "1"
INPUTING = "2"
FINISHED = "3"
FAILED = "5"
_TERMINAL_STATES = {FINISHED, FAILED}


@dataclass
class ActiveAICard:
    card_instance_id: str
    access_token: str
    conversation_id: str
    account_id: str
    store_path: str
    created_at: int
    last_updated: int
    state: str
    last_streamed_content: str = ""


class AICardPendingStore:
    """Persist active inbound cards for crash recovery."""

    def __init__(self, path: Path):
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> List[dict]:
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            pending = (
                data.get("pending_cards") if isinstance(data, dict) else []
            )
            return pending if isinstance(pending, list) else []
        except Exception:
            return []

    def save(self, cards: Dict[str, ActiveAICard]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        pending_cards = [
            {
                "account_id": v.account_id,
                "card_instance_id": v.card_instance_id,
                "conversation_id": v.conversation_id,
                "created_at": v.created_at,
                "last_updated": v.last_updated,
                "state": v.state,
            }
            for v in cards.values()
            if v.state not in _TERMINAL_STATES
        ]
        data = {
            "version": 1,
            "updated_at": int(time.time() * 1000),
            "pending_cards": pending_cards,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)


def is_group_conversation(conversation_id: str) -> bool:
    return (conversation_id or "").startswith("cid")


def thinking_or_tool_to_card_text(text: str, title: str) -> str:
    body = (text or "")[:500]
    if len(text or "") > 500:
        body += "…"
    lines = body.splitlines() or [""]
    fixed = []
    for ln in lines:
        ln = re.sub(r"^_$", "*", ln)
        ln = re.sub(r"_$", "*", ln)
        fixed.append(f"> {ln}")
    return f"{title}\n" + "\n".join(fixed)


def to_pending_record(card: ActiveAICard) -> dict:
    data = asdict(card)
    data.pop("access_token", None)
    data.pop("store_path", None)
    data.pop("last_streamed_content", None)
    return data
