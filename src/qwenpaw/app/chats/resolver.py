# -*- coding: utf-8 -*-
"""Resolve Console Chat references without starting agent workspaces."""

from pathlib import Path

from pydantic import BaseModel

from .models import ChatSpec
from .repo.json_repo import JsonChatRepository
from ...config.config import Config
from ...utils.io_utils import read_json_async


class ChatResolution(BaseModel):
    """An agent and the persisted Chat identity that it owns."""

    agent_id: str
    chat: ChatSpec


def is_app_owned_chat(chat: ChatSpec) -> bool:
    """Return whether a Chat belongs to a PawApp dialogue surface."""
    owner = chat.meta.get(f"pawapp") if isinstance(chat.meta, dict) else None
    return isinstance(owner, dict) and bool(owner.get(f"app_id"))


async def _available_in_console(workspace_dir: Path) -> bool:
    """Read the ownership marker without migrating or creating a profile."""
    try:
        profile = await read_json_async(workspace_dir / f"agent.json")
    except FileNotFoundError:
        return True
    template_id = profile.get(f"template_id") or f""
    return not template_id.startswith(f"pawapp:")


async def find_chat_matches(
    config: Config,
    reference_id: str,
    current_agent_id: str | None,
) -> list[ChatResolution]:
    """Prefer global Chat IDs to aliases scoped to the current agent."""
    exact_matches = []
    alias_matches = []
    for agent_id, profile in config.agents.profiles.items():
        if not profile.enabled:
            continue
        repository = JsonChatRepository(
            Path(profile.workspace_dir) / f"chats.json",
        )
        catalog = await repository.load()
        candidates = [
            chat
            for chat in catalog.chats
            if not is_app_owned_chat(chat)
            and (
                chat.id == reference_id
                or (
                    agent_id == current_agent_id
                    and chat.session_id == reference_id
                )
            )
        ]
        if not candidates or not await _available_in_console(
            repository.path.parent,
        ):
            continue
        for chat in candidates:
            match = ChatResolution(agent_id=agent_id, chat=chat)
            if chat.id == reference_id:
                exact_matches.append(match)
            else:
                alias_matches.append(match)
    return exact_matches or alias_matches
