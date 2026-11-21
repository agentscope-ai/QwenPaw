"""撤权后的本人定时任务历史仍可由正常菜单读取。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from qwenpaw.app.crons import api
from qwenpaw.access.dependencies import get_actor
from tests.unit.app.conftest import make_cron_job_spec


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_kind", ["owner", "other", "admin"])
async def test_cron_owner_can_list_and_read_history_without_runtime(
    monkeypatch, actor_kind
):
    owner = uuid4()
    user = owner if actor_kind == "owner" else uuid4()
    actor = SimpleNamespace(user_id=user, platform_role=actor_kind)
    job = make_cron_job_spec().model_copy(update={"automation_owner_user_id": owner})
    repo = SimpleNamespace(
        list_owned_jobs=AsyncMock(return_value=[job] if user == owner else []),
        get_owned_job=AsyncMock(return_value=job if user == owner else None),
        get_owned_history=AsyncMock(return_value=[] if user == owner else None),
    )
    monkeypatch.setattr(
        api, "_owned_job_repository", lambda request: repo, raising=False
    )
    monkeypatch.setattr(api, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_agent_for_request",
        AsyncMock(side_effect=HTTPException(403, "revoked")),
    )
    app = FastAPI()
    app.dependency_overrides[get_actor] = lambda: actor
    app.include_router(api.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get("/api/cron/jobs?scope=mine")
        history = await client.get(f"/api/cron/jobs/{job.id}/history")
        detail = await client.get(f"/api/cron/jobs/{job.id}")
    assert listed.status_code == 200
    assert len(listed.json()) == (1 if user == owner else 0)
    assert history.status_code == (200 if user == owner else 404)
    assert detail.status_code == (200 if user == owner else 403)
