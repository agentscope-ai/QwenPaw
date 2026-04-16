# -*- coding: utf-8 -*-
"""Meeting management API endpoints.

Provides CRUD operations for meetings: create, start, stop, list, query.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...meetings import (
    MeetingConfig,
    MeetingManager,
    MeetingRepository,
    MeetingStatus,
    MeetingType,
    MeetingTopic,
    MeetingParticipant,
    AgentEndpoint,
    RoleType,
)
from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["meetings"])

# In-memory cache for active meetings (reconstructed from repo on demand)
_active_meetings: dict[str, MeetingManager] = {}


async def get_meeting_repo(_request: Request) -> MeetingRepository:
    """Get meeting repository using global WORKING_DIR.

    Meetings are stored at WORKING_DIR/meetings/ (shared across all agents),
    not under individual agent workspace directories.

    Args:
        request: FastAPI request object

    Returns:
        MeetingRepository configured with the global WORKING_DIR
    """
    return MeetingRepository(str(WORKING_DIR))


class EndpointRequest(BaseModel):
    url: str
    auth_key: str


class ParticipantRequest(BaseModel):
    id: str
    name: str
    intent: Optional[str] = None
    endpoint: Optional[EndpointRequest] = None


class TopicRequest(BaseModel):
    title: str
    description: Optional[str] = None
    context: Optional[str] = None


class MeetingCreateRequest(BaseModel):
    meeting_name: str
    meeting_type: str = "TEMPORARY"
    topic: TopicRequest
    participants: list[ParticipantRequest] = []
    host_id: str
    decider_id: str
    rounds: list[str] = Field(default_factory=lambda: ["raw"])


class MeetingUpdateRequest(BaseModel):
    meeting_name: Optional[str] = None
    topic: Optional[TopicRequest] = None


def _reconstruct_meeting(
    meeting_id: str,
    repo: MeetingRepository,
) -> Optional[MeetingManager]:
    result = repo.get(meeting_id)
    if not result:
        return None
    config, status, doc_paths = result
    manager = MeetingManager(config)
    manager.status = status
    # Restore document references from persisted paths — do NOT call create()
    # which would regenerate paths with new timestamps, making existing
    # docs unreachable
    if doc_paths:
        from qwenpaw.meetings.models import MeetingDocument

        if doc_paths.get("goals"):
            manager.goals_doc = MeetingDocument(
                meeting_id=config.meeting_id,
                doc_type="goals",
                path=doc_paths["goals"],
            )
        if doc_paths.get("records"):
            manager.records_doc = MeetingDocument(
                meeting_id=config.meeting_id,
                doc_type="records",
                path=doc_paths["records"],
            )
        if doc_paths.get("summary"):
            manager.summary_doc = MeetingDocument(
                meeting_id=config.meeting_id,
                doc_type="summary",
                path=doc_paths["summary"],
            )
    return manager


def _get_or_reconstruct(
    meeting_id: str,
    repo: MeetingRepository,
) -> Optional[MeetingManager]:
    if meeting_id in _active_meetings:
        return _active_meetings[meeting_id]
    manager = _reconstruct_meeting(meeting_id, repo)
    if manager:
        _active_meetings[meeting_id] = manager
    return manager


@router.post("", summary="Create Meeting")
async def create_meeting(
    request_data: MeetingCreateRequest,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    # Build participants with roles based on host_id and decider_id
    participants = []
    for p in request_data.participants:
        roles = [RoleType.REPORTER]  # Default: all are reporters
        if p.id == request_data.host_id:
            roles.append(RoleType.HOST)
        if p.id == request_data.decider_id:
            roles.append(RoleType.DECIDER)

        participants.append(
            MeetingParticipant(
                id=p.id,
                name=p.name,
                roles=roles,
                intent=p.intent,
                endpoint=AgentEndpoint(
                    url=p.endpoint.url,
                    auth_key=p.endpoint.auth_key,
                )
                if p.endpoint
                else None,
            ),
        )

    config = MeetingConfig(
        meeting_name=request_data.meeting_name,
        meeting_type=MeetingType(request_data.meeting_type),
        topic=MeetingTopic(
            title=request_data.topic.title,
            description=request_data.topic.description,
            context=request_data.topic.context,
        ),
        participants=participants,
        flow={
            "rounds": request_data.rounds,
        },
    )

    mgr = MeetingManager(config)
    mgr.create()
    if mgr.c.meeting_id is None:
        raise ValueError("meeting_id cannot be None after create()")
    _active_meetings[mgr.c.meeting_id] = mgr

    doc_paths = {
        "goals": mgr.goals_doc.path if mgr.goals_doc else "",
        "records": mgr.records_doc.path if mgr.records_doc else "",
        "summary": mgr.summary_doc.path if mgr.summary_doc else "",
    }

    repo.save(mgr.c, mgr.status, doc_paths)

    # 临时会议创建后立即开始（后台异步执行，不阻塞请求）
    if config.meeting_type == MeetingType.TEMPORARY:
        # 设置为 RUNNING 状态，因为会议即将在后台开始
        mgr.status = MeetingStatus.RUNNING
        repo.save(mgr.c, mgr.status, doc_paths)

        async def _run_temporary_meeting():
            """后台运行临时会议，完成后更新状态和文档路径."""
            try:
                await mgr.run_async()
            except Exception as e:
                logger.error(f"Temporary meeting start failed: {e}")
            finally:
                await asyncio.sleep(0.3)  # 等待状态稳定
                doc_paths = {
                    "goals": mgr.goals_doc.path if mgr.goals_doc else "",
                    "records": mgr.records_doc.path if mgr.records_doc else "",
                    "summary": mgr.summary_doc.path if mgr.summary_doc else "",
                }
                repo.save(mgr.c, mgr.status, doc_paths)
                _active_meetings.pop(mgr.c.meeting_id)

        asyncio.create_task(_run_temporary_meeting())

    return {
        "meeting_id": mgr.c.meeting_id,
        "meeting_name": mgr.c.meeting_name,
        "status": mgr.status.value,
        "topic_title": mgr.c.topic.title,
        "participants_count": len(mgr.c.participants),
        "created_at": datetime.now().isoformat(),
    }


@router.get("", summary="List Meetings")
async def list_meetings(
    skip: int = 0,
    limit: int = 100,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    meetings_data, total = repo.list(skip=skip, limit=limit)
    return {
        "meetings": meetings_data,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/{meeting_id}", summary="Get Meeting")
async def get_meeting(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    documents = {}
    if manager.goals_doc:
        documents["goals_path"] = manager.goals_doc.path
    if manager.records_doc:
        documents["records_path"] = manager.records_doc.path
    if manager.summary_doc:
        documents["summary_path"] = manager.summary_doc.path

    return {
        "meeting_id": manager.c.meeting_id,
        "meeting_name": manager.c.meeting_name,
        "meeting_type": manager.c.meeting_type.value,
        "status": manager.status.value,
        "topic": {
            "title": manager.c.topic.title,
            "description": manager.c.topic.description,
            "context": manager.c.topic.context,
        },
        "participants": [
            {
                "id": p.id,
                "name": p.name,
                "roles": [r.value for r in p.roles],
                "intent": p.intent,
            }
            for p in manager.c.participants
        ],
        "documents": documents,
        "current_round": manager.current_round,
        "current_phase": manager.current_phase.value
        if manager.current_phase
        else None,
    }


@router.patch("/{meeting_id}", summary="Update Meeting")
async def update_meeting(
    meeting_id: str,
    request_data: MeetingUpdateRequest,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    result = repo.get(meeting_id)
    if not result:
        raise HTTPException(status_code=404, detail="Meeting not found")

    config, status, doc_paths = result

    # Only allow updating non-running meetings
    if status in (MeetingStatus.RUNNING, MeetingStatus.INITIALIZED):
        raise HTTPException(
            status_code=400,
            detail="Cannot edit a meeting that is running or initialized",
        )

    # Apply updates
    if request_data.meeting_name is not None:
        config.meeting_name = request_data.meeting_name
    if request_data.topic is not None:
        config.topic = MeetingTopic(
            title=request_data.topic.title,
            description=request_data.topic.description,
            context=request_data.topic.context,
        )

    repo.save(config, status, doc_paths)

    return {
        "meeting_id": config.meeting_id,
        "meeting_name": config.meeting_name,
        "meeting_type": config.meeting_type.value,
        "status": status.value,
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
            }
            for p in config.participants
        ],
    }


@router.get("/{meeting_id}/records", summary="Get Meeting Records")
async def get_meeting_records(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not manager.records_doc:
        raise HTTPException(status_code=404, detail="Records not found")

    content = manager.storage.read_doc(manager.records_doc.path)
    return {
        "meeting_id": meeting_id,
        "records_path": manager.records_doc.path,
        "content": content,
    }


@router.get("/{meeting_id}/summary", summary="Get Meeting Summary")
async def get_meeting_summary(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not manager.summary_doc:
        raise HTTPException(status_code=404, detail="Summary not found")

    content = manager.storage.read_doc(manager.summary_doc.path)
    return {
        "meeting_id": meeting_id,
        "summary_path": manager.summary_doc.path,
        "content": content,
    }


@router.get("/{meeting_id}/goals", summary="Get Meeting Goals")
async def get_meeting_goals(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not manager.goals_doc:
        raise HTTPException(status_code=404, detail="Goals not found")

    content = manager.storage.read_doc(manager.goals_doc.path)
    return {
        "meeting_id": meeting_id,
        "goals_path": manager.goals_doc.path,
        "content": content,
    }


@router.get("/{meeting_id}/reasons", summary="Get Meeting Reasons")
async def get_meeting_reasons(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    """Get the reasons JSON file for a meeting.

    The reasons file stores the thinking process (Chain of Thought) for each
    agent utterance during the meeting, stored alongside records.md.
    """
    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Derive reasons JSON path from records_doc.path
    # pylint: disable=protected-access
    reasons_path = manager._get_reasons_json_path()
    full_path = Path(manager.storage.workspace_dir) / reasons_path

    if not full_path.exists():
        return {
            "meeting_id": meeting_id,
            "reasons_path": str(reasons_path),
            "entries": [],
        }

    try:
        import json

        content = full_path.read_text(encoding="utf-8")
        entries = json.loads(content)
        return {
            "meeting_id": meeting_id,
            "reasons_path": str(reasons_path),
            "entries": entries,
        }
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to parse reasons JSON",
        ) from exc


@router.post("/{meeting_id}/start", summary="Start Meeting")
async def start_meeting(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if manager.status in (MeetingStatus.RUNNING, MeetingStatus.COMPLETED):
        raise HTTPException(
            status_code=400,
            detail="Meeting cannot be started",
        )

    # Reset documents before starting (clear old records/goals/summary)
    manager.reset()

    # Update persisted doc paths
    doc_paths = {
        "goals": manager.goals_doc.path if manager.goals_doc else "",
        "records": manager.records_doc.path if manager.records_doc else "",
        "summary": manager.summary_doc.path if manager.summary_doc else "",
    }
    repo.save(manager.c, manager.status, doc_paths)

    # Start the meeting
    try:
        result = await manager.run_async()
        repo.update_status(meeting_id, manager.status)
        return {
            "status": "started",
            "meeting_id": meeting_id,
            "result": result,
        }
    except Exception as e:
        logger.error(f"Start meeting error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{meeting_id}/stop", summary="Stop Meeting")
async def stop_meeting(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    manager.stop()
    repo.update_status(meeting_id, manager.status)
    return {"status": "stopped", "meeting_id": meeting_id}


@router.get("/{meeting_id}/status", summary="Get Meeting Status")
async def get_meeting_status(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return {
        "meeting_id": manager.c.meeting_id,
        "status": manager.status.value,
        "current_round": manager.current_round,
        "current_phase": manager.current_phase.value
        if manager.current_phase
        else None,
    }


@router.post("/{meeting_id}/restart", summary="Restart Meeting")
async def restart_meeting(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    """Restart a meeting - reset documents and status, then start fresh."""

    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if manager.status == MeetingStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail="Cannot restart a running meeting",
        )

    # Reset the meeting (clear docs, reset status)
    manager.reset()

    # Update persisted doc paths
    doc_paths = {
        "goals": manager.goals_doc.path if manager.goals_doc else "",
        "records": manager.records_doc.path if manager.records_doc else "",
        "summary": manager.summary_doc.path if manager.summary_doc else "",
    }
    repo.save(manager.c, manager.status, doc_paths)

    # Start the meeting
    try:
        result = await manager.run_async()
        repo.update_status(meeting_id, manager.status)
        return {
            "status": "restarted",
            "meeting_id": meeting_id,
            "result": result,
        }
    except Exception as e:
        logger.error(f"Restart meeting error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{meeting_id}", summary="Delete Meeting")
async def delete_meeting(
    meeting_id: str,
    _request: Request,
    repo: MeetingRepository = Depends(get_meeting_repo),
) -> dict:
    manager = _get_or_reconstruct(meeting_id, repo)
    if not manager:
        raise HTTPException(status_code=404, detail="Meeting not found")

    for doc in [manager.goals_doc, manager.records_doc, manager.summary_doc]:
        if doc:
            full_path = Path(manager.storage.workspace_dir) / doc.path
            if full_path.exists():
                full_path.unlink()

    if meeting_id in _active_meetings:
        del _active_meetings[meeting_id]

    repo.delete(meeting_id)

    return {"status": "deleted", "meeting_id": meeting_id}
