"""Trusted user scopes for transient runtime events."""

from uuid import UUID

from fastapi import HTTPException, Request

from ..access.dependencies import get_actor
from ..identity.runtime import is_multi_user_enabled


def execution_user_id(context: dict | None) -> str | None:
    """Only the server-issued actor snapshot establishes event ownership."""
    actor = (context or {}).get("actor_context")
    value = actor.get("user_id") if isinstance(actor, dict) else None
    try:
        return str(UUID(str(value))) if value else None
    except ValueError:
        return None


def request_user_id(request: Request) -> str | None:
    if not is_multi_user_enabled():
        return None
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=403, detail="forbidden")
    return str(actor.user_id)


def event_scope(agent_id: str, user_id: str | None) -> tuple[str, str | None]:
    if is_multi_user_enabled() and not user_id:
        raise ValueError("Runtime event requires a trusted user identity")
    return agent_id, user_id if is_multi_user_enabled() else None
