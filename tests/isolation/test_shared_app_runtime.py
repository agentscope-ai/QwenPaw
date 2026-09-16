# -*- coding: utf-8 -*-
"""共享应用启动时的用户、会话和工作区隔离。"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.chats.repo.conversation import ConversationRecord
from qwenpaw.identity.models import PlatformRole
from qwenpaw.publications.models import DependencyReport, SharedAppPublicationRecord, SharedAppRecord
from qwenpaw.publications.service import SharedAppService
from qwenpaw.workspaces import WorkspaceResolver

NOW = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)


class Repository:
    def __init__(self, app, publication):
        self.app, self.publication, self.workspaces = app, publication, {}

    async def get_app(self, app_id):
        return self.app if app_id == self.app.id else None

    async def get_publication(self, publication_id):
        return self.publication if publication_id == self.publication.id else None

    async def get_user_workspace(self, app_id, publication_id, user_id):
        return self.workspaces.get((app_id, publication_id, user_id))

    async def create_user_workspace(self, record, **_kwargs):
        self.workspaces[(record.shared_app_id, record.publication_id, record.user_id)] = record
        return record


class Validator:
    async def validate(self, _manifest, *, mode):
        assert mode == "read"
        return DependencyReport()


class SnapshotBuilder:
    def verify(self, _key, _expected_hash):
        return True


class ConversationRepository:
    def __init__(self):
        self.user_id, self.rows = None, {}

    def with_user(self, user_id):
        self.user_id = user_id
        return self

    async def create_plain(self, chat, agent_id):
        self.rows[UUID(chat.id)] = ConversationRecord(
            id=UUID(chat.id), agent_id=agent_id, owner_user_id=UUID(chat.user_id),
            title=chat.name, status="active", created_at=chat.created_at,
            updated_at=chat.updated_at,
        )

    async def bind_publication(self, conversation_id, **values):
        current = self.rows[conversation_id]
        assert current.owner_user_id == self.user_id
        updated = current.model_copy(update={
            "shared_app_id": values["shared_app_id"],
            "publication_id": values["publication_id"],
            "updated_at": values["updated_at"],
        })
        self.rows[conversation_id] = updated
        return updated


class ChatManager:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.conversation_repository = ConversationRepository()

    async def create_chat(self, chat):
        await self.conversation_repository.create_plain(chat, self.agent_id)
        return chat

    async def delete_chats(self, chat_ids):
        for chat_id in chat_ids:
            self.conversation_repository.rows.pop(UUID(chat_id), None)
        return True


def actor(user_id):
    return ActorContext(
        user_id=user_id, actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER, admin_mode=False,
        request_id=str(uuid4()),
    )


@pytest.mark.asyncio
async def test_two_users_receive_distinct_private_workspaces(tmp_path: Path):
    owner_id, user_a, user_b = uuid4(), uuid4(), uuid4()
    app_id, publication_id, agent_id = uuid4(), uuid4(), uuid4()
    app = SharedAppRecord(
        id=app_id, agent_id=agent_id, owner_user_id=owner_id,
        status="active", current_publication_id=publication_id,
        created_at=NOW, updated_at=NOW,
    )
    publication = SharedAppPublicationRecord(
        id=publication_id, shared_app_id=app_id, version="r2",
        immutable_manifest={
            "display": {"name": "隔离应用"},
            "model": {"provider_id": "provider", "model": "model"},
            "integrity": {"workspace_hash": "hash"},
        },
        baseline_workspace_key=f"published_workspaces/{publication_id}",
        submitted_by=owner_id, review_status="approved",
    )
    baseline = tmp_path / publication.baseline_workspace_key
    baseline.mkdir(parents=True)
    (baseline / "seed.txt").write_text("baseline", encoding="utf-8")
    repository, manager = Repository(app, publication), ChatManager(agent_id)
    service = SharedAppService(
        repository, Validator(), snapshot_builder=SnapshotBuilder(), clock=lambda: NOW,
    )
    resolver = WorkspaceResolver(working_dir=tmp_path)

    left = await service.start_conversation(
        actor(user_a), app_id, agent_key="agent", chat_manager=manager,
        workspace_resolver=resolver, working_dir=tmp_path,
    )
    right = await service.start_conversation(
        actor(user_b), app_id, agent_key="agent", chat_manager=manager,
        workspace_resolver=resolver, working_dir=tmp_path,
    )

    assert left["workspace_key"] != right["workspace_key"]
    assert left["publication_id"] == right["publication_id"] == str(publication_id)
    assert manager.conversation_repository.rows[UUID(left["conversation_id"])].owner_user_id == user_a
    assert manager.conversation_repository.rows[UUID(right["conversation_id"])].owner_user_id == user_b
    assert (tmp_path / left["workspace_key"] / "seed.txt").read_text(encoding="utf-8") == "baseline"
