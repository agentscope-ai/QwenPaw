"""Exercise private output -> automatic archive -> library -> later reference."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.artifacts import collection
from qwenpaw.artifacts.middleware import ArtifactCollectionMiddleware
from qwenpaw.artifacts.service import ArtifactService, ArtifactNotFound
from qwenpaw.app.chat_file_references import ChatFileReferences
from qwenpaw.personal_library.service import PersonalLibraryService
from qwenpaw.services.workspace_files import resolve_private_task_directory
from tests.unit.artifacts.test_service import Repository
from tests.unit.personal_library.test_runtime_access import GrantRepository


@pytest.mark.asyncio
async def test_generated_files_are_archived_without_send_and_saved_library_is_scoped(tmp_path, monkeypatch):
    owner, other, chat = uuid4(), uuid4(), uuid4()
    context = {"user_id": str(owner), "agent_id": "qa", "conversation_id": str(chat)}
    cwd = resolve_private_task_directory(actor_user_id=owner, agent_id="qa", conversation_id=str(chat), working_dir=tmp_path)
    service = ArtifactService(repository=Repository(), working_dir=tmp_path)
    library = PersonalLibraryService(repository=GrantRepository(), working_dir=tmp_path)
    monkeypatch.setattr(collection, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(collection, "ArtifactService", lambda **kwargs: service)

    async def generate():
        (cwd / "note.md").write_text("成都攻略", encoding="utf-8")
        (cwd / "poster.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (cwd / "report.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
        (cwd / ".work").mkdir()
        (cwd / ".work" / "scratch.md").write_text("intermediate", encoding="utf-8")
        yield "generated"

    assert [item async for item in ArtifactCollectionMiddleware().on_acting(SimpleNamespace(_request_context=context), {}, generate)] == ["generated"]
    outputs = await service.list_active(owner_user_id=owner, agent_key="qa")
    assert {item.original_name for item in outputs} == {"note.md", "poster.png", "report.pdf"}
    assert {item.media_type for item in outputs} >= {"image/png", "application/pdf"}
    await collection.collect_current_session_artifacts(context)
    assert len(await service.list_active(owner_user_id=owner, agent_key="qa")) == 3
    note = next(item for item in outputs if item.original_name == "note.md")
    saved = await library.copy_from_artifact(owner_user_id=owner, agent_id="qa", source_path=note.relative_path, destination_path="saved/note.md")
    refs = ChatFileReferences(owner=owner, agent_key="qa", conversation_id=str(uuid4()), profile_root=tmp_path, library=library, artifacts=service, attachments=None)
    assert (await refs.resolve([{"source": "personal_library", "id": str(saved.id)}]))[0]["content"] == "成都攻略"
    for user, agent in [(other, "qa"), (owner, "other-agent")]:
        assert await service.list_active(owner_user_id=user, agent_key=agent) == []
        assert await library.search_text(owner_user_id=user, agent_key=agent, query="成都") == []
        with pytest.raises(ArtifactNotFound):
            await service.download_path(owner_user_id=user, agent_key=agent, artifact_id=note.id)
