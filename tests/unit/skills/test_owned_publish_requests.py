"""发布申请人可只读自己的固定快照，审核仍是管理员职责。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.dependencies import get_actor
from qwenpaw.app.routers import skill_governance
from qwenpaw.identity.models import PlatformRole
from qwenpaw.skills.service import SkillGovernanceService
from qwenpaw.skills.snapshots import SnapshotStore


@pytest.mark.asyncio
@pytest.mark.parametrize("person", ["owner", "other", "admin"])
async def test_request_owner_reads_snapshot_without_agent_edit_rights(
    tmp_path, monkeypatch, person
):
    owner, request_id = uuid4(), uuid4()
    user_id = owner if person == "owner" else uuid4()
    actor = ActorContext(
        user_id,
        ActorType.USER,
        PlatformRole.ADMIN if person == "admin" else PlatformRole.MEMBER,
        False,
        "owner-requests",
    )
    source = tmp_path / "source"
    source.mkdir()
    text = "---\nname: sample\ndescription: Example\n---\nOriginal snapshot"
    (source / "SKILL.md").write_text(text, encoding="utf-8")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    fixed = snapshots.capture(source, "sample")
    row = {
        "id": request_id,
        "submitted_by": owner,
        "snapshot_key": fixed.snapshot_key,
        "content_hash": fixed.content_hash,
        "skill_name": "sample",
        "status": "approved",
        "review_version": 1,
        "review_note": "通过",
    }

    async def get_request(identifier, *, submitted_by=None):
        if identifier != request_id or (
            submitted_by is not None and submitted_by != owner
        ):
            raise ValueError("request_not_found")
        return row

    async def list_requests(*, submitted_by=None):
        return [row] if submitted_by in {None, owner} else []

    role = AsyncMock(
        side_effect=AssertionError(
            "Reading a submission must not inspect Agent editor rights"
        )
    )
    repo = SimpleNamespace(
        get_request=get_request, list_requests=list_requests, agent_role=role
    )
    service = SkillGovernanceService(repo, snapshots, tmp_path / "pool")
    monkeypatch.setattr(skill_governance, "get_skill_service", lambda: service)
    app = FastAPI()
    app.dependency_overrides[get_actor] = lambda: actor
    app.include_router(skill_governance.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get(
            "/api/skill-governance/requests?scope=mine",
            headers={"X-Agent-Id": "old-unavailable-agent"},
        )
        detail = await client.get(f"/api/skill-governance/requests/{request_id}")
        content = await client.get(
            f"/api/skill-governance/requests/{request_id}/files/SKILL.md"
        )
        review = (
            await client.post(
                f"/api/skill-governance/requests/{request_id}/review",
                json={"decision": "approve", "expected_version": 1, "note": "no"},
            )
            if person != "admin"
            else None
        )
    assert listed.status_code == 200
    assert len(listed.json()["requests"]) == (1 if person == "owner" else 0)
    assert (
        detail.status_code == content.status_code == (403 if person == "other" else 200)
    )
    if person != "other":
        assert content.json()["content"] == text
    if review is not None:
        assert review.status_code == 403
    role.assert_not_awaited()
