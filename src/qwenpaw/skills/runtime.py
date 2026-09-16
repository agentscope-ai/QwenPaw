"""Explicit PostgreSQL assembly; authority failures never fall back to Legacy."""

from ..agents.skill_system.store import get_skill_pool_dir
from ..identity.runtime import get_identity_schema, is_multi_user_enabled
from .repository import PostgresSkillRepository
from .service import SkillGovernanceService
from .snapshots import SnapshotStore


def get_skill_service():
    if not is_multi_user_enabled():
        raise ValueError("postgres_governance_required")
    root = get_skill_pool_dir()
    return SkillGovernanceService(
        PostgresSkillRepository(schema=get_identity_schema()),
        SnapshotStore(root.parent / "skill_snapshots"),
        root,
    )


def resolve_agent_workspace(agent_id):
    from pathlib import Path
    from ..config.utils import load_config
    from ..access.service import AuthorizationDeniedError

    profile = load_config().agents.profiles.get(agent_id)
    if profile is None or not getattr(profile, "enabled", True):
        raise AuthorizationDeniedError()
    return Path(profile.workspace_dir)


def get_skill_lifecycle_service():
    from .lifecycle import SkillLifecycleService

    return SkillLifecycleService(get_skill_service(), resolve_agent_workspace)
