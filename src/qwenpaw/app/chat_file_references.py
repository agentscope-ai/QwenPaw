"""对话文件引用：所有来源均在读取时按可信身份重新校验。"""
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from ..access.agent_repository import agent_database_id

PROFILE_FILES = frozenset({"AGENTS.md", "SOUL.md", "PROFILE.md", "MEMORY.md", "HEARTBEAT.md", "BOOTSTRAP.md"})
TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".csv"})
SOURCES = ("temporary", "personal_library", "agent_profile", "artifact")


class ChatFileReferences:
    def __init__(self, *, owner, agent_key, conversation_id, profile_root, library, attachments, artifacts):
        self.owner = owner
        self.agent_key = agent_key
        self.conversation = UUID(conversation_id) if conversation_id else None
        self.root = Path(profile_root).resolve()
        self.library = library
        self.attachments = attachments
        self.artifacts = artifacts

    def _temporary_allowed(self, record):
        return (record is not None and record.owner_user_id == self.owner
                and record.agent_id == agent_database_id(self.agent_key)
                and record.conversation_id in {None, self.conversation}
                and record.lifecycle == "temporary")

    def _profile_path(self, name):
        if name not in PROFILE_FILES:
            raise ValueError("invalid_profile")
        path = self.root / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.root) or not path.is_file():
            raise FileNotFoundError(name)
        return path

    @staticmethod
    def _entry(source, identifier, name, relative_path):
        return {"source": source, "id": str(identifier), "name": name, "relative_path": relative_path}

    async def catalog(self):
        items = []
        if self.attachments is not None:
            records = await self.attachments.list_owned_attachments(owner_user_id=self.owner,
                agent_id=agent_database_id(self.agent_key), lifecycle="temporary")
            for record in records:
                if self._temporary_allowed(record) and Path(record.original_name).suffix.lower() in TEXT_SUFFIXES:
                    path = Path(record.storage_key)
                    if path.is_file() and not path.is_symlink():
                        items.append(self._entry("temporary", record.id, record.original_name, record.original_name))
        if self.library is not None:
            for doc in await self.library.reference_documents(owner_user_id=self.owner, agent_key=self.agent_key):
                items.append(self._entry("personal_library", doc.id, doc.name, doc.relative_path))
        for name in sorted(PROFILE_FILES):
            try:
                self._profile_path(name)
                items.append(self._entry("agent_profile", name, name, name))
            except (ValueError, OSError):
                continue
        if self.artifacts is not None:
            for artifact in await self.artifacts.list_active(owner_user_id=self.owner, agent_key=self.agent_key):
                if Path(artifact.original_name).suffix.lower() in TEXT_SUFFIXES:
                    try:
                        await self.artifacts.download_path(owner_user_id=self.owner, agent_key=self.agent_key, artifact_id=artifact.id)
                        items.append(self._entry("artifact", artifact.id, artifact.original_name, artifact.relative_path))
                    except (ValueError, OSError):
                        continue
        return items

    async def resolve(self, refs):
        if not isinstance(refs, list) or len(refs) > 5:
            raise HTTPException(400, "invalid_file_references")
        result, seen = [], set()
        for ref in refs:
            if (not isinstance(ref, dict) or set(ref) != {"source", "id"}
                    or ref.get("source") not in SOURCES or not isinstance(ref.get("id"), str)):
                raise HTTPException(400, "invalid_file_references")
            source, identifier = ref["source"], ref["id"]
            if (source, identifier) in seen:
                continue
            seen.add((source, identifier))
            try:
                if source == "personal_library":
                    doc = await self.library.read_text_for_agent(owner_user_id=self.owner,
                        agent_key=self.agent_key, document_id=UUID(identifier), limit=65_536)
                    result.append({**self._entry(source, identifier, doc.document.name, doc.document.relative_path),
                        "content": doc.content, "truncated": doc.truncated})
                    continue
                if source == "agent_profile":
                    path = self._profile_path(identifier)
                    name = identifier
                elif source == "temporary":
                    record = await self.attachments.get_attachment(attachment_id=UUID(identifier), owner_user_id=self.owner)
                    if not self._temporary_allowed(record):
                        raise FileNotFoundError(identifier)
                    path, name = Path(record.storage_key), record.original_name
                else:
                    record, path = await self.artifacts.download_path(owner_user_id=self.owner,
                        agent_key=self.agent_key, artifact_id=UUID(identifier))
                    name = record.original_name
                if Path(name).suffix.lower() not in TEXT_SUFFIXES or path.is_symlink():
                    raise ValueError("unsupported_reference")
                with path.open("rb") as stream:
                    data = stream.read(65_537)
                result.append({**self._entry(source, identifier, name, name),
                    "content": data[:65_536].decode("utf-8", errors="replace"), "truncated": len(data) > 65_536})
            except (ValueError, OSError, PermissionError) as exc:
                raise HTTPException(404, "file_reference_unavailable") from exc
        return result
