from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from qwenpaw.app.chat_file_references import ChatFileReferences
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.personal_library.service import PersonalLibraryService
from tests.unit.personal_library.test_runtime_access import GrantRepository
from tests.unit.artifacts.test_service import Repository as ArtifactRepository
from qwenpaw.artifacts.service import ArtifactService
from qwenpaw.workspaces.resolver import WorkspaceKind, WorkspaceResolver


class Attachments:
    def __init__(self, records):
        self.records = records

    async def list_owned_attachments(self, **kwargs):
        return self.records

    async def get_attachment(self, *, attachment_id, owner_user_id):
        return next((r for r in self.records if r.id == attachment_id and r.owner_user_id == owner_user_id), None)


@pytest.mark.asyncio
async def test_library_mentions_require_same_owner_and_agent_scope(tmp_path):
    owner, other = uuid4(), uuid4()
    repository = GrantRepository()
    library = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await library.create_text(
        owner_user_id=owner, agent_key="allowed", relative_path="private-requirements.md", content="owner-only-body",
    )
    refs = [{"source": "personal_library", "id": str(document.id)}]

    def resolver(user, agent):
        return ChatFileReferences(owner=user, agent_key=agent, conversation_id="",
            profile_root=tmp_path, library=library, attachments=None, artifacts=None)

    assert (await resolver(owner, "allowed").resolve(refs))[0]["content"] == "owner-only-body"
    for user, agent in [(other, "allowed"), (owner, "ungranted")]:
        assert await resolver(user, agent).catalog() == []
        assert await library.match_prompt_documents(
            owner_user_id=user, agent_key=agent, text="review private-requirements",
        ) == []
        with pytest.raises(HTTPException) as error:
            await resolver(user, agent).resolve(refs)
        assert error.value.status_code == 404

    assert (await resolver(owner, "allowed").catalog())[0]["id"] == str(document.id)
    assert not (tmp_path / "user_workspaces").exists()


@pytest.mark.asyncio
async def test_catalog_and_resolution_enforce_scopes_and_lifecycle(tmp_path):
    owner, other, chat, other_chat = uuid4(), uuid4(), uuid4(), uuid4()
    repository = GrantRepository()
    library = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    doc = await library.create_text(owner_user_id=owner, relative_path="nested/需求.md", content="private library")
    await repository.set_grant(owner_user_id=owner, agent_id=agent_database_id("default"), enabled=True)
    (tmp_path / "SOUL.md").write_text("shared profile", encoding="utf-8")
    (tmp_path / "secret.md").write_text("not a profile", encoding="utf-8")
    attachment = tmp_path / "upload.txt"
    attachment.write_text("temporary body", encoding="utf-8")
    records = [SimpleNamespace(id=uuid4(), owner_user_id=user, agent_id=agent_database_id(agent), conversation_id=conversation,
        lifecycle=state, storage_key=str(attachment), original_name="upload.txt")
        for user, agent, conversation, state in [(owner,"default",chat,"temporary"),(other,"default",chat,"temporary"),
            (owner,"default",other_chat,"temporary"),(owner,"other",chat,"temporary"),(owner,"default",chat,"deleted")]]
    resolver = ChatFileReferences(owner=owner, agent_key="default", conversation_id=str(chat),
        profile_root=tmp_path, library=library, attachments=Attachments(records), artifacts=None)
    catalog = await resolver.catalog()
    assert {(x["source"], x["id"]) for x in catalog} == {
        ("personal_library",str(doc.id)), ("agent_profile","SOUL.md"), ("temporary",str(records[0].id))}
    result = await resolver.resolve([{"source":"temporary","id":str(records[0].id)}, {"source":"agent_profile","id":"SOUL.md"}])
    assert [x["content"] for x in result] == ["temporary body", "shared profile"]
    for record in records[1:]:
        with pytest.raises(HTTPException):
            await resolver.resolve([{"source":"temporary","id":str(record.id)}])
    for name in ["secret.md", "../SOUL.md", "C:/SOUL.md"]:
        with pytest.raises(HTTPException):
            await resolver.resolve([{"source":"agent_profile","id":name}])
    assert (await resolver.resolve([{"source":"personal_library","id":str(doc.id)}]))[0]["content"] == "private library"


@pytest.mark.asyncio
async def test_rejects_forged_fields_and_oversized_reference_list(tmp_path):
    resolver = ChatFileReferences(owner=uuid4(), agent_key="a", conversation_id="", profile_root=tmp_path,
        library=None, attachments=None, artifacts=None)
    for refs in [[{"source":"unknown", "id":"x"}], [{"source":"agent_profile", "id":"SOUL.md", "content":"forged"}], [{}]*6, "bad"]:
        with pytest.raises(HTTPException):
            await resolver.resolve(refs)


@pytest.mark.asyncio
async def test_artifact_references_recheck_owner_agent_and_deleted_state(tmp_path):
    owner, other = uuid4(), uuid4()
    service = ArtifactService(repository=ArtifactRepository(), working_dir=tmp_path)
    workspace = WorkspaceResolver(working_dir=tmp_path)
    root = workspace.resolve(kind=WorkspaceKind.USER_RUNTIME, resource_id="a", actor_user_id=owner)
    source = workspace.ensure_standard_directories(root) / "report.md"
    source.write_text("private artifact", encoding="utf-8")
    artifact = await service.publish(owner_user_id=owner, agent_key="a", source=source)
    ref = [{"source": "artifact", "id": str(artifact.id)}]
    def resolver(user=owner, agent="a"):
        return ChatFileReferences(owner=user, agent_key=agent, conversation_id="", profile_root=tmp_path,
            library=None, attachments=None, artifacts=service)
    assert (await resolver().resolve(ref))[0]["content"] == "private artifact"
    assert any(item["id"] == str(artifact.id) for item in await resolver().catalog())
    for user, agent in [(other, "a"), (owner, "b")]:
        assert await resolver(user, agent).catalog() == []
        with pytest.raises(HTTPException):
            await resolver(user, agent).resolve(ref)
    await service.delete(owner_user_id=owner, agent_key="a", artifact_id=artifact.id)
    with pytest.raises(HTTPException):
        await resolver().resolve(ref)
