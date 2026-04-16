# -*- coding: utf-8 -*-
"""Meeting repository for JSON-based persistence."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import (
    MeetingConfig,
    MeetingStatus,
    MeetingType,
    MeetingTopic,
    MeetingParticipant,
    AgentEndpoint,
    MeetingFlow,
    RoleType,
)

logger = logging.getLogger(__name__)


def _lock_ex(f) -> None:
    """Acquire exclusive file lock (cross-platform)."""
    try:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    except ImportError:
        import msvcrt

        msvcrt.locking(
            f.fileno(),
            msvcrt.LK_NBLCK,
            os.path.getsize(f.name) or 1,
        )


def _lock_sh(f) -> None:
    """Acquire shared file lock (cross-platform)."""
    try:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
    except ImportError:
        # Windows: skip shared lock; reads are safe without it
        pass


def _unlock(f) -> None:
    """Release file lock (cross-platform)."""
    try:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except ImportError:
        try:
            import msvcrt

            msvcrt.locking(
                f.fileno(),
                msvcrt.LK_UNLCK,
                os.path.getsize(f.name) or 1,
            )
        except Exception:
            pass


class MeetingRepository:
    """JSON file-based meeting metadata repository."""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.meta_dir = self.workspace_dir / "meetings" / "meta"
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def _get_meta_path(self, meeting_id: str) -> Path:
        return self.meta_dir / f"{meeting_id}.json"

    def _serialize_meeting(
        self,
        config: MeetingConfig,
        status: MeetingStatus,
        doc_paths: Optional[dict] = None,
    ) -> dict:
        return {
            "meeting_id": config.meeting_id,
            "meeting_name": config.meeting_name,
            "meeting_type": config.meeting_type.value,
            "topic": {
                "title": config.topic.title,
                "description": config.topic.description,
                "context": config.topic.context,
            },
            "participants": [
                {
                    "id": p.id,
                    "name": p.name,
                    "roles": [r.value for r in p.roles],
                    "intent": p.intent,
                    "endpoint": {
                        "url": p.endpoint.url,
                        "auth_key": p.endpoint.auth_key,
                    }
                    if p.endpoint
                    else None,
                }
                for p in config.participants
            ],
            "flow": {
                "rounds": config.flow.rounds,
                "speakers": config.flow.speakers,
                "timeout_per_round": config.flow.timeout_per_round,
            },
            "doc_paths": doc_paths or {},
            "status": status.value,
            "created_at": datetime.now().isoformat(),
        }

    def _deserialize_meeting(
        self,
        data: dict,
    ) -> tuple[MeetingConfig, MeetingStatus, dict]:
        flow_data = data.get("flow", {})
        config = MeetingConfig(
            meeting_id=data["meeting_id"],
            meeting_name=data["meeting_name"],
            meeting_type=MeetingType(data["meeting_type"]),
            topic=MeetingTopic(
                title=data["topic"]["title"],
                description=data["topic"].get("description"),
                context=data["topic"].get("context"),
            ),
            participants=[
                MeetingParticipant(
                    id=p["id"],
                    name=p["name"],
                    roles=[RoleType(r) for r in p.get("roles", ["OBSERVER"])],
                    intent=p.get("intent"),
                    endpoint=AgentEndpoint(
                        url=p["endpoint"]["url"],
                        auth_key=p["endpoint"]["auth_key"],
                    )
                    if p.get("endpoint")
                    else None,
                )
                for p in data.get("participants", [])
            ],
            flow=MeetingFlow(
                rounds=flow_data.get("rounds", ["raw"]),
                speakers=flow_data.get("speakers", []),
                timeout_per_round=flow_data.get("timeout_per_round", 120),
            ),
        )
        status = MeetingStatus(data.get("status", "CREATED"))
        doc_paths = data.get("doc_paths", {})
        return config, status, doc_paths

    def save(
        self,
        config: MeetingConfig,
        status: MeetingStatus,
        doc_paths: Optional[dict] = None,
    ) -> None:
        if config.meeting_id is None:
            raise ValueError("config.meeting_id cannot be None")
        meta_path = self._get_meta_path(config.meeting_id)
        data = self._serialize_meeting(config, status, doc_paths)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            _lock_ex(f)
            json.dump(data, f, ensure_ascii=False, indent=2)
            _unlock(f)

    def get(
        self,
        meeting_id: str,
    ) -> Optional[tuple[MeetingConfig, MeetingStatus, dict]]:
        meta_path = self._get_meta_path(meeting_id)
        if not meta_path.exists():
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            _lock_sh(f)

            data = json.load(f)
            _unlock(f)
        return self._deserialize_meeting(data)

    def list(self, skip: int = 0, limit: int = 100) -> tuple[list[dict], int]:
        meta_files = sorted(
            self.meta_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        total = len(meta_files)
        paginated = meta_files[skip : skip + limit]
        meetings = []
        for meta_file in paginated:
            with open(meta_file, "r", encoding="utf-8") as f:
                _lock_sh(f)
                data = json.load(f)
                _unlock(f)
            meetings.append(data)
        return meetings, total

    def delete(self, meeting_id: str) -> bool:
        meta_path = self._get_meta_path(meeting_id)
        if meta_path.exists():
            meta_path.unlink()
            return True
        return False

    def update_status(self, meeting_id: str, status: MeetingStatus) -> bool:
        result = self.get(meeting_id)
        if not result:
            return False
        config, _, doc_paths = result
        self.save(config, status, doc_paths)
        return True
