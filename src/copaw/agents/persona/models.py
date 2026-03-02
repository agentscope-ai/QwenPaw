# -*- coding: utf-8 -*-
"""Persona models for CoPaw role management.

This module defines data models for persona (role) specification
and management, allowing different agent behaviors per channel/user.

Example:
    >>> from copaw.agents.persona import PersonaSpec, PersonaScope
    >>>
    >>> # Create a work assistant persona for DingTalk
    >>> persona = PersonaSpec(
    ...     name="工作助手",
    ...     description="专业的职场助手",
    ...     system_prompt_addon="使用正式、专业的语言。",
    ...     scope=PersonaScope.CHANNEL,
    ...     channel="dingtalk",
    ... )
"""
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import uuid4


class PersonaScope(str, Enum):
    """Persona application scope.

    Defines where a persona applies:
    - GLOBAL: Default persona for all contexts
    - CHANNEL: Persona for specific channel (e.g., dingtalk, feishu)
    - USER: Persona for specific user across channels
    - USER_CHANNEL: Persona for specific user in specific channel
    """
    GLOBAL = "global"
    CHANNEL = "channel"
    USER = "user"
    USER_CHANNEL = "user_channel"


class PersonaSpec(BaseModel):
    """Persona specification.

    Attributes:
        id: Unique identifier for the persona
        name: Display name (e.g., "工作助手", "老师")
        description: Human-readable description
        system_prompt_addon: Text to append to system prompt
        scope: The scope of persona application
        channel: Channel name (for CHANNEL/USER_CHANNEL scope)
        user_id: User identifier (for USER/USER_CHANNEL scope)
        enabled: Whether the persona is currently active
        created_at: When the persona was created
    """
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str
    system_prompt_addon: str = ""

    # Scope configuration
    scope: PersonaScope = PersonaScope.GLOBAL
    channel: Optional[str] = None
    user_id: Optional[str] = None

    # Status
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        """Pydantic model config."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            PersonaScope: lambda v: v.value,
        }

    def is_applicable_to(
        self,
        channel: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """Check if this persona applies to the given context.

        Args:
            channel: Channel name to check
            user_id: User ID to check

        Returns:
            True if the persona applies to the given context
        """
        if not self.enabled:
            return False

        if self.scope == PersonaScope.GLOBAL:
            return True
        elif self.scope == PersonaScope.CHANNEL:
            return self.channel == channel
        elif self.scope == PersonaScope.USER:
            return self.user_id == user_id
        elif self.scope == PersonaScope.USER_CHANNEL:
            return (
                self.channel == channel and
                self.user_id == user_id
            )

        return False

    def get_priority_score(
        self,
        channel: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """Get priority score for persona selection.

        Higher score = more specific = higher priority.

        Args:
            channel: Channel name
            user_id: User ID

        Returns:
            Priority score (0 if not applicable, 1-4 if applicable)
        """
        if not self.is_applicable_to(channel=channel, user_id=user_id):
            return 0

        # Priority order: GLOBAL < CHANNEL < USER < USER_CHANNEL
        if self.scope == PersonaScope.GLOBAL:
            return 1
        elif self.scope == PersonaScope.CHANNEL:
            return 2
        elif self.scope == PersonaScope.USER:
            return 3
        elif self.scope == PersonaScope.USER_CHANNEL:
            return 4

        return 0


__all__ = ["PersonaScope", "PersonaSpec"]
