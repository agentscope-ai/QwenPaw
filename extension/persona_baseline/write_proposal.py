# -*- coding: utf-8 -*-
"""Persistent store for agent persona write proposals awaiting approval."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .paths import persona_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WriteProposal:
    proposal_id: str
    agent_id: str
    relative_path: str
    absolute_path: str
    operation: str
    tool_name: str
    old_sha256: str
    new_sha256: str
    encoding: str
    content: str
    created_at: str
    session_id: str = ""
    user_id: str = ""
    channel: str = ""

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "agent_id": self.agent_id,
            "relative_path": self.relative_path,
            "absolute_path": self.absolute_path,
            "operation": self.operation,
            "tool_name": self.tool_name,
            "old_sha256": self.old_sha256,
            "new_sha256": self.new_sha256,
            "encoding": self.encoding,
            "content": self.content,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "channel": self.channel,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WriteProposal":
        return cls(
            proposal_id=str(data["proposal_id"]),
            agent_id=str(data["agent_id"]),
            relative_path=str(data["relative_path"]),
            absolute_path=str(data["absolute_path"]),
            operation=str(data["operation"]),
            tool_name=str(data["tool_name"]),
            old_sha256=str(data["old_sha256"]),
            new_sha256=str(data["new_sha256"]),
            encoding=str(data.get("encoding") or "utf-8"),
            content=str(data["content"]),
            created_at=str(data.get("created_at") or _utc_now()),
            session_id=str(data.get("session_id") or ""),
            user_id=str(data.get("user_id") or ""),
            channel=str(data.get("channel") or ""),
        )


class WriteProposalStore:
    def __init__(self, working_dir: Path) -> None:
        self._root = persona_root(working_dir) / "write_proposals"
        self._root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        agent_id: str,
        relative_path: str,
        absolute_path: str,
        operation: str,
        tool_name: str,
        old_sha256: str,
        new_sha256: str,
        encoding: str,
        content: str,
        session_id: str = "",
        user_id: str = "",
        channel: str = "",
        proposal_id: str | None = None,
    ) -> WriteProposal:
        proposal = WriteProposal(
            proposal_id=proposal_id or str(uuid.uuid4()),
            agent_id=agent_id,
            relative_path=relative_path,
            absolute_path=absolute_path,
            operation=operation,
            tool_name=tool_name,
            old_sha256=old_sha256,
            new_sha256=new_sha256,
            encoding=encoding,
            content=content,
            created_at=_utc_now(),
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        self.save(proposal)
        return proposal

    def save(self, proposal: WriteProposal) -> None:
        path = self._root / f"{proposal.proposal_id}.json"
        path.write_text(
            json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load(self, proposal_id: str) -> WriteProposal | None:
        path = self._root / f"{proposal_id}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return WriteProposal.from_dict(data)

    def delete(self, proposal_id: str) -> None:
        path = self._root / f"{proposal_id}.json"
        if path.is_file():
            path.unlink()
