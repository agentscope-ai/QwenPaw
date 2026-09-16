"""Authorization precedes filesystem access and transactional persistence."""

from pathlib import Path
from ..access.capabilities import Capability
from ..access.service import AuthorizationDeniedError, AuthorizationService
from .records import catalog_skill
from .snapshots import directory_hash, validate_name


class SkillGovernanceService:
    def __init__(self, repository, snapshots, pool_root):
        self.repository = repository
        self.snapshots = snapshots
        self.pool_root = Path(pool_root)

    @staticmethod
    def require_manage(actor):
        AuthorizationService().require(actor, Capability.SKILLS_MANAGE)

    async def require_agent_editor(self, actor, agent_id, *, owner_only=False):
        AuthorizationService().require(actor, Capability.AGENT_USE)
        role = await self.repository.agent_role(actor.user_id, agent_id)
        if role not in ({"owner"} if owner_only else {"owner", "collaborator"}):
            raise AuthorizationDeniedError()

    async def list_catalog(self, actor, agent_id):
        await self.require_agent_editor(actor, agent_id)
        return {
            "items": [
                catalog_skill(row) for row in await self.repository.list_items(agent_id)
            ]
        }

    async def require_loadable(self, actor, agent_id, skill_id):
        for row in (await self.list_catalog(actor, agent_id))["items"]:
            if row["id"] == str(skill_id):
                version = await self.repository.get_version(row["version_id"])
                self.snapshots.verify(version["content_key"], version["content_hash"])
                return version
        raise AuthorizationDeniedError()

    async def require_agent_version(self, actor, agent_id, version_id):
        """Validate current authority for a chosen current or historical version."""
        await self.require_agent_editor(actor, agent_id)
        version = await self.repository.get_version(version_id)
        allowed = await self.repository.list_items(agent_id)
        if not any(str(row["id"]) == str(version["skill_id"]) for row in allowed):
            raise AuthorizationDeniedError()
        self.snapshots.verify(version["content_key"], version["content_hash"])
        return version

    async def preview_existing(self, actor):
        self.require_manage(actor)
        if not self.pool_root.exists():
            return []
        result = []
        for source in sorted(self.pool_root.iterdir()):
            if source.is_dir():
                validate_name(source.name)
                result.append(
                    {"name": source.name, "content_hash": directory_hash(source)}
                )
        return result

    async def import_existing(self, actor, preview):
        self.require_manage(actor)
        staged = []
        for item in preview:
            name = validate_name(item["name"])
            source = self.pool_root / name
            if directory_hash(source) != item["content_hash"]:
                raise ValueError("initialization_preview_changed")
            snapshot = self.snapshots.capture(source, name)
            if snapshot.content_hash != item["content_hash"]:
                raise ValueError("initialization_preview_changed")
            staged.append((name, snapshot))
        await self.repository.import_snapshots(staged, actor.user_id, self.snapshots)
        return {"imported": len(staged)}

    async def set_agent_grant(self, actor, skill_id, agent_id, enabled):
        self.require_manage(actor)
        return await self.repository.set_agent_grant(
            skill_id, agent_id, enabled, actor.user_id
        )

    async def set_item_status(self, actor, skill_id, enabled):
        self.require_manage(actor)
        return await self.repository.set_item_status(skill_id, enabled, actor.user_id)

    async def submit_request(self, actor, agent_id, skill_name, source):
        await self.require_agent_editor(actor, agent_id, owner_only=True)
        snapshot = self.snapshots.capture(source, validate_name(skill_name))
        return await self.repository.create_request(
            agent_id, skill_name, snapshot, actor.user_id
        )

    async def _request_snapshot(self, actor, request_id):
        self.require_manage(actor)
        row = await self.repository.get_request(request_id)
        if not row["snapshot_key"] or not row["content_hash"]:
            raise ValueError("request_snapshot_required")
        root = self.snapshots.verify(row["snapshot_key"], row["content_hash"])
        return row, root

    async def request_detail(self, actor, request_id):
        row, root = await self._request_snapshot(actor, request_id)
        return {
            "id": str(row["id"]),
            "skill_name": row["skill_name"],
            "status": row["status"],
            "review_version": row["review_version"],
            "content_hash": row["content_hash"],
            "files": sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            ),
        }

    async def request_file(self, actor, request_id, file_path):
        _, root = await self._request_snapshot(actor, request_id)
        parts = file_path.replace("\\", "/").split("/")
        if any(part in {"", ".", ".."} or ":" in part for part in parts):
            raise ValueError("invalid_skill_file")
        path = root.joinpath(*parts)
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("invalid_skill_file")
        try:
            return {"content": path.read_text(encoding="utf-8")}
        except UnicodeError as exc:
            raise ValueError("binary_skill_file") from exc

    async def review_request(self, actor, request_id, decision, expected_version, note):
        self.require_manage(actor)
        if decision not in {"approve", "reject"}:
            raise ValueError("invalid_review_decision")
        return await self.repository.review_request(
            request_id, decision, expected_version, note, actor.user_id, self.snapshots
        )
