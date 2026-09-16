"""Authorized fixed-version installation and explicit private-copy reconciliation."""

from contextlib import ExitStack
from pathlib import Path

from ..agents.skill_system.store import (
    get_workspace_skills_dir,
    get_workspace_skill_manifest_path,
    mutate_json,
    default_workspace_manifest,
    normalize_skill_dir_name,
    safe_skill_dir,
    read_skill_manifest,
    workspace_skill_write_lock,
)
from ..agents.skill_system.workspace_service import SkillService
from .snapshots import directory_hash, validate_name
from ..access.service import AuthorizationDeniedError


class SkillLifecycleService:
    def __init__(self, governance, workspace_resolver):
        self.governance = governance
        self.repository = governance.repository
        self.workspace_resolver = workspace_resolver

    @staticmethod
    def _state(name, root, binding, catalog):
        safe_skill_dir(root, name)
        actual = directory_hash(root / name, shared=False)
        bound = (
            binding is not None and binding.get("source_pool_version_id") is not None
        )
        active = next(
            (
                item
                for item in catalog
                if bound and str(item["id"]) == str(binding["skill_id"])
            ),
            None,
        )
        return {
            "name": name,
            "source_pool_version_id": (
                str(binding["source_pool_version_id"]) if bound else None
            ),
            "source_pool_version": binding["source_pool_version"] if bound else None,
            "detached": bool(bound and actual != binding["source_content_hash"]),
            "update_available": bool(
                active
                and str(active["version_id"]) != str(binding["source_pool_version_id"])
            ),
            "content_hash": actual,
        }

    async def list_installed(self, actor, agent_id):
        await self.governance.require_agent_editor(actor, agent_id)
        workspace = Path(self.workspace_resolver(agent_id))
        with workspace_skill_write_lock(workspace):
            root = get_workspace_skills_dir(workspace)
            catalog = await self.repository.list_items(agent_id)
            async with self.repository.lifecycle_transaction() as session:
                bindings = await self.repository.installed(agent_id, session=session)
                rows = []
                names = set(read_skill_manifest(workspace).get("skills", {})) | set(
                    bindings
                )
                for name in sorted(names):
                    safe_skill_dir(root, name)
                    bound = bindings.get(name)
                    if not (root / name).is_dir() or (
                        not (root / name / "SKILL.md").is_file()
                        and not (bound and bound["source_pool_version_id"])
                    ):
                        continue
                    state = self._state(name, root, bindings.get(name), catalog)
                    await self.repository.mark_detached(
                        session, agent_id, name, state["detached"]
                    )
                    rows.append(state)
        return {"items": rows}

    async def delete(self, actor, agent_id, name):
        """Explicit deletion ends this installation's source; damaged files do not."""
        await self.governance.require_agent_editor(actor, agent_id)
        name = normalize_skill_dir_name(name)
        workspace = Path(self.workspace_resolver(agent_id))
        service = SkillService(workspace)
        with workspace_skill_write_lock(workspace), ExitStack() as changes:
            async with self.repository.lifecycle_transaction() as session:
                await self.repository.lock_agent_editor(session, agent_id, actor=actor)
                changes.enter_context(service.skill_files_transaction(name))
                service.disable_skill(name)
                deleted = service.delete_skill(name)
                if deleted:
                    await self.repository.unbind_installed(session, agent_id, name)
        return deleted

    async def save(self, actor, agent_id, **values):
        """Save a private copy without losing its database identity on rename."""
        await self.governance.require_agent_editor(actor, agent_id)
        workspace = Path(self.workspace_resolver(agent_id))
        old_name = normalize_skill_dir_name(values["skill_name"])
        with workspace_skill_write_lock(workspace), ExitStack() as changes:
            async with self.repository.lifecycle_transaction() as session:
                await self.repository.lock_agent_editor(session, agent_id, actor=actor)
                result = changes.enter_context(
                    SkillService(workspace).save_skill_transaction(**values)
                )
                if result.get("success"):
                    name = result["name"]
                    if result["mode"] == "rename":
                        await self.repository.rename_installed(
                            session, agent_id, old_name, name
                        )
                    binding = (
                        await self.repository.installed(agent_id, session=session)
                    ).get(name)
                    if binding and binding["source_pool_version_id"]:
                        state = self._state(
                            name, get_workspace_skills_dir(workspace), binding, []
                        )
                        await self.repository.mark_detached(
                            session, agent_id, name, state["detached"]
                        )

                        def mirror(payload):
                            payload["skills"][name].update(
                                source_pool_version_id=state["source_pool_version_id"],
                                source_pool_version=state["source_pool_version"],
                                source_content_hash=binding["source_content_hash"],
                                detached=state["detached"],
                            )

                        mutate_json(
                            get_workspace_skill_manifest_path(workspace),
                            default_workspace_manifest(),
                            mirror,
                        )
        return result

    async def install(
        self, actor, agent_id, skill_id, *, overwrite=False, expected_content_hash=None
    ):
        version = await self.governance.require_loadable(actor, agent_id, skill_id)
        return await self._replace(
            actor,
            agent_id,
            version,
            overwrite=overwrite,
            expected=expected_content_hash,
        )

    async def _bound_version(self, actor, agent_id, name, restore):
        await self.governance.require_agent_editor(actor, agent_id)
        name = normalize_skill_dir_name(name)
        bound = (await self.repository.installed(agent_id)).get(name)
        if not bound or not bound["source_pool_version_id"]:
            raise ValueError("skill_source_required")
        if restore:
            return await self.governance.require_agent_version(
                actor, agent_id, bound["source_pool_version_id"]
            )
        return await self.governance.require_loadable(
            actor, agent_id, bound["skill_id"]
        )

    async def update(self, actor, agent_id, name, expected_content_hash):
        version = await self._bound_version(actor, agent_id, name, False)
        return await self._replace(
            actor,
            agent_id,
            version,
            overwrite=True,
            expected=expected_content_hash,
            bound_name=name,
        )

    async def restore(self, actor, agent_id, name, expected_content_hash):
        version = await self._bound_version(actor, agent_id, name, True)
        return await self._replace(
            actor,
            agent_id,
            version,
            overwrite=True,
            expected=expected_content_hash,
            bound_name=name,
            restore=True,
        )

    async def broadcast(
        self, actor, skill_id, agent_ids, *, overwrite=False, preview_only=False,
        confirmations=None,
    ):
        self.governance.require_manage(actor)
        return await self._batch(
            skill_id,
            agent_ids,
            automatic=False,
            overwrite=overwrite,
            preview_only=preview_only,
            confirmations=confirmations,
        )

    async def auto_update(self, skill_id, agent_ids):
        """Trusted scheduler entry: Agent keys come from server config, never a fabricated actor."""
        return await self._batch(
            skill_id, agent_ids, automatic=True, overwrite=True, preview_only=False
        )

    async def _batch(
        self, skill_id, agent_ids, *, automatic, overwrite, preview_only,
        confirmations=None,
    ):
        if not agent_ids:
            return {"results": [], "reason": "no_trusted_targets"}
        results, plans = [], []
        # Every compensating file context outlives the single all-target DB transaction.
        with ExitStack() as changes:
            async with self.repository.lifecycle_transaction() as session:
                for agent_id in sorted(set(agent_ids)):
                    result = {"agent_id": agent_id, "status": "skipped", "reason": ""}
                    results.append(result)
                    try:
                        item = await self.repository.lock_lifecycle_authority(
                            session, agent_id, skill_id, internal=True
                        )
                    except AuthorizationDeniedError:
                        result["reason"] = "not_authorized"
                        continue
                    workspace = Path(self.workspace_resolver(agent_id))
                    changes.enter_context(workspace_skill_write_lock(workspace))
                    name = validate_name(item["name"])
                    bindings = await self.repository.installed(
                        agent_id, session=session
                    )
                    if name not in bindings:
                        renamed = [
                            key
                            for key, value in bindings.items()
                            if str(value.get("skill_id")) == str(skill_id)
                        ]
                        if len(renamed) == 1:
                            name = normalize_skill_dir_name(renamed[0])
                    bound = bindings.get(name)
                    safe_skill_dir(get_workspace_skills_dir(workspace), name)
                    target = get_workspace_skills_dir(workspace) / name
                    actual = (
                        directory_hash(target, shared=False) if target.exists() else None
                    )
                    version_id = str(item["current_version_id"])
                    confirmation = (confirmations or {}).get(agent_id)
                    if not automatic and not preview_only:
                        if confirmation and confirmation.get("expected_version_id") != version_id:
                            result.update(status="failed", reason="source_version_changed")
                            continue
                        if confirmation and (
                            "expected_content_hash" not in confirmation
                            or confirmation["expected_content_hash"] != actual
                        ):
                            result.update(status="failed", reason="content_conflict")
                            continue
                    if automatic and (not bound or not bound["source_pool_version_id"]):
                        result["reason"] = "skill_source_required"
                        continue
                    if target.exists():
                        if (
                            not bound
                            or not bound["source_pool_version_id"]
                            or str(bound["skill_id"]) != str(skill_id)
                        ):
                            result["reason"] = "skill_source_required"
                            continue
                        if actual != bound["source_content_hash"]:
                            if not preview_only:
                                await self.repository.mark_detached(
                                    session, agent_id, name, True
                                )
                            result["reason"] = "detached"
                            continue
                    elif automatic:
                        result["reason"] = "skill_missing"
                        continue
                    if not automatic and not preview_only and (
                        not confirmation or not overwrite
                    ):
                        result.update(status="failed", reason="confirmation_required")
                        continue
                    version = await self.repository.get_version(
                        item["current_version_id"]
                    )
                    fixed = self.governance.snapshots.verify(
                        version["content_key"], version["content_hash"]
                    )
                    result.update(
                        name=name,
                        expected_content_hash=actual,
                        expected_version_id=str(version["id"]),
                    )
                    if (
                        bound
                        and str(bound["source_pool_version_id"]) == str(version["id"])
                        and target.exists()
                    ):
                        result.update(status="unchanged", reason="")
                        continue
                    plans.append(
                        (
                            workspace,
                            name,
                            version,
                            fixed,
                            result,
                            actual,
                        )
                    )
                for workspace, name, version, fixed, result, expected in plans:
                    if preview_only:
                        result.update(status="ready", reason="")
                        continue
                    target = get_workspace_skills_dir(workspace) / name
                    current = (
                        directory_hash(target, shared=False)
                        if target.exists()
                        else None
                    )
                    if current != expected:
                        raise ValueError("content_conflict")
                    entry = changes.enter_context(
                        SkillService(workspace).install_verified_snapshot(
                            name, fixed, version, expected_content_hash=expected
                        )
                    )
                    await self.repository.bind_installed(
                        session, result["agent_id"], name, version, entry["enabled"]
                    )
                    result.update(
                        status="updated",
                        reason="",
                        name=name,
                        source_pool_version_id=str(version["id"]),
                    )
        return {"results": results}

    async def _replace(
        self,
        actor,
        agent_id,
        version,
        *,
        overwrite,
        expected,
        bound_name=None,
        restore=False,
    ):
        workspace = Path(self.workspace_resolver(agent_id))
        with workspace_skill_write_lock(workspace), ExitStack() as changes:
            async with self.repository.lifecycle_transaction() as session:
                item = await self.repository.lock_lifecycle_authority(
                    session, agent_id, version["skill_id"], actor=actor
                )
                name = (
                    normalize_skill_dir_name(bound_name)
                    if bound_name
                    else validate_name(item["name"])
                )
                safe_skill_dir(get_workspace_skills_dir(workspace), name)
                binding = (
                    await self.repository.installed(agent_id, session=session)
                ).get(name)
                if bound_name and (
                    not binding
                    or not binding["source_pool_version_id"]
                    or str(binding["skill_id"]) != str(version["skill_id"])
                ):
                    raise ValueError("skill_source_changed")
                if restore and str(binding["source_pool_version_id"]) != str(
                    version["id"]
                ):
                    raise ValueError("skill_source_changed")
                if not restore and str(item["current_version_id"]) != str(
                    version["id"]
                ):
                    raise ValueError("skill_version_changed")
                target = get_workspace_skills_dir(workspace) / name
                exists = target.exists()
                if exists and not overwrite:
                    raise ValueError("skill_conflict")
                if exists and (
                    expected is None or directory_hash(target, shared=False) != expected
                ):
                    raise ValueError("content_conflict")
                if not exists and expected is not None:
                    raise ValueError("content_conflict")
                fixed = self.governance.snapshots.verify(
                    version["content_key"], version["content_hash"]
                )
                entry = changes.enter_context(
                    SkillService(workspace).install_verified_snapshot(
                        name, fixed, version, expected_content_hash=expected
                    )
                )
                await self.repository.bind_installed(
                    session, agent_id, name, version, entry["enabled"]
                )
            # ExitStack keeps compensation live until the transaction context commits.
        return {
            "name": name,
            "source_pool_version_id": str(version["id"]),
            "source_pool_version": version["version"],
            "detached": False,
            "update_available": str(item["current_version_id"]) != str(version["id"]),
            "content_hash": version["content_hash"],
        }
