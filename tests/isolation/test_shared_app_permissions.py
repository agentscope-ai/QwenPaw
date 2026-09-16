# -*- coding: utf-8 -*-
"""共享应用 owner 与管理员权限及状态机测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole
from qwenpaw.publications.models import (
    DependencyReport,
    SharedAppPublicationRecord,
    SharedAppRecord,
)


NOW = datetime(2026, 9, 7, 2, 0, tzinfo=UTC)


def actor(user_id, role=PlatformRole.MEMBER):
    return ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="request-1",
    )


class Repository:
    def __init__(self, app, publication):
        self.app = app
        self.publication = publication
        self.reviewed = []
        self.switched = []

    async def get_app(self, app_id):
        return self.app if app_id == self.app.id else None

    async def get_publication(self, publication_id):
        return self.publication if publication_id == self.publication.id else None

    async def review(self, publication_id, **values):
        self.reviewed.append((publication_id, values))
        self.publication = self.publication.model_copy(
            update={
                "review_status": values["decision"],
                "reviewed_by": values["reviewer_id"],
                "review_note": values["note"],
                "reviewed_at": values["reviewed_at"],
            }
        )
        return self.publication

    async def switch_current(self, app_id, **values):
        self.switched.append((app_id, values))
        self.app = self.app.model_copy(
            update={
                "status": "active",
                "current_publication_id": values["publication_id"],
                "updated_at": values["changed_at"],
            }
        )
        return self.app


class Validator:
    async def validate(self, manifest, *, mode):
        assert manifest and mode in {"read", "strong"}
        return DependencyReport()


@pytest.fixture
def lifecycle():
    owner_id = uuid4()
    app_id, publication_id, agent_id = uuid4(), uuid4(), uuid4()
    app = SharedAppRecord(
        id=app_id,
        agent_id=agent_id,
        owner_user_id=owner_id,
        status="draft",
        created_at=NOW,
        updated_at=NOW,
    )
    publication = SharedAppPublicationRecord(
        id=publication_id,
        shared_app_id=app_id,
        version="r1",
        immutable_manifest={"model": {"provider_id": "p", "model": "m"}},
        baseline_workspace_key=f"published_workspaces/{publication_id}",
        submitted_by=owner_id,
        review_status="pending",
    )
    return owner_id, app, publication, Repository(app, publication)


@pytest.mark.asyncio
async def test_owner_cannot_review_publication(lifecycle):
    from qwenpaw.publications.service import PublicationAccessError, SharedAppService

    owner_id, _app, publication, repository = lifecycle
    service = SharedAppService(repository, Validator(), clock=lambda: NOW)

    with pytest.raises(PublicationAccessError, match="publications_review_required"):
        await service.review(actor(owner_id), publication.id, "approved", "ok")


@pytest.mark.asyncio
async def test_admin_approves_then_publishes(lifecycle):
    from qwenpaw.publications.service import SharedAppService

    _owner_id, app, publication, repository = lifecycle
    admin_id = uuid4()
    service = SharedAppService(repository, Validator(), clock=lambda: NOW)

    approved = await service.review(
        actor(admin_id, PlatformRole.ADMIN), publication.id, "approved", "ok"
    )
    active = await service.publish(
        actor(admin_id, PlatformRole.ADMIN),
        app.id,
        approved.id,
        expected_current_id=None,
    )

    assert approved.review_status == "approved"
    assert active.current_publication_id == publication.id
    assert repository.switched[0][1]["actor_id"] == admin_id


@pytest.mark.asyncio
async def test_pending_publication_cannot_be_published(lifecycle):
    from qwenpaw.publications.service import PublicationStateError, SharedAppService

    _owner_id, app, publication, repository = lifecycle
    service = SharedAppService(repository, Validator(), clock=lambda: NOW)

    with pytest.raises(PublicationStateError, match="publication_not_approved"):
        await service.publish(
            actor(uuid4(), PlatformRole.ADMIN),
            app.id,
            publication.id,
            expected_current_id=None,
        )


@pytest.mark.asyncio
async def test_member_cannot_publish(lifecycle):
    from qwenpaw.publications.service import PublicationAccessError, SharedAppService

    _owner_id, app, publication, repository = lifecycle
    service = SharedAppService(repository, Validator(), clock=lambda: NOW)

    with pytest.raises(PublicationAccessError, match="publications_review_required"):
        await service.publish(
            actor(uuid4()), app.id, publication.id, expected_current_id=None
        )
