# -*- coding: utf-8 -*-
"""Persona Manager for CoPaw.

This module provides persona (role) management capabilities for CoPaw,
allowing different agent behaviors per channel and user.

Features:
- Create, read, update, delete personas
- Scope-based persona application
- Priority-based selection (USER_CHANNEL > USER > CHANNEL > GLOBAL)
- Persistent storage with JSON backend

Example:
    >>> from copaw.agents.persona import PersonaManager, PersonaScope
    >>>
    >>> manager = PersonaManager()
    >>> await manager.load()
    >>>
    >>> # Create a persona for DingTalk work assistant
    >>> await manager.create_persona(
    ...     name="工作助手",
    ...     description="专业的职场助手，使用正式语言",
    ...     system_prompt_addon="你是一个专业的职场助手。使用正式、专业的语言。",
    ...     scope=PersonaScope.CHANNEL,
    ...     channel="dingtalk",
    ... )
    >>>
    >>> # Get active persona for context
    >>> persona = await manager.get_active_persona(
    ...     channel="dingtalk",
    ...     user_id="user123",
    ... )
"""
import json
import asyncio
from pathlib import Path
from typing import Optional, List

from .models import PersonaSpec, PersonaScope

__all__ = ["PersonaManager"]


class PersonaManager:
    """Persona manager for role-based agent behavior.

    This manager handles:
    - Persona CRUD operations
    - Scope-based persona filtering
    - Priority-based selection
    - JSON file persistence

    Attributes:
        save_dir: Directory where personas are stored
        personas_file: Path to the personas.json file
    """

    def __init__(self, save_dir: str = "~/.copaw/personas"):
        """Initialize PersonaManager.

        Args:
            save_dir: Directory to store persona files
        """
        self.save_dir = Path(save_dir).expanduser()
        self.save_dir.mkdir(parents=True, exist_ok=True)

        self._personas: dict[str, PersonaSpec] = {}
        self._lock = asyncio.Lock()
        self._personas_file = self.save_dir / "personas.json"

    @property
    def personas_file(self) -> Path:
        """Get the personas file path."""
        return self._personas_file

    async def load(self) -> None:
        """Load personas from disk.

        Reads personas.json and populates the in-memory cache.
        If the file doesn't exist, starts with an empty persona set.
        """
        async with self._lock:
            if not self._personas_file.exists():
                return

            try:
                data = json.loads(self._personas_file.read_text(encoding="utf-8"))
                for persona_data in data.get("personas", []):
                    persona = PersonaSpec(**persona_data)
                    self._personas[persona.id] = persona
            except (json.JSONDecodeError, KeyError) as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to load personas: {e}")

    async def save(self) -> None:
        """Save personas to disk."""
        async with self._lock:
            await self._persist()

    async def create_persona(
        self,
        name: str,
        description: str,
        system_prompt_addon: str = "",
        scope: PersonaScope = PersonaScope.GLOBAL,
        channel: Optional[str] = None,
        user_id: Optional[str] = None,
        enabled: bool = True,
    ) -> PersonaSpec:
        """Create a new persona.

        Args:
            name: Persona display name
            description: Human-readable description
            system_prompt_addon: Text to append to system prompt
            scope: Persona application scope
            channel: Channel name (for CHANNEL/USER_CHANNEL scope)
            user_id: User ID (for USER/USER_CHANNEL scope)
            enabled: Whether the persona is initially enabled

        Returns:
            The created PersonaSpec

        Raises:
            ValueError: If scope-channel/user_id mismatch
        """
        # Validate scope-specific fields
        if scope in (PersonaScope.CHANNEL, PersonaScope.USER_CHANNEL) and not channel:
            raise ValueError("channel is required for CHANNEL/USER_CHANNEL scope")
        if scope in (PersonaScope.USER, PersonaScope.USER_CHANNEL) and not user_id:
            raise ValueError("user_id is required for USER/USER_CHANNEL scope")

        persona = PersonaSpec(
            name=name,
            description=description,
            system_prompt_addon=system_prompt_addon,
            scope=scope,
            channel=channel,
            user_id=user_id,
            enabled=enabled,
        )

        async with self._lock:
            self._personas[persona.id] = persona
            await self._persist()

        return persona

    async def get_persona(self, persona_id: str) -> Optional[PersonaSpec]:
        """Get a persona by ID."""
        async with self._lock:
            return self._personas.get(persona_id)

    async def delete_persona(self, persona_id: str) -> bool:
        """Delete a persona by ID."""
        async with self._lock:
            if persona_id not in self._personas:
                return False
            del self._personas[persona_id]
            await self._persist()
            return True

    async def update_persona(
        self,
        persona_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        system_prompt_addon: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[PersonaSpec]:
        """Update an existing persona."""
        async with self._lock:
            if persona_id not in self._personas:
                return None

            persona = self._personas[persona_id]
            if name is not None:
                persona.name = name
            if description is not None:
                persona.description = description
            if system_prompt_addon is not None:
                persona.system_prompt_addon = system_prompt_addon
            if enabled is not None:
                persona.enabled = enabled

            await self._persist()
            return persona

    async def list_personas(
        self,
        scope: Optional[PersonaScope] = None,
        enabled_only: bool = True,
    ) -> List[PersonaSpec]:
        """List all personas with optional filtering."""
        async with self._lock:
            personas = []
            for p in self._personas.values():
                if enabled_only and not p.enabled:
                    continue
                if scope is not None and p.scope != scope:
                    continue
                personas.append(p)
            return personas

    async def get_active_persona(
        self,
        channel: str,
        user_id: str,
    ) -> Optional[PersonaSpec]:
        """Get the active persona for the given context.

        Selects the persona with highest priority score:
        - USER_CHANNEL (4) > USER (3) > CHANNEL (2) > GLOBAL (1)

        Args:
            channel: Channel name
            user_id: User identifier

        Returns:
            The PersonaSpec with highest priority, or None if no persona applies
        """
        async with self._lock:
            candidates = []
            for persona in self._personas.values():
                score = persona.get_priority_score(
                    channel=channel,
                    user_id=user_id,
                )
                if score > 0:
                    candidates.append((score, persona))

            if not candidates:
                return None

            # Sort by score (highest first)
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

    async def enable_persona(self, persona_id: str) -> bool:
        """Enable a persona."""
        async with self._lock:
            if persona_id not in self._personas:
                return False
            self._personas[persona_id].enabled = True
            await self._persist()
            return True

    async def disable_persona(self, persona_id: str) -> bool:
        """Disable a persona."""
        async with self._lock:
            if persona_id not in self._personas:
                return False
            self._personas[persona_id].enabled = False
            await self._persist()
            return True

    async def _persist(self) -> None:
        """Persist personas to disk atomically."""
        data = {
            "version": 1,
            "personas": [
                p.model_dump(mode="json")
                for p in self._personas.values()
            ],
        }

        tmp_path = self._personas_file.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._personas_file)

    async def clear_all(self) -> None:
        """Clear all personas."""
        async with self._lock:
            self._personas.clear()
            await self._persist()
