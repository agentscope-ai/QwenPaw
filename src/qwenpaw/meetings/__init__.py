# -*- coding: utf-8 -*-
"""qwenpaw Multi-Agent Meeting System.

A module that enables multiple agents to collaborate in meeting scenarios,
simulating real meeting discussions for complex decision-making tasks.
"""

from .models import (
    MeetingType,
    RoleType,
    MeetingStatus,
    PhaseType,
    MeetingTopic,
    MeetingParticipant,
    AgentEndpoint,
    MeetingFlow,
    MeetingConfig,
    MeetingDocument,
    PromptsConfig,
)
from .manager import MeetingManager
from .storage import MeetingStorage
from .repo_meetings import MeetingRepository
from .rpc import SACPClient

__version__ = "0.1.0"

__all__ = [
    # Types
    "MeetingType",
    "RoleType",
    "MeetingStatus",
    "PhaseType",
    # Models
    "MeetingTopic",
    "MeetingParticipant",
    "AgentEndpoint",
    "MeetingFlow",
    "MeetingConfig",
    "MeetingDocument",
    "PromptsConfig",
    # Core
    "MeetingManager",
    "MeetingStorage",
    "MeetingRepository",
    "SACPClient",
]
