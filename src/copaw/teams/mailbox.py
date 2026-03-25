# -*- coding: utf-8 -*-
"""Mailbox for inter-agent communication.

File-based message passing between agents. Each agent has an inbox
directory; senders write messages there, receivers read and archive.
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MessageType = Literal["delegate", "consult", "notify", "broadcast"]
MessagePriority = Literal["urgent", "high", "normal", "low"]

# Priority order for sorting (lower = higher priority)
_MSG_TYPE_PRIORITY = {
    "delegate": 0,
    "consult": 1,
    "notify": 2,
    "broadcast": 3,
}

_MSG_PRIORITY_ORDER = {
    "urgent": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
}


MessageKind = Literal[
    "assign", "progress", "blocker", "submit", "review", "rework", "done", "general"
]

# Queue mode: how AutoPoll should handle delivery of this message.
# - steer: 阻断/紧急，立即注入，不折叠（优先级最高）
# - collect: 普通进度，合并折叠，按静默批次处理（默认）
# - followup: 后续再通知，作为尾注，不抢占当前轮次
QueueMode = Literal["steer", "collect", "followup"]

# Default queue mode when not specified
_DEFAULT_QUEUE_MODE: QueueMode = "collect"

# Mapping from msg_kind/priority to default queue mode
_QUEUE_MODE_BY_KIND: dict[str, QueueMode] = {
    "blocker": "steer",
    "urgent": "steer",
    "assign": "steer",
    "rework": "steer",
    "review": "followup",
    "submit": "followup",
    "progress": "collect",
    "done": "collect",
    "general": "collect",
}

def _resolve_queue_mode(msg_kind: str, priority: str, explicit: str | None) -> QueueMode:
    """Resolve effective queue mode from kind, priority, and explicit setting."""
    if explicit:
        return explicit
    if priority == "urgent":
        return "steer"
    return _QUEUE_MODE_BY_KIND.get(msg_kind, _DEFAULT_QUEUE_MODE)


class AgentMessage(BaseModel):
    """A message between agents."""

    id: str = Field(default_factory=lambda: str(uuid4())[:12])
    from_agent: str
    to_agent: str
    msg_type: MessageType = "notify"
    priority: MessagePriority = "normal"
    content: str
    reply_to: Optional[str] = None
    # thread/task context for continuous collaboration
    thread_id: str = Field(default_factory=lambda: str(uuid4())[:12])
    task_id: str = ""
    msg_kind: MessageKind = "general"
    need_reply: bool = False
    created_at: float = Field(default_factory=time.time)
    read_at: Optional[float] = None
    # Queue mode: steer(立即) / collect(折叠) / followup(后续)
    queue_mode: Optional[QueueMode] = None

    @property
    def sort_key(self) -> tuple[int, int, float]:
        return (
            _MSG_PRIORITY_ORDER.get(self.priority, 2),
            _MSG_TYPE_PRIORITY.get(self.msg_type, 2),
            self.created_at,
        )


class Mailbox:
    """File-based mailbox for agent-to-agent communication."""

    def __init__(self, workspace_dir: Path):
        self._workspace_dir = workspace_dir
        self._mailbox_dir = workspace_dir / "mailbox"
        self._inbox_dir = self._mailbox_dir / "inbox"
        self._outbox_dir = self._mailbox_dir / "outbox"
        self._archive_dir = self._mailbox_dir / "archive"

        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        self._outbox_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        to_agent: str,
        content: str,
        from_agent: str,
        msg_type: MessageType = "notify",
        priority: MessagePriority = "normal",
        reply_to: Optional[str] = None,
        thread_id: str = "",
        task_id: str = "",
        msg_kind: MessageKind = "general",
        need_reply: bool = False,
        queue_mode: Optional[QueueMode] = None,
    ) -> AgentMessage:
        resolved_queue_mode = _resolve_queue_mode(msg_kind, priority, queue_mode)
        msg = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            msg_type=msg_type,
            priority=priority,
            content=content,
            reply_to=reply_to,
            thread_id=thread_id or str(uuid4())[:12],
            task_id=task_id,
            msg_kind=msg_kind,
            need_reply=need_reply,
            queue_mode=resolved_queue_mode,
        )

        target_inbox = self._resolve_inbox(to_agent)
        timestamp = datetime.fromtimestamp(msg.created_at).strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{from_agent}_{msg.id}.json"

        msg_json = json.dumps(msg.model_dump(), ensure_ascii=False, indent=2)
        (target_inbox / filename).write_text(msg_json, encoding="utf-8")
        (self._outbox_dir / filename).write_text(msg_json, encoding="utf-8")

        logger.info(
            "Message sent: %s → %s (type=%s, id=%s)",
            from_agent, to_agent, msg_type, msg.id,
        )
        return msg

    def broadcast(
        self,
        content: str,
        from_agent: str,
        priority: MessagePriority = "normal",
        exclude_agents: Optional[List[str]] = None,
        thread_id: str = "",
        task_id: str = "",
        msg_kind: MessageKind = "general",
        need_reply: bool = False,
    ) -> List[AgentMessage]:
        exclude_agents = set(exclude_agents or [])
        exclude_agents.add(from_agent)

        sent_messages = []
        for agent_dir in self._workspace_dir.parent.iterdir():
            if not agent_dir.is_dir():
                continue
            agent_id = agent_dir.name
            if agent_id.startswith(".") or agent_id in exclude_agents:
                continue
            try:
                msg = self.send(
                    to_agent=agent_id,
                    content=content,
                    from_agent=from_agent,
                    msg_type="broadcast",
                    priority=priority,
                    thread_id=thread_id,
                    task_id=task_id,
                    msg_kind=msg_kind,
                    need_reply=need_reply,
                )
                sent_messages.append(msg)
            except Exception as e:
                logger.warning("Failed to broadcast to %s: %s", agent_id, e)

        logger.info(
            "Broadcast from %s to %d agents", from_agent, len(sent_messages),
        )
        return sent_messages

    def receive(self, limit: Optional[int] = None) -> List[AgentMessage]:
        messages = []
        for msg_file in sorted(self._inbox_dir.glob("*.json")):
            try:
                data = json.loads(msg_file.read_text(encoding="utf-8"))
                msg = AgentMessage(**data)
                msg.read_at = time.time()
                messages.append(msg)
            except Exception as e:
                logger.warning("Failed to read message %s: %s", msg_file, e)
                continue

        messages.sort(key=lambda m: m.sort_key)
        if limit is not None:
            messages = messages[:limit]

        message_ids = {m.id for m in messages}
        for msg_file in sorted(self._inbox_dir.glob("*.json")):
            try:
                data = json.loads(msg_file.read_text(encoding="utf-8"))
                if data.get("id") in message_ids:
                    archive_path = self._archive_dir / msg_file.name
                    msg_file.rename(archive_path)
            except Exception:
                continue

        if messages:
            logger.info("Received %d messages", len(messages))
        return messages

    def peek(self) -> int:
        return len(list(self._inbox_dir.glob("*.json")))

    def _resolve_inbox(self, agent_id: str) -> Path:
        if agent_id == self._workspace_dir.name:
            return self._inbox_dir
        target_workspace = self._workspace_dir.parent / agent_id
        inbox = target_workspace / "mailbox" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        return inbox


# ---------------------------------------------------------------------------
# Room models & manager
# ---------------------------------------------------------------------------

RoomStatus = Literal["active", "closed"]
RoomMessageType = Literal["speak", "pass", "timeout_skip", "prompt", "round_prompt", "conclude"]


class RoomMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4())[:12])
    room_id: str
    from_agent: str
    content: str
    msg_type: RoomMessageType = "speak"
    round: int = 1
    timestamp: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


class Room(BaseModel):
    room_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    name: str
    topic: str = ""
    host: str
    members: List[str] = Field(default_factory=list)
    status: RoomStatus = "active"
    max_rounds: int = 10
    current_round: int = 1
    round_timeout_sec: int = 300
    round_deadline_ts: Optional[float] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    closed_at: Optional[str] = None
    conclusion: Optional[str] = None
    needs_conclusion: bool = False


class RoomManager:
    """File-based room manager.

    Storage layout::
        {workspaces_dir}/../rooms/
        └── {room_id}/
            ├── meta.json
            └── messages.jsonl
    """

    def __init__(self, workspaces_dir: Path):
        self._rooms_dir = workspaces_dir.parent / "rooms"
        self._rooms_dir.mkdir(parents=True, exist_ok=True)

    def create_room(
        self,
        host: str,
        name: str,
        topic: str = "",
        members: Optional[List[str]] = None,
        max_rounds: int = 10,
        round_timeout_sec: int = 300,
    ) -> Room:
        member_list = list(dict.fromkeys([host, *(members or [])]))
        room = Room(
            name=name,
            topic=topic,
            host=host,
            members=member_list,
            max_rounds=max_rounds,
            round_timeout_sec=round_timeout_sec,
            round_deadline_ts=time.time() + round_timeout_sec if round_timeout_sec > 0 else None,
        )
        room_dir = self._rooms_dir / room.room_id
        room_dir.mkdir(parents=True, exist_ok=True)
        (room_dir / "messages.jsonl").touch()
        self._save_meta(room)
        logger.info("Room created: %s (%s)", room.name, room.room_id)
        return room

    def get_room(self, room_id: str) -> Optional[Room]:
        meta_file = self._rooms_dir / room_id / "meta.json"
        if not meta_file.exists():
            return None
        try:
            return Room(**json.loads(meta_file.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("Failed to load room %s: %s", room_id, e)
            return None

    def list_rooms(
        self,
        agent_id: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[Room]:
        rooms: List[Room] = []
        if not self._rooms_dir.exists():
            return rooms
        for d in sorted(self._rooms_dir.iterdir()):
            if not d.is_dir():
                continue
            room = self.get_room(d.name)
            if not room:
                continue
            if agent_id and agent_id not in room.members:
                continue
            if status_filter and room.status != status_filter:
                continue
            rooms.append(room)
        return rooms

    def join_room(self, room_id: str, agent_id: str) -> Optional[Room]:
        room = self.get_room(room_id)
        if not room or room.status != "active":
            return None
        if agent_id not in room.members:
            room.members.append(agent_id)
            self._save_meta(room)
        return room

    def leave_room(self, room_id: str, agent_id: str) -> Optional[Room]:
        room = self.get_room(room_id)
        if not room or room.status != "active":
            return None
        if agent_id == room.host:
            return None
        if agent_id in room.members:
            room.members.remove(agent_id)
            self._save_meta(room)
        return room

    def send_message(
        self,
        room_id: str,
        from_agent: str,
        content: str,
        msg_type: RoomMessageType = "speak",
    ) -> Optional[RoomMessage]:
        room = self.get_room(room_id)
        if not room or room.status != "active" or room.needs_conclusion:
            return None
        if from_agent not in room.members:
            return None

        round_messages = self.get_history(room_id, since_round=room.current_round)
        responded_agents = {m.from_agent for m in round_messages if m.msg_type != "conclude"}
        if from_agent in responded_agents:
            logger.warning(
                "%s already responded in round %d of room %s",
                from_agent, room.current_round, room_id,
            )
            return None

        msg = RoomMessage(
            room_id=room_id,
            from_agent=from_agent,
            content=content,
            msg_type=msg_type,
            round=room.current_round,
        )
        with (self._rooms_dir / room_id / "messages.jsonl").open("a", encoding="utf-8") as f:
            f.write(msg.model_dump_json() + "\n")

        self._advance_round_if_ready(room)
        return msg

    def mark_timeout_skips(self, room_id: str) -> int:
        room = self.get_room(room_id)
        if not room or room.status != "active" or room.needs_conclusion:
            return 0
        round_messages = self.get_history(room_id, since_round=room.current_round)
        responded_agents = {m.from_agent for m in round_messages if m.msg_type != "conclude"}
        pending = [m for m in room.members if m != room.host and m not in responded_agents]
        count = 0
        if not pending:
            return 0
        for agent_id in pending:
            msg = RoomMessage(
                room_id=room_id,
                from_agent=agent_id,
                content="超时未表态，系统自动记为跳过",
                msg_type="timeout_skip",
                round=room.current_round,
            )
            with (self._rooms_dir / room_id / "messages.jsonl").open("a", encoding="utf-8") as f:
                f.write(msg.model_dump_json() + "\n")
            count += 1
        self._advance_round_if_ready(room)
        return count

    def get_round_status(self, room_id: str) -> Optional[dict]:
        room = self.get_room(room_id)
        if not room:
            return None
        round_messages = self.get_history(room_id, since_round=room.current_round)
        responded_agents = {m.from_agent for m in round_messages if m.msg_type != "conclude"}
        required_agents = [m for m in room.members if m != room.host]
        pending_agents = [m for m in required_agents if m not in responded_agents]
        return {
            "room_id": room.room_id,
            "current_round": room.current_round,
            "required_agents": required_agents,
            "responded_agents": sorted(responded_agents),
            "pending_agents": pending_agents,
            "needs_conclusion": room.needs_conclusion,
            "round_deadline_ts": room.round_deadline_ts,
            "round_timeout_sec": room.round_timeout_sec,
        }

    def is_round_timeout_due(self, room_id: str) -> bool:
        room = self.get_room(room_id)
        if not room or room.status != "active" or room.needs_conclusion:
            return False
        if not room.round_deadline_ts:
            return False
        status = self.get_round_status(room_id)
        if not status or not status.get("pending_agents"):
            return False
        return time.time() >= room.round_deadline_ts

    def prompt_member(self, room_id: str, host: str, target_agent: str, content: str) -> Optional[RoomMessage]:
        room = self.get_room(room_id)
        if not room or room.status != "active" or host != room.host:
            return None
        if target_agent not in room.members or target_agent == room.host:
            return None
        msg = RoomMessage(
            room_id=room_id,
            from_agent=host,
            content=content,
            msg_type="prompt",
            round=room.current_round,
        )
        with (self._rooms_dir / room_id / "messages.jsonl").open("a", encoding="utf-8") as f:
            f.write(msg.model_dump_json() + "\n")
        return msg

    def next_round_prompt(self, room_id: str, host: str, content: str) -> Optional[RoomMessage]:
        room = self.get_room(room_id)
        if not room or room.status != "active" or host != room.host:
            return None
        msg = RoomMessage(
            room_id=room_id,
            from_agent=host,
            content=content,
            msg_type="round_prompt",
            round=room.current_round,
        )
        with (self._rooms_dir / room_id / "messages.jsonl").open("a", encoding="utf-8") as f:
            f.write(msg.model_dump_json() + "\n")
        return msg

    def get_history(
        self,
        room_id: str,
        limit: Optional[int] = None,
        since_round: Optional[int] = None,
    ) -> List[RoomMessage]:
        jsonl_file = self._rooms_dir / room_id / "messages.jsonl"
        if not jsonl_file.exists():
            return []
        messages: List[RoomMessage] = []
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = RoomMessage(**json.loads(line))
                if since_round is not None and msg.round < since_round:
                    continue
                messages.append(msg)
            except Exception as e:
                logger.warning("Failed to parse room message: %s", e)
        if limit is not None:
            messages = messages[-limit:]
        return messages

    def close_room(self, room_id: str, host: str) -> Optional[Room]:
        room = self.get_room(room_id)
        if not room or host != room.host:
            return None
        room.status = "closed"
        room.closed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        room.needs_conclusion = False
        self._save_meta(room)
        return room

    def conclude_room(self, room_id: str, host: str, conclusion: str) -> Optional[Room]:
        room = self.get_room(room_id)
        if not room or host != room.host:
            return None
        msg = RoomMessage(
            room_id=room_id,
            from_agent=host,
            content=conclusion,
            msg_type="conclude",
            round=room.current_round,
        )
        with (self._rooms_dir / room_id / "messages.jsonl").open("a", encoding="utf-8") as f:
            f.write(msg.model_dump_json() + "\n")
        room.status = "closed"
        room.conclusion = conclusion
        room.closed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        room.needs_conclusion = False
        self._save_meta(room)
        return room

    def _advance_round_if_ready(self, room: Room) -> None:
        round_messages = self.get_history(room.room_id, since_round=room.current_round)
        responded_agents = {m.from_agent for m in round_messages if m.msg_type != "conclude"}
        required_agents = {m for m in room.members if m != room.host}
        if not required_agents.issubset(responded_agents):
            self._save_meta(room)
            return
        room.current_round += 1
        room.round_deadline_ts = (
            time.time() + room.round_timeout_sec if room.round_timeout_sec > 0 else None
        )
        if room.current_round > room.max_rounds > 0:
            room.needs_conclusion = True
        self._save_meta(room)

    def _save_meta(self, room: Room) -> None:
        meta_file = self._rooms_dir / room.room_id / "meta.json"
        meta_file.write_text(room.model_dump_json(indent=2), encoding="utf-8")
